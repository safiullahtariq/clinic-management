from datetime import datetime, timedelta, timezone
from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from memberships.models import Membership, CreditLedger
from .models import Resource, Booking, DoctorShift
from tenancy.models import Organization, AdminNotification
from tenancy.emails import email_service_booked, email_booking_canceled

class PublicResourcesAPIView(APIView):
    def get(self, request):
        tenant = getattr(request, 'tenant', None)
        if not tenant:
            return Response({"error": "Tenant not resolved."}, status=status.HTTP_404_NOT_FOUND)
        resources = Resource.objects.filter(organization=tenant, is_active=True).order_by('credit_cost')
        data = [{
            "id": str(r.id),
            "name": r.name,
            "duration_minutes": r.duration_minutes,
            "credit_cost": r.credit_cost,
            "capacity": r.capacity
        } for r in resources]
        return Response(data)

class ResourceSlotsAPIView(APIView):
    def get(self, request, resource_id):
        # Fallback slot calculator
        return Response([])

@require_GET
def get_available_slots_api(request):
    """
    Returns shift slots for doctor and date, marking:
    - is_booked: False (Clickable)
    - is_booked: True (Disabled)
    """
    org_slug = request.GET.get('org')
    doctor_id = request.GET.get('doctor_id')
    resource_id = request.GET.get('resource_id')
    date_str = request.GET.get('date')

    if not all([org_slug, doctor_id, resource_id, date_str]):
        return JsonResponse({'error': 'Missing required query parameters'}, status=400)

    try:
        booking_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'error': 'Invalid date format. Use YYYY-MM-DD'}, status=400)

    tenant = Organization.objects.filter(slug=org_slug).first()
    if not tenant:
        return JsonResponse({'error': 'Clinic organization not found'}, status=404)

    doctor = User.objects.filter(id=doctor_id).first()
    resource = Resource.objects.filter(id=resource_id, organization=tenant).first()

    if not doctor or not resource:
        return JsonResponse({'error': 'Doctor or Service not found'}, status=404)

    day_of_week = booking_date.weekday()
    day_name = booking_date.strftime('%A')

    shift = DoctorShift.objects.filter(
        organization=tenant,
        doctor=doctor,
        day_of_week=day_of_week,
        is_active=True
    ).first()

    if not shift:
        return JsonResponse({
            'slots': [],
            'message': f"Dr. {doctor.username} has no scheduled shift on {day_name}s."
        })

    existing_bookings = Booking.objects.filter(
        organization=tenant,
        doctor=doctor,
        start_time__date=booking_date,
    ).exclude(status='canceled').values_list('start_time', 'end_time')

    busy_intervals = [(b_start.time(), b_end.time()) for b_start, b_end in existing_bookings]

    slot_duration = timedelta(minutes=resource.duration_minutes)
    current_dt = datetime.combine(booking_date, shift.start_time)
    shift_end_dt = datetime.combine(booking_date, shift.end_time)

    all_slots = []
    while current_dt + slot_duration <= shift_end_dt:
        slot_start_time = current_dt.time()
        slot_end_time = (current_dt + slot_duration).time()

        is_booked = False
        for busy_start, busy_end in busy_intervals:
            if max(slot_start_time, busy_start) < min(slot_end_time, busy_end):
                is_booked = True
                break

        all_slots.append({
            'start_time': slot_start_time.strftime('%H:%M'),
            'end_time': slot_end_time.strftime('%H:%M'),
            'display': f"{slot_start_time.strftime('%I:%M %p')} - {slot_end_time.strftime('%I:%M %p')}",
            'is_booked': is_booked
        })
        current_dt += slot_duration

    return JsonResponse({
        'date': date_str,
        'day_name': day_name,
        'doctor': doctor.username,
        'service': resource.name,
        'slots': all_slots
    })

class CreateBookingAPIView(APIView):
    @transaction.atomic
    def post(self, request):
        if not request.user.is_authenticated:
            return Response({"error": "Authentication required. Please sign in."}, status=status.HTTP_401_UNAUTHORIZED)

        user = request.user
        tenant = getattr(request, 'tenant', None)
        org_slug = request.GET.get('org')
        if not tenant and org_slug:
            tenant = Organization.objects.filter(slug=org_slug).first()
        if not tenant and hasattr(user, 'profile') and user.profile.organization:
            tenant = user.profile.organization

        if not tenant:
            return Response({"error": "Clinic organization not found."}, status=status.HTTP_404_NOT_FOUND)

        resource_id = request.data.get('resource_id')
        doctor_id = request.data.get('doctor_id')
        start_iso = request.data.get('start_time')
        end_iso = request.data.get('end_time')

        if not all([resource_id, start_iso, end_iso]):
            return Response({"error": "Service, start time, and end time are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            resource = Resource.objects.get(id=resource_id, organization=tenant)
        except (Resource.DoesNotExist, ValueError):
            return Response({"error": "Selected modality service not found."}, status=status.HTTP_404_NOT_FOUND)

        doctor_obj = User.objects.filter(id=doctor_id).first() if doctor_id else None

        # Active membership check
        membership = Membership.objects.select_for_update().filter(
            user=user,
            organization=tenant,
            status='active',
            credit_balance__gte=resource.credit_cost
        ).first()

        if not membership:
            return Response({
                "error": f"Requires {resource.credit_cost} active credit(s). Await Org Admin payment approval if recently joined."
            }, status=status.HTTP_400_BAD_REQUEST)

        start_time = parse_datetime(start_iso)
        end_time = parse_datetime(end_iso)

        if not start_time or not end_time:
            return Response({"error": "Invalid start or end time format."}, status=status.HTTP_400_BAD_REQUEST)

        if doctor_obj:
            is_doc_busy = Booking.objects.filter(
                doctor=doctor_obj,
                organization=tenant,
                status__in=['pending', 'waiting', 'in_consultation'],
                start_time__lt=end_time,
                end_time__gt=start_time
            ).exists()
            if is_doc_busy:
                return Response({"error": f"Dr. {doctor_obj.username} is already booked for this slot."}, status=status.HTTP_409_CONFLICT)

        # 1. Deduct Credits
        membership.credit_balance -= resource.credit_cost
        membership.save()

        # 2. Immutable Ledger
        CreditLedger.objects.create(
            organization=tenant,
            membership=membership,
            amount=-resource.credit_cost,
            transaction_type='spend',
            reason=f"Booked {resource.name}" + (f" with Dr. {doctor_obj.username}" if doctor_obj else "")
        )

        # 3. Create Booking with 'pending' status
        booking = Booking.objects.create(
            organization=tenant,
            membership=membership,
            resource=resource,
            doctor=doctor_obj,
            start_time=start_time,
            end_time=end_time,
            credits_used=resource.credit_cost,
            status='pending'
        )

        # 4. In-App Notification strictly to Receptionist Roster (NOT Org Admin)
        AdminNotification.objects.create(
            organization=tenant,
            title="New Patient Booking",
            message=f"{user.username} scheduled {resource.name} with Dr. {doctor_obj.username if doctor_obj else 'N/A'}",
            target_tab="tab-roster"
        )

        try:
            email_service_booked(booking)
        except Exception:
            pass

        return Response({
            "message": "Appointment successfully booked!",
            "booking_id": str(booking.id),
            "doctor": doctor_obj.username if doctor_obj else None,
            "remaining_credits": membership.credit_balance
        }, status=status.HTTP_201_CREATED)

class CancelBookingAPIView(APIView):
    @transaction.atomic
    def post(self, request, booking_id):
        user = request.user
        tenant = getattr(request, 'tenant', None)

        try:
            booking = Booking.objects.select_for_update().get(id=booking_id, organization=tenant)
        except Booking.DoesNotExist:
            return Response({"error": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)

        is_owner = (booking.membership.user == user)
        is_staff = user.is_superuser or (
            hasattr(user, 'profile') and user.profile.role in ['receptionist', 'doctor', 'org_admin']
        )

        if not (is_owner or is_staff):
            return Response({"error": "Unauthorized to cancel this booking."}, status=status.HTTP_403_FORBIDDEN)

        if booking.status == 'canceled':
            return Response({"error": "Booking is already canceled."}, status=status.HTTP_400_BAD_REQUEST)

        # Update status
        booking.status = 'canceled'
        booking.save()

        # Restore credits
        membership = Membership.objects.select_for_update().get(id=booking.membership.id)
        membership.credit_balance += booking.credits_used
        membership.save()

        # Audit ledger trail
        CreditLedger.objects.create(
            organization=tenant,
            membership=membership,
            amount=booking.credits_used,
            transaction_type='refund',
            reason=f"Restored credits for canceled {booking.resource.name}",
            booking_reference=str(booking.id)
        )

        try:
            email_booking_canceled(booking, booking.credits_used, membership.credit_balance)
        except Exception:
            pass

        return Response({
            "message": "Appointment canceled and credits refunded successfully.",
            "restored_credits": booking.credits_used,
            "new_balance": membership.credit_balance
        }, status=status.HTTP_200_OK)