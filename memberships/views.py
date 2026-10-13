import re
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib.auth import login
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.core.mail import send_mail
from tenancy.models import UserProfile, Organization,EmailOTP
from tenancy.emails import email_new_member_joined, notify_plan_purchase_pending
from .models import MembershipPlan, Membership, CreditLedger
from django.conf import settings




def founders_landing_page(request):
    """
    Renders the public tiers card page when accessed directly or 
    via Super Admin 'View Live Page' button (/?org=<slug>).
    """
    org_slug = request.GET.get('org')
    tenant = getattr(request, 'tenant', None)
    if org_slug:
        tenant = Organization.objects.filter(slug=org_slug).first() or tenant

    # Handle logged-in member tier upgrade / reservation from landing page modal
    if request.method == 'POST' and request.user.is_authenticated and 'claim_tier_upgrade' in request.POST:
        plan_id = request.POST.get('plan_id')
        try:
            chosen_plan = MembershipPlan.objects.get(id=plan_id, organization=tenant)
            with transaction.atomic():
                # Enforce the approval gate: save in 'pending_deposit' status with 0 credits
                new_membership = Membership.objects.create(
                    user=request.user,
                    organization=tenant,
                    plan=chosen_plan,
                    status='pending_deposit',
                    credit_balance=0  # Credits released only after Org Admin confirmation
                )

                # Send email and in-app notification for Org Admin approval
                notify_plan_purchase_pending(request.user, chosen_plan, tenant)

            return redirect(f"/dashboard/member/?org={tenant.slug}")
        except MembershipPlan.DoesNotExist:
            pass

    plans = []
    total_cap = 100
    claimed = 0
    remaining = 100
    progress = 0
    is_full = False

    if tenant:
        # Live query for updated plans created/edited by Org Admin
        plans = MembershipPlan.objects.filter(organization=tenant).order_by('rate_monthly')
        total_cap = getattr(tenant, 'founding_cap', 100)
        claimed = Membership.objects.filter(organization=tenant, status='active').count()
        remaining = max(0, total_cap - claimed)
        if total_cap > 0:
            progress = min(100, int((claimed / total_cap) * 100))
        is_full = (remaining <= 0)

    context = {
        'tenant': tenant,
        'plans': plans,
        'total_founding_slots': total_cap,
        'claimed_founding_slots': claimed,
        'remaining_founding_slots': remaining,
        'slots_progress_percent': progress,
        'is_slots_full': is_full,
    }
    return render(request, 'memberships/founders.html', context)

def send_otp_email(user, otp_code, tenant_name="Clinic"):
    subject = f"Your Verification Code | {tenant_name}"
    message = f"""Hello {user.first_name or user.username},

Your 6-digit email verification code is:

    {otp_code}

This code will expire in 10 minutes. If you did not create this account, please ignore this email.

Best regards,
{tenant_name} Team
"""
    send_mail(
        subject,
        message,
        getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@clinic.com'),
        [user.email],
        fail_silently=False
    )


def register_view(request):
    tenant_slug = request.GET.get('org')
    selected_plan_id = request.GET.get('plan')

    tenant = getattr(request, 'tenant', None)
    if tenant_slug:
        tenant = Organization.objects.filter(slug=tenant_slug).first() or tenant

    plans = MembershipPlan.objects.filter(organization=tenant).order_by('rate_monthly') if tenant else []
    error = None

    if request.method == 'POST':
        plan_id = request.POST.get('plan_id') or selected_plan_id
        first_name = request.POST.get('firstName', '').strip()
        last_name = request.POST.get('lastName', '').strip()
        country_code = request.POST.get('country_code', '+1').strip()
        phone_input = request.POST.get('phone_number', '').strip()

        username = request.POST.get('username', '').strip().lower()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        full_phone = f"{country_code} {phone_input}".strip() if phone_input else ""
        raw_digits = re.sub(r'\D', '', phone_input)

        if not re.match(r"^[a-zA-Z\s'-]{2,}$", first_name):
            error = "First name can only contain letters."
        elif not re.match(r"^[a-zA-Z\s'-]{2,}$", last_name):
            error = "Last name can only contain letters."
        elif country_code == '+1' and len(raw_digits) != 10:
            error = "Please enter a valid 10-digit US/CA phone number: (555) 555-1234."
        elif country_code != '+1' and not (7 <= len(raw_digits) <= 15):
            error = "Please enter a valid international phone number."
        elif not re.match(r'^[a-z][a-z0-9_]{2,19}$', username):
            error = "Username must be 3-20 characters, start with a letter, and contain only lowercase letters, numbers, or underscores."
        elif not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', email):
            error = "Please enter a valid email address."
        elif len(password) < 8:
            error = "Password must be at least 8 characters long."
        elif password != confirm_password:
            error = "Passwords do not match."
        elif User.objects.filter(username=username).exists():
            error = f"The username '{username}' is already taken."
        elif User.objects.filter(email=email).exists():
            error = f"An account with email '{email}' already exists. Please sign in."
        else:
            target_plan = MembershipPlan.objects.filter(id=plan_id, organization=tenant).first() or (plans.first() if plans else None)
            if not target_plan:
                error = "Please select a valid membership plan."
            else:
                with transaction.atomic():
                    # 1. Create User with is_active=False until OTP verified
                    new_user = User.objects.create_user(
                        username=username,
                        email=email,
                        password=password,
                        first_name=first_name,
                        last_name=last_name,
                        is_active=False
                    )

                    UserProfile.objects.create(
                        user=new_user,
                        organization=tenant,
                        role='member',
                        phone_number=full_phone
                    )

                    Membership.objects.create(
                        user=new_user,
                        organization=tenant,
                        plan=target_plan,
                        status='unpaid',
                        credit_balance=0
                    )

                    # 2. Generate and Send OTP
                    otp_obj = EmailOTP.generate_otp(new_user)
                    send_otp_email(new_user, otp_obj.otp_code, tenant.name if tenant else "Clinic")

                # 3. Store pending user ID in session and redirect to OTP screen
                request.session['pending_otp_user_id'] = new_user.id
                fallback_slug = tenant.slug if tenant else 'biohacking'
                return redirect(f"/verify-otp/?org={fallback_slug}")

    return render(request, 'memberships/register.html', {
        'tenant': tenant,
        'plans': plans,
        'selected_plan_id': selected_plan_id,
        'error': error,
    })


def verify_otp_view(request):
    """
    Validates the 6-digit OTP entered by the user.
    """
    user_id = request.session.get('pending_otp_user_id')
    tenant_slug = request.GET.get('org')
    tenant = Organization.objects.filter(slug=tenant_slug).first() if tenant_slug else None

    if not user_id:
        return redirect(f"/join/?org={tenant_slug if tenant_slug else ''}")

    user = User.objects.filter(id=user_id).first()
    if not user:
        return redirect(f"/join/?org={tenant_slug if tenant_slug else ''}")

    error = None

    if request.method == 'POST':
        entered_otp = request.POST.get('otp', '').strip()
        otp_record = EmailOTP.objects.filter(user=user, otp_code=entered_otp).order_by('-created_at').first()

        if not otp_record or not otp_record.is_valid():
            error = "Invalid or expired verification code. Please try again or request a new code."
        else:
            with transaction.atomic():
                otp_record.is_verified = True
                otp_record.save()

                user.is_active = True
                user.save()

            # Clean session and auto-login
            del request.session['pending_otp_user_id']
            login(request, user)

            fallback_slug = tenant.slug if tenant else 'biohacking'
            return redirect(f"/dashboard/member/?org={fallback_slug}")

    return render(request, 'memberships/verify_otp.html', {
        'tenant': tenant,
        'email': user.email,
        'error': error,
    })


def resend_otp_view(request):
    """
    Resends a fresh 6-digit OTP.
    """
    user_id = request.session.get('pending_otp_user_id')
    tenant_slug = request.GET.get('org')
    tenant = Organization.objects.filter(slug=tenant_slug).first() if tenant_slug else None

    if user_id:
        user = User.objects.filter(id=user_id).first()
        if user:
            otp_obj = EmailOTP.generate_otp(user)
            send_otp_email(user, otp_obj.otp_code, tenant.name if tenant else "Clinic")

    return redirect(f"/verify-otp/?org={tenant_slug if tenant_slug else ''}&resent=1")
class PublicPlansAPIView(APIView):
    """
    Public API returning active membership plans for the resolved tenant.
    """
    def get(self, request):
        if not request.tenant:
            return Response({"error": "Tenant organization not found."}, status=status.HTTP_404_NOT_FOUND)
        plans = MembershipPlan.objects.filter(organization=request.tenant).order_by('rate_monthly')
        data = [{
            "id": str(p.id),
            "tier_label": p.tier_label,
            "name": p.name,
            "standard_rate": str(p.standard_rate),
            "rate_monthly": str(p.rate_monthly),
            "credits_per_period": p.credits_per_period,
            "deposit_amount": str(p.deposit_amount),
            "inclusions": p.inclusions,
            "allotments": p.allotments
        } for p in plans]
        return Response(data)