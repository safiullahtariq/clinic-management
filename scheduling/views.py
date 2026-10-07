from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.contrib.auth.models import User
from datetime import datetime, timedelta, timezone

from memberships.models import Membership, CreditLedger
from .models import Resource, Booking
from tenancy.emails import (
    email_service_booked,
    email_booking_canceled,
    email_super_admin_audit,
)


class PublicResourcesAPIView(APIView):
    def get(self, request):
        if not request.tenant:
            return Response({"error": "Tenant not resolved."}, status=status.HTTP_404_NOT_FOUND)
        resources = Resource.objects.filter(organization=request.tenant).order_by('credit_cost')
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
        date_str = request.GET.get('date')
        if not date_str:
            return Response({"error": "Query param 'date' (YYYY-MM-DD) is required."}, status=400)

        try:
            resource = Resource.objects.get(id=resource_id, organization=request.tenant)
        except Resource.DoesNotExist:
            return Response({"error": "Resource not found."}, status=404)

        base_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        start_dt = datetime(base_date.year, base_date.month, base_date.day, 9, 0, tzinfo=timezone.utc)
        close_dt = datetime(base_date.year, base_date.month, base_date.day, 17, 0, tzinfo=timezone.utc)
        step = timedelta(minutes=resource.duration_minutes)

        slots = []
        current = start_dt
        while current + step <= close_dt:
            slot_end = current + step

            active_occupancy = Booking.objects.filter(
                resource=resource,
                status__in=['confirmed', 'pending'],
                start_time__lt=slot_end,
                end_time__gt=current
            ).count()

            slots.append({
                "start": current.isoformat(),
                "end": slot_end.isoformat(),
                "available": active_occupancy < resource.capacity,
                "remaining_capacity": resource.capacity - active_occupancy
            })
            current = slot_end

        return Response(slots)


class CreateBookingAPIView(APIView):
    @transaction.atomic
    def post(self, request):
        if not request.user.is_authenticated:
            return Response({"error": "Authentication required."}, status=status.HTTP_401_UNAUTHORIZED)
        user = request.user
        resource_id = request.data.get('resource_id')
        start_iso = request.data.get('start_time')
        end_iso = request.data.get('end_time')

        if not all([resource_id, start_iso, end_iso]):
            return Response({"error": "resource_id, start_time, and end_time are required."}, status=400)

        try:
            resource = Resource.objects.get(id=resource_id, organization=request.tenant)
        except Resource.DoesNotExist:
            return Response({"error": "Resource not found."}, status=404)

        # Sirf ACTIVE membership dhoondein jisme is service ke liye kaafi credits hon
        membership = Membership.objects.select_for_update().filter(
            user=user,
            organization=request.tenant,
            status='active',
            credit_balance__gte=resource.credit_cost
        ).first()

        if not membership:
            return Response({
                "error": f"Requires {resource.credit_cost} active credit(s). If recently purchased, wait for Org Admin payment confirmation."
            }, status=400)

        start_time = parse_datetime(start_iso)
        end_time = parse_datetime(end_iso)

        active_occupancy = Booking.objects.filter(
            resource=resource,
            status__in=['confirmed', 'pending'],
            start_time__lt=end_time,
            end_time__gt=start_time
        ).count()

        if active_occupancy >= resource.capacity:
            return Response({"error": "Slot capacity already reached."}, status=409)

        # 1. Deduct credits EXACTLY ONCE
        membership.credit_balance -= resource.credit_cost
        membership.save()

        # 2. Audit Ledger
        CreditLedger.objects.create(
            organization=request.tenant,
            membership=membership,
            amount=-resource.credit_cost,
            transaction_type='spend',
            reason=f"Booked {resource.name}"
        )

        # 3. Create booking in pending status
        booking = Booking.objects.create(
            organization=request.tenant,
            membership=membership,
            resource=resource,
            start_time=start_time,
            end_time=end_time,
            credits_used=resource.credit_cost,
            status='pending'
        )

        # 4. Email notifications to Member, Org Admin, and Super Admin (+ In-app alert)
        email_service_booked(booking)

        return Response({
            "message": "Slot successfully confirmed",
            "booking_id": str(booking.id),
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
        is_staff = user.is_superuser or (hasattr(user, 'profile') and user.profile.role in ['org_admin', 'super_admin'])

        if not (is_owner or is_staff):
            return Response({"error": "Unauthorized to cancel this booking."}, status=status.HTTP_403_FORBIDDEN)

        if booking.status == 'canceled':
            return Response({"error": "Booking is already canceled."}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Update Booking Status
        booking.status = 'canceled'
        booking.save()

        # 2. Restore Credits to Membership
        membership = Membership.objects.select_for_update().get(id=booking.membership.id)
        membership.credit_balance += booking.credits_used
        membership.save()

        # 3. Append to Audit CreditLedger
        CreditLedger.objects.create(
            organization=tenant,
            membership=membership,
            amount=booking.credits_used,
            transaction_type='refund',
            reason=f"Restored credits for canceled {booking.resource.name}",
            booking_reference=str(booking.id)
        )

        # 4. Notify Member via email
        email_booking_canceled(booking, booking.credits_used, membership.credit_balance)

        # 5. Security audit log to Super Admin
        email_super_admin_audit(
            tenant,
            user,
            "Booking Canceled & Restored",
            f"Booking #{booking.id} ({booking.resource.name}) canceled by '{user.username}'. Restored: {booking.credits_used} credits to balance."
        )

        return Response({
            "message": "Booking canceled and credits restored successfully.",
            "restored_credits": booking.credits_used,
            "new_balance": membership.credit_balance
        }, status=status.HTTP_200_OK)