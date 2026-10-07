import re
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib.auth import login
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from tenancy.models import UserProfile, Organization
from tenancy.emails import email_new_member_joined, notify_plan_purchase_pending
from .models import MembershipPlan, Membership, CreditLedger


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


import re
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib.auth import login
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from tenancy.models import UserProfile, Organization
from tenancy.emails import email_new_member_joined, notify_plan_purchase_pending
from .models import MembershipPlan, Membership, CreditLedger


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
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not re.match(r'^[a-zA-Z0-9_]{3,}$', username):
            error = "Username must be at least 3 characters (letters, numbers, underscore)."
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
            target_plan = MembershipPlan.objects.filter(id=plan_id, organization=tenant).first() or plans.first()
            if not target_plan:
                error = "Please select a valid membership plan."
            else:
                with transaction.atomic():
                    new_user = User.objects.create_user(username=username, email=email, password=password)
                    UserProfile.objects.create(user=new_user, organization=tenant, role='member')

                    # IMPORTANT: Status is 'unpaid' because payment has NOT happened yet.
                    Membership.objects.create(
                        user=new_user,
                        organization=tenant,
                        plan=target_plan,
                        status='unpaid',
                        credit_balance=0
                    )

                    email_new_member_joined(new_user, tenant)

                # Log the user in directly and take them to dashboard or payment
                login(request, new_user)
                return redirect(f"/dashboard/member/?org={tenant.slug if tenant else 'longevity-haus'}")

    return render(request, 'memberships/register.html', {
        'tenant': tenant,
        'plans': plans,
        'selected_plan_id': selected_plan_id,
        'error': error,
    })
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