from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.db import transaction
from django.db.models import Sum, Count
from tenancy.emails import (
    email_org_admin_created,
    email_super_admin_audit,
    email_plan_purchased
)
from django.utils.text import slugify
from tenancy.models import Organization, UserProfile
from memberships.models import Membership, MembershipPlan, CreditLedger
from scheduling.models import Booking, Resource


def universal_login_view(request):
    """
    Single sign-on entry point with password reset handler
    and accurate role-based dashboard redirection.
    """
    error = None
    success_msg = None

    if request.method == 'POST':
        action = request.POST.get('action')

        # Forgot Password Reset Handler
        if action == 'forgot_password':
            reset_username = request.POST.get('reset_username')
            new_password = request.POST.get('new_password')
            user_to_reset = User.objects.filter(username=reset_username).first()

            if user_to_reset:
                user_to_reset.set_password(new_password)
                user_to_reset.save()
                success_msg = f"Password updated successfully for '{reset_username}'. You can now sign in."
            else:
                error = f"No account found with username '{reset_username}'."

        # Standard Login Handler
        else:
            u = request.POST.get('username')
            p = request.POST.get('password')
            user = authenticate(request, username=u, password=p)
            if user:
                login(request, user)

                # Robust profile extraction (supports both related_name='profile' and userprofile)
                profile = getattr(user, 'profile', None) or getattr(user, 'userprofile', None)
                if not profile:
                    profile, _ = UserProfile.objects.get_or_create(user=user)

                # Determine fallback tenant slug from request or profile
                req_tenant = getattr(request, 'tenant', None)
                tenant_slug = getattr(req_tenant, 'slug', None) or request.GET.get('org')

                # 1. Super Admin Routing
                if user.is_superuser or profile.role == 'super_admin':
                    return redirect('/dashboard/super-admin/')

                # 2. Org Admin Routing (Strictly redirects to Club Console)
                elif profile.role == 'org_admin':
                    org_slug = profile.organization.slug if profile.organization else (tenant_slug or 'longevity-haus')
                    return redirect(f"/dashboard/org-admin/?org={org_slug}")

                # 3. Regular Member Routing
                else:
                    org_slug = (profile.organization.slug if profile.organization else None) or tenant_slug or 'longevity-haus'
                    return redirect(f"/dashboard/member/?org={org_slug}")

            else:
                error = "Invalid username or password."

    return render(request, 'tenancy/login.html', {'error': error, 'success_msg': success_msg})
def logout_view(request):
    logout(request)
    return redirect('/login/')


# ==========================================
# PUBLIC LIVE TIERS LANDING PAGE VIEW
# ==========================================
def founders_landing_page(request):
    """
    Renders the public tiers card page when accessed directly or 
    via Super Admin 'View Live Page' button (/?org=<slug>).
    """
    org_slug = request.GET.get('org')
    
    tenant = getattr(request, 'tenant', None)
    if org_slug:
        tenant = Organization.objects.filter(slug=org_slug).first() or tenant

    # Member plan upgrade handler from the tiers card page
    if request.method == 'POST' and request.user.is_authenticated and 'claim_tier_upgrade' in request.POST:
        plan_id = request.POST.get('plan_id')
        try:
            chosen_plan = MembershipPlan.objects.get(id=plan_id, organization=tenant)
            with transaction.atomic():
                membership = Membership.objects.filter(user=request.user, organization=tenant).first()
                if membership:
                    membership.plan = chosen_plan
                    membership.status = 'active'
                    membership.credit_balance += chosen_plan.credits_per_period
                    membership.save()

                    CreditLedger.objects.create(
                        organization=tenant,
                        membership=membership,
                        amount=chosen_plan.credits_per_period,
                        transaction_type='grant',
                        reason=f"Tier upgraded to {chosen_plan.name} (+{chosen_plan.credits_per_period} credits)"
                    )
                else:
                    membership = Membership.objects.create(
                        user=request.user,
                        organization=tenant,
                        plan=chosen_plan,
                        status='active',
                        credit_balance=chosen_plan.credits_per_period
                    )
                    CreditLedger.objects.create(
                        organization=tenant,
                        membership=membership,
                        amount=chosen_plan.credits_per_period,
                        transaction_type='grant',
                        reason=f"Initial allotment for {chosen_plan.name}"
                    )
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


# ==========================================
# 1. MEMBER DASHBOARD
# ==========================================
@login_required
def member_dashboard_view(request):
    user = request.user
    tenant = getattr(request, 'tenant', None)

    # 1. Member ke saare purchased plans (Active aur Pending dono)
    all_user_memberships = Membership.objects.filter(
        user=user, 
        organization=tenant
    ).select_related('plan').order_by('-created_at')

    # Total active credit pool across all active memberships
    active_memberships = all_user_memberships.filter(status='active')
    total_active_credits = sum(m.credit_balance for m in active_memberships)
    primary_membership = active_memberships.first() or all_user_memberships.first()

    bookings = Booking.objects.filter(
        membership__user=user, 
        organization=tenant
    ).select_related('resource').order_by('-created_at')

    available_plans = MembershipPlan.objects.filter(organization=tenant).order_by('rate_monthly')
    resources = Resource.objects.filter(organization=tenant, is_active=True)

    context = {
        'membership': primary_membership,
        'all_user_memberships': all_user_memberships,
        'total_active_credits': total_active_credits,
        'bookings': bookings,
        'tenant': tenant,
        'available_plans': available_plans,
        'resources': resources,
    }
    return render(request, 'memberships/dashboard.html', context)


from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.db import transaction

from tenancy.models import Organization, UserProfile, AdminNotification
from memberships.models import Membership, MembershipPlan, CreditLedger
from scheduling.models import Booking, Resource
from tenancy.emails import (
    email_org_admin_created,
    email_plan_activated,
    email_super_admin_audit,
)

# ==========================================
# SUPER ADMIN DASHBOARD
# ==========================================
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.db import transaction
from django.db.models import Q
from django.contrib import messages

from tenancy.models import Organization, UserProfile
from memberships.models import Membership, MembershipPlan
from scheduling.models import Booking
from tenancy.emails import (
    email_org_admin_created,
    email_super_admin_audit,
)


@login_required
def super_admin_dashboard_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    if not request.user.is_superuser and profile.role != 'super_admin':
        return HttpResponseForbidden("Access Denied: Super Admin permissions required.")

    if request.method == 'POST':
        action = request.POST.get('action_type')

        # 1. Update Own Credentials
        if action == 'update_own_credentials':
            new_username = request.POST.get('new_username', '').strip()
            new_email = request.POST.get('new_email', '').strip()
            new_password = request.POST.get('new_password', '').strip()

            if new_username:
                request.user.username = new_username
            if new_email:
                request.user.email = new_email
            if new_password:
                request.user.set_password(new_password)

            request.user.save()
            login(request, request.user)
            messages.success(request, "Your credentials have been updated successfully.")
            return redirect('/dashboard/super-admin/')

        # 2. Add New Super Admin
        elif action == 'create_super_admin':
            sa_username = request.POST.get('sa_username', '').strip()
            sa_email = request.POST.get('sa_email', '').strip()
            sa_password = request.POST.get('sa_password', '').strip()

            if sa_username and sa_password:
                with transaction.atomic():
                    new_sa = User.objects.create_superuser(
                        username=sa_username,
                        email=sa_email,
                        password=sa_password
                    )
                    UserProfile.objects.create(
                        user=new_sa,
                        role='super_admin'
                    )

                if sa_email:
                    from django.core.mail import send_mail
                    from django.conf import settings
                    subject = "Master Console Access Granted | Super Admin Role"
                    message = f"""Hello {sa_username},

You have been granted full platform governance privileges as a Super Admin.

Sign-In Credentials:
- Username: {sa_username}
- Password: {sa_password}
- Console URL: http://127.0.0.1:8000/login/

Best regards,
Haus Platform Operations
"""
                    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [sa_email], fail_silently=True)

                email_super_admin_audit(
                    None, request.user,
                    "New Super Admin Created",
                    f"Super Admin '{request.user.username}' created another Super Admin: '{sa_username}' ({sa_email})."
                )
                messages.success(request, f"Super Admin '{sa_username}' created successfully.")

            return redirect('/dashboard/super-admin/#tab-super-admins')

        # 3. Delete Super Admin (With Last Admin Protection)
        elif action == 'delete_super_admin':
            target_sa_id = request.POST.get('user_id')
            
            # Count total active super admins
            total_super_admins_count = User.objects.filter(
                Q(is_superuser=True) | Q(profile__role='super_admin')
            ).distinct().count()

            # Rule: Last Super Admin cannot be deleted
            if total_super_admins_count <= 1:
                messages.error(request, "Action Denied: You cannot delete the last Super Admin of the platform.")
                return redirect('/dashboard/super-admin/#tab-super-admins')

            target_user = User.objects.filter(id=target_sa_id).first()
            if target_user:
                deleted_name = target_user.username
                deleted_email = target_user.email
                is_deleting_self = (target_user.id == request.user.id)

                target_user.delete()

                email_super_admin_audit(
                    None, request.user,
                    "Super Admin Removed",
                    f"Super Admin '{request.user.username}' removed Super Admin account '{deleted_name}' ({deleted_email})."
                )

                # Agar admin ne khud ko delete kiya aur doosre admins bache hue the, toh logout kar do
                if is_deleting_self:
                    logout(request)
                    return redirect('/login/')

                messages.success(request, f"Super Admin '{deleted_name}' has been deleted.")

            return redirect('/dashboard/super-admin/#tab-super-admins')

        # 4. Create Org Admin
        elif action == 'create_org_admin':
            admin_username = request.POST.get('admin_username', '').strip()
            admin_password = request.POST.get('admin_password', '').strip()
            admin_email = request.POST.get('admin_email', '').strip()
            org_id = request.POST.get('org_id')
            target_org = get_object_or_404(Organization, id=org_id)

            admin_user = User.objects.create_user(
                username=admin_username,
                email=admin_email,
                password=admin_password
            )
            UserProfile.objects.create(
                user=admin_user,
                organization=target_org,
                role='org_admin'
            )

            email_org_admin_created(admin_user, admin_password, target_org)
            messages.success(request, f"Club Admin '{admin_username}' provisioned.")
            return redirect('/dashboard/super-admin/#tab-admins')

        # 5. Delete Regular User or Org Admin
        elif action == 'delete_user':
            user_id = request.POST.get('user_id')
            if str(user_id) != str(request.user.id):
                u = User.objects.filter(id=user_id).first()
                if u:
                    u_name = u.username
                    u_email = u.email
                    u.delete()
                    email_super_admin_audit(None, request.user, "User Deleted", f"Deleted user '{u_name}' ({u_email}).")
                    messages.success(request, f"User '{u_name}' deleted.")
            return redirect('/dashboard/super-admin/#tab-members')
        # 5. Provision New Club / Wellness Center Organization
        elif action == 'create_org':
            org_name = request.POST.get('org_name', '').strip()
            raw_slug = request.POST.get('org_slug', '').strip()
            founding_cap = request.POST.get('founding_cap', 100)
            accent_color = request.POST.get('accent_color', '#38bdf8')

            if org_name:
                # 1. Guaranteed Unique Slug Generator
                base_slug = slugify(raw_slug or org_name)
                final_slug = base_slug
                counter = 1
                while Organization.objects.filter(slug=final_slug).exists():
                    final_slug = f"{base_slug}-{counter}"
                    counter += 1

                try:
                    cap_val = int(founding_cap)
                except (ValueError, TypeError):
                    cap_val = 100

                # 2. Database Creation inside Atomic Block
                with transaction.atomic():
                    new_org = Organization.objects.create(
                        name=org_name,
                        slug=final_slug,
                        founding_cap=cap_val,
                        branding={
                            'accent_color': accent_color,
                            'bg_color': '#07090e',
                            'card_bg': '#111620',
                            'text_color': '#ffffff',
                            'tagline': 'WELLNESS CLUB',
                            'font_h1': 'Inter',
                            'font_h2': 'Inter',
                            'font_h3': 'Inter',
                            'font_p': 'Inter',
                            'font_price': 'Inter'
                        }
                    )

                    # 3. Default starter tier plans auto-provision
                    MembershipPlan.objects.create(
                        organization=new_org,
                        tier_label="TIER 1",
                        name="The Core Pass",
                        standard_rate=199.00,
                        rate_monthly=179.00,
                        credits_per_period=8,
                        deposit_amount=100.00,
                        inclusions=["8 Biohacking Credits", "Continuous rollover"]
                    )
                    MembershipPlan.objects.create(
                        organization=new_org,
                        tier_label="TIER 2",
                        name="The Prime Pass",
                        standard_rate=299.00,
                        rate_monthly=279.00,
                        credits_per_period=16,
                        deposit_amount=100.00,
                        is_featured=True,
                        inclusions=["16 Biohacking Credits", "Priority booking window"]
                    )

                # 4. Super Admin Audit Log Email
                email_super_admin_audit(
                    new_org, request.user,
                    "New Wellness Center Provisioned",
                    f"Super Admin created new club:\n- Name: {org_name}\n- Slug: {final_slug}\n- Cap: {cap_val}\n- Accent: {accent_color}"
                )

                # Form submit hone ke baad seedha Clubs tab par redirect
                return redirect('/dashboard/super-admin/#tab-clubs')
    # Fetch All Super Admins
    super_admins = User.objects.filter(
        Q(is_superuser=True) | Q(profile__role='super_admin') | Q(profile__role='super_admin')
    ).distinct().order_by('-date_joined')
    total_super_admins = super_admins.count()

    organizations = Organization.objects.all().order_by('name')
    selected_club_slug = request.GET.get('club')

    club_stats = []
    for org in organizations:
        m_count = UserProfile.objects.filter(role='member', organization=org).count()
        club_stats.append({
            'org': org,
            'member_count': m_count,
            'is_selected': (org.slug == selected_club_slug)
        })

    all_members = UserProfile.objects.filter(role='member').select_related('user', 'organization')
    if selected_club_slug:
        all_members = all_members.filter(organization__slug=selected_club_slug)

    org_admins = UserProfile.objects.filter(role='org_admin').select_related('user', 'organization')

    return render(request, 'tenancy/super_admin.html', {
        'organizations': organizations,
        'club_stats': club_stats,
        'selected_club_slug': selected_club_slug,
        'org_admins': org_admins,
        'all_members': all_members,
        'super_admins': super_admins,
        'total_super_admins': total_super_admins,
        'total_clubs': organizations.count(),
        'total_members': UserProfile.objects.filter(role='member').count(),
        'total_bookings': Booking.objects.count(),
    })

# ORG ADMIN DASHBOARD
# ==========================================
@login_required
def org_admin_dashboard_view(request):
    """
    Organization Administrator Console.
    Controls club configuration, bookable modalities, dynamic tier plans,
    appointment fulfillment, credit ledgers, and plan payment approvals.
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    tenant = getattr(request, 'tenant', None)

    if not request.user.is_superuser and (profile.role != 'org_admin' or profile.organization != tenant):
        return HttpResponseForbidden("Access Denied: You are not authorized to manage this club.")

    if request.method == 'POST':
        action = request.POST.get('action_type')

        # ----------------------------------------------------------------------
        # 1. NOTIFICATIONS MANAGEMENT
        # ----------------------------------------------------------------------
        if action == 'mark_notification_read':
            notif_id = request.POST.get('notification_id')
            AdminNotification.objects.filter(id=notif_id, organization=tenant).update(is_read=True)
            target_tab = request.POST.get('target_tab', 'tab-overview')
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#{target_tab}")

        elif action == 'mark_all_notifications_read':
            AdminNotification.objects.filter(organization=tenant, is_read=False).update(is_read=True)
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#tab-notifications")

        # ----------------------------------------------------------------------
        # 2. PLAN PAYMENT CONFIRMATION & CREDIT ACTIVATION
        # ----------------------------------------------------------------------
        elif action == 'confirm_member_plan':
            membership_id = request.POST.get('membership_id')
            with transaction.atomic():
                mem = Membership.objects.select_for_update().filter(id=membership_id, organization=tenant).first()
                if mem and mem.status == 'pending_deposit':
                    plan = mem.plan
                    mem.status = 'active'
                    mem.credit_balance += plan.credits_per_period
                    mem.save()

                    # Audit ledger entry
                    CreditLedger.objects.create(
                        organization=tenant,
                        membership=mem,
                        amount=plan.credits_per_period,
                        transaction_type='grant',
                        reason=f"Payment verified & plan activated by Org Admin: {plan.name} (+{plan.credits_per_period} credits)"
                    )

                    # Send activation email to member
                    email_plan_purchased(mem.user, plan, tenant, mem.credit_balance)

                    # Security audit trail to Super Admin
                    email_super_admin_audit(
                        tenant, request.user,
                        "Plan Payment Approved",
                        f"Admin approved payment for '{mem.user.username}' for plan '{plan.name}'. Granted: {plan.credits_per_period} credits."
                    )
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#tab-approvals")

        # ----------------------------------------------------------------------
        # 3. APPOINTMENT ACTIONS (MARK COMPLETED & CANCEL / REFUND)
        # ----------------------------------------------------------------------
        elif action == 'complete_service':
            booking_id = request.POST.get('booking_id')
            booking = Booking.objects.filter(id=booking_id, organization=tenant).first()
            if booking and booking.status == 'pending':
                booking.status = 'completed'
                booking.save()

                email_super_admin_audit(
                    tenant, request.user,
                    "Service Fulfilled",
                    f"Admin marked service '{booking.resource.name}' as completed for member '{booking.membership.user.username}' (Booking ID #{booking.id})."
                )
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#tab-bookings")

        elif action == 'admin_cancel_booking':
            booking_id = request.POST.get('booking_id')
            with transaction.atomic():
                booking = Booking.objects.select_for_update().filter(id=booking_id, organization=tenant).first()
                if booking and booking.status != 'canceled':
                    booking.status = 'canceled'
                    booking.save()

                    # Refund credits back to member
                    membership = booking.membership
                    membership.credit_balance += booking.credits_used
                    membership.save()

                    CreditLedger.objects.create(
                        organization=tenant,
                        membership=membership,
                        amount=booking.credits_used,
                        transaction_type='refund',
                        reason=f"Admin canceled {booking.resource.name} appointment",
                        booking_reference=str(booking.id)
                    )

                    # Email member about cancellation and credit restoration
                    email_booking_canceled(booking, booking.credits_used, membership.credit_balance)

                    email_super_admin_audit(
                        tenant, request.user,
                        "Appointment Canceled & Credits Refunded",
                        f"Admin canceled booking #{booking.id} ({booking.resource.name}) for member '{membership.user.username}'. Refunded: {booking.credits_used} credits."
                    )
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#tab-bookings")

        # ----------------------------------------------------------------------
        # 4. MODALITY / RESOURCE CONFIGURATION
        # ----------------------------------------------------------------------
        elif action == 'save_service':
            service_id = request.POST.get('service_id')
            name = request.POST.get('name', '').strip()
            duration = request.POST.get('duration_minutes', 30)
            credits_cost = request.POST.get('credit_cost', 1)
            capacity = request.POST.get('capacity', 1)

            try:
                duration_int = int(duration)
                cost_int = int(credits_cost)
                capacity_int = int(capacity)
            except (ValueError, TypeError):
                duration_int, cost_int, capacity_int = 30, 1, 1

            if service_id:
                res = get_object_or_404(Resource, id=service_id, organization=tenant)
                res.name = name
                res.duration_minutes = duration_int
                res.credit_cost = cost_int
                res.capacity = capacity_int
                res.save()
                audit_msg = f"Admin updated modality '{name}' - Cost: {cost_int} cr, Duration: {duration_int}m, Capacity: {capacity_int}."
            else:
                Resource.objects.create(
                    organization=tenant,
                    name=name,
                    duration_minutes=duration_int,
                    credit_cost=cost_int,
                    capacity=capacity_int,
                    is_active=True
                )
                audit_msg = f"Admin created new modality '{name}' - Cost: {cost_int} cr, Duration: {duration_int}m, Capacity: {capacity_int}."

            email_super_admin_audit(tenant, request.user, "Service Configuration Updated", audit_msg)
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#tab-services")

        elif action == 'delete_service':
            service_id = request.POST.get('service_id')
            with transaction.atomic():
                res = Resource.objects.filter(id=service_id, organization=tenant).first()
                if res:
                    deleted_name = res.name
                    Booking.objects.filter(resource=res).delete()
                    res.delete()

                    email_super_admin_audit(
                        tenant, request.user,
                        "Service Deleted",
                        f"Admin deleted modality '{deleted_name}'. All tied bookings were purged."
                    )
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#tab-services")

        # ----------------------------------------------------------------------
        # 5. DYNAMIC MEMBERSHIP PLAN CONFIGURATION
        # ----------------------------------------------------------------------
        elif action == 'save_plan':
            plan_id = request.POST.get('plan_id')
            tier_label = request.POST.get('tier_label', 'TIER 1').strip()
            name = request.POST.get('name', '').strip()
            standard_rate = request.POST.get('standard_rate', 199.00)
            rate_monthly = request.POST.get('rate_monthly', 179.00)
            credits_cnt = request.POST.get('credits_per_period', 8)
            inclusions_raw = request.POST.get('inclusions', '')

            # Parse lines from textarea into dynamic list
            inclusions_list = [line.strip() for line in inclusions_raw.splitlines() if line.strip()]

            try:
                credits_int = int(credits_cnt)
                std_rate_float = float(standard_rate)
                rate_month_float = float(rate_monthly)
            except (ValueError, TypeError):
                credits_int, std_rate_float, rate_month_float = 8, 199.00, 179.00

            if plan_id:
                plan = get_object_or_404(MembershipPlan, id=plan_id, organization=tenant)
                plan.tier_label = tier_label
                plan.name = name
                plan.standard_rate = std_rate_float
                plan.rate_monthly = rate_month_float
                plan.credits_per_period = credits_int
                plan.inclusions = inclusions_list
                plan.save()
                audit_msg = f"Admin updated plan '{name}' ({tier_label}) - Rate: ${rate_month_float}/mo, Credits: {credits_int}."
            else:
                MembershipPlan.objects.create(
                    organization=tenant,
                    tier_label=tier_label,
                    name=name,
                    standard_rate=std_rate_float,
                    rate_monthly=rate_month_float,
                    credits_per_period=credits_int,
                    deposit_amount=100.00,
                    inclusions=inclusions_list
                )
                audit_msg = f"Admin created plan '{name}' ({tier_label}) - Rate: ${rate_month_float}/mo, Credits: {credits_int}."

            email_super_admin_audit(tenant, request.user, "Plan Configuration Updated", audit_msg)
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#tab-plans")

        elif action == 'delete_plan':
            plan_id = request.POST.get('plan_id')
            with transaction.atomic():
                plan = MembershipPlan.objects.filter(id=plan_id, organization=tenant).first()
                if plan:
                    deleted_plan_name = plan.name
                    Membership.objects.filter(plan=plan).delete()
                    plan.delete()

                    email_super_admin_audit(
                        tenant, request.user,
                        "Membership Plan Deleted",
                        f"Admin permanently deleted membership plan '{deleted_plan_name}'."
                    )
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#tab-plans")

        # ----------------------------------------------------------------------
        # 6. CLUB BRANDING & FOUNDING SLOTS CONFIGURATION
        # ----------------------------------------------------------------------
        elif action == 'update_settings':
            accent = request.POST.get('accent_color', '#60a5fa').strip()
            tagline = request.POST.get('tagline', '').strip()
            cap = request.POST.get('founding_cap')

            if not isinstance(tenant.branding, dict):
                tenant.branding = {}

            tenant.branding['accent_color'] = accent
            tenant.branding['tagline'] = tagline

            if cap:
                try:
                    tenant.founding_cap = int(cap)
                except (ValueError, TypeError):
                    pass

            tenant.save()

            email_super_admin_audit(
                tenant, request.user,
                "Club Settings & Branding Modified",
                f"Admin updated settings:\n- Tagline: '{tagline}'\n- Accent Color: {accent}\n- Slots Cap: {tenant.founding_cap}"
            )
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#tab-settings")

        # ----------------------------------------------------------------------
        # 7. MEMBER REMOVAL
        # ----------------------------------------------------------------------
        elif action == 'delete_member':
            membership_id = request.POST.get('membership_id')
            with transaction.atomic():
                membership = Membership.objects.filter(id=membership_id, organization=tenant).first()
                if membership:
                    user_to_delete = membership.user
                    deleted_username = user_to_delete.username
                    deleted_email = user_to_delete.email

                    Booking.objects.filter(membership=membership).delete()
                    CreditLedger.objects.filter(membership=membership).delete()
                    membership.delete()

                    # Delete auth user only if no other active tenant memberships exist
                    if hasattr(user_to_delete, 'profile') and user_to_delete.profile.role == 'member':
                        if not Membership.objects.filter(user=user_to_delete).exists():
                            user_to_delete.delete()

                    email_super_admin_audit(
                        tenant, request.user,
                        "Member Removed Globally",
                        f"Admin deleted membership for '{deleted_username}' ({deleted_email})."
                    )
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#tab-members")

    # --------------------------------------------------------------------------
    # QUERIES FOR DASHBOARD TEMPLATE RENDERING
    # --------------------------------------------------------------------------
    notifications = AdminNotification.objects.filter(organization=tenant)[:30]
    unread_notifications_count = AdminNotification.objects.filter(organization=tenant, is_read=False).count()

    all_memberships = Membership.objects.filter(organization=tenant).select_related('user', 'plan').prefetch_related('ledger')
    active_memberships = all_memberships.filter(status='active')
    pending_plan_memberships = all_memberships.filter(status='pending_deposit')

    bookings = Booking.objects.filter(organization=tenant).select_related('resource', 'membership__user').order_by('-start_time')
    resources = Resource.objects.filter(organization=tenant).order_by('credit_cost')
    plans = MembershipPlan.objects.filter(organization=tenant).order_by('rate_monthly')

    total_deposit_earnings = sum(m.plan.deposit_amount for m in active_memberships if m.plan)
    total_monthly_recurring = sum(m.plan.rate_monthly for m in active_memberships if m.plan)
    total_earnings = total_deposit_earnings + total_monthly_recurring

    return render(request, 'memberships/org_admin.html', {
        'tenant': tenant,
        'notifications': notifications,
        'unread_notifications_count': unread_notifications_count,
        'memberships': active_memberships,
        'pending_plan_memberships': pending_plan_memberships,
        'bookings': bookings,
        'resources': resources,
        'plans': plans,
        'total_earnings': total_earnings,
        'total_deposit_earnings': total_deposit_earnings,
        'total_monthly_recurring': total_monthly_recurring,
        'active_members_count': active_memberships.count(),
    })