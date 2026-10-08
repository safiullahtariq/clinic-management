# from django.shortcuts import render, redirect, get_object_or_404
# from django.contrib.auth import authenticate, login, logout
# from django.contrib.auth.models import User
# from django.contrib.auth.decorators import login_required
# from django.http import HttpResponseForbidden
# from django.db import transaction
# from django.db.models import Sum, Count
# from tenancy.emails import (
#     email_org_admin_created,
#     email_super_admin_audit,
#     email_plan_purchased,
#     email_staff_account_created,
# )
# from scheduling.models import Booking, Resource
# from datetime import datetime, time
# from django.utils.text import slugify
# from tenancy.models import Organization, UserProfile
# from memberships.models import Membership, MembershipPlan, CreditLedger
# from scheduling.models import Booking, Resource
# from scheduling.models import Booking, Resource, DoctorShift, ClinicalNote
# from django.utils import timezone
# from scheduling.models import Booking, ClinicalNote
# import csv
# from xhtml2pdf import pisa
import csv
import io
from datetime import datetime, time
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponseForbidden, HttpResponse
from django.db import transaction
from django.utils import timezone
from django.template.loader import render_to_string
from xhtml2pdf import pisa

from tenancy.models import Organization, UserProfile, AdminNotification
from memberships.models import Membership, MembershipPlan, CreditLedger
from scheduling.models import Booking, Resource, DoctorShift, ClinicalNote
from tenancy.emails import (
    email_plan_purchased,
    email_super_admin_audit,
    email_staff_account_created
)
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
                elif profile.role == 'doctor':
                    return redirect(f"/dashboard/doctor/?org={profile.organization.slug}")
                elif profile.role == 'receptionist':
                    return redirect(f"/dashboard/reception/?org={profile.organization.slug}")
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

    # Tenant resolve check fallback
    org_slug = request.GET.get('org')
    if not tenant and org_slug:
        tenant = Organization.objects.filter(slug=org_slug).first()

    # 1. Member ke saare purchased plans (Active aur Pending dono)
    all_user_memberships = Membership.objects.filter(
        user=user, 
        organization=tenant
    ).select_related('plan').order_by('-created_at')

    # Total active credit pool across all active memberships
    active_memberships = all_user_memberships.filter(status='active')
    total_active_credits = sum(m.credit_balance for m in active_memberships)
    primary_membership = active_memberships.first() or all_user_memberships.first()

    # 2. Member ke Bookings (Doctor aur Clinical Notes ke sath)
    bookings = Booking.objects.filter(
        membership__user=user, 
        organization=tenant
    ).select_related('resource', 'doctor').prefetch_related('clinical_note').order_by('-start_time')

    available_plans = MembershipPlan.objects.filter(organization=tenant).order_by('rate_monthly')
    resources = Resource.objects.filter(organization=tenant, is_active=True).order_by('name')

    # 3. REAL-TIME DOCTORS FETCH (Database se active doctors)
    doctors = UserProfile.objects.filter(
        organization=tenant,
        role='doctor'
    ).select_related('user')

    # Agar tenant ke sath doctor direct link na ho toh safe fallback
    if not doctors.exists():
        doctors = UserProfile.objects.filter(role='doctor').select_related('user')

    context = {
        'membership': primary_membership,
        'all_user_memberships': all_user_memberships,
        'total_active_credits': total_active_credits,
        'bookings': bookings,
        'tenant': tenant,
        'available_plans': available_plans,
        'resources': resources,
        'doctors': doctors,  # <-- Dropdown ke liye doctors list
    }
    return render(request, 'memberships/dashboard.html', context)

# from django.shortcuts import render, redirect, get_object_or_404
# from django.contrib.auth import authenticate, login, logout
# from django.contrib.auth.models import User
# from django.contrib.auth.decorators import login_required
# from django.http import HttpResponseForbidden
# from django.db import transaction

# from tenancy.models import Organization, UserProfile, AdminNotification

# from scheduling.models import Booking, Resource
# from tenancy.emails import (
#     email_org_admin_created,
#     email_plan_activated,
#     email_super_admin_audit,
# )

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

from scheduling.models import Booking
from tenancy.emails import (
    email_org_admin_created,
    email_super_admin_audit,
)


# @login_required
# def super_admin_dashboard_view(request):
#     profile, _ = UserProfile.objects.get_or_create(user=request.user)
#     if not request.user.is_superuser and profile.role != 'super_admin':
#         return HttpResponseForbidden("Access Denied: Super Admin permissions required.")

#     if request.method == 'POST':
#         action = request.POST.get('action_type')

#         # 1. Update Own Credentials
#         if action == 'update_own_credentials':
#             new_username = request.POST.get('new_username', '').strip()
#             new_email = request.POST.get('new_email', '').strip()
#             new_password = request.POST.get('new_password', '').strip()

#             if new_username:
#                 request.user.username = new_username
#             if new_email:
#                 request.user.email = new_email
#             if new_password:
#                 request.user.set_password(new_password)

#             request.user.save()
#             login(request, request.user)
#             messages.success(request, "Your credentials have been updated successfully.")
#             return redirect('/dashboard/super-admin/')

#         # 2. Add New Super Admin
#         elif action == 'create_super_admin':
#             sa_username = request.POST.get('sa_username', '').strip()
#             sa_email = request.POST.get('sa_email', '').strip()
#             sa_password = request.POST.get('sa_password', '').strip()

#             if sa_username and sa_password:
#                 with transaction.atomic():
#                     new_sa = User.objects.create_superuser(
#                         username=sa_username,
#                         email=sa_email,
#                         password=sa_password
#                     )
#                     UserProfile.objects.create(
#                         user=new_sa,
#                         role='super_admin'
#                     )

#                 if sa_email:
#                     from django.core.mail import send_mail
#                     from django.conf import settings
#                     subject = "Master Console Access Granted | Super Admin Role"
#                     message = f"""Hello {sa_username},

# You have been granted full platform governance privileges as a Super Admin.

# Sign-In Credentials:
# - Username: {sa_username}
# - Password: {sa_password}
# - Console URL: http://127.0.0.1:8000/login/

# Best regards,
# Haus Platform Operations
# """
#                     send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [sa_email], fail_silently=True)

#                 email_super_admin_audit(
#                     None, request.user,
#                     "New Super Admin Created",
#                     f"Super Admin '{request.user.username}' created another Super Admin: '{sa_username}' ({sa_email})."
#                 )
#                 messages.success(request, f"Super Admin '{sa_username}' created successfully.")

#             return redirect('/dashboard/super-admin/#tab-super-admins')

#         # 3. Delete Super Admin (With Last Admin Protection)
#         elif action == 'delete_super_admin':
#             target_sa_id = request.POST.get('user_id')
            
#             # Count total active super admins
#             total_super_admins_count = User.objects.filter(
#                 Q(is_superuser=True) | Q(profile__role='super_admin')
#             ).distinct().count()

#             # Rule: Last Super Admin cannot be deleted
#             if total_super_admins_count <= 1:
#                 messages.error(request, "Action Denied: You cannot delete the last Super Admin of the platform.")
#                 return redirect('/dashboard/super-admin/#tab-super-admins')

#             target_user = User.objects.filter(id=target_sa_id).first()
#             if target_user:
#                 deleted_name = target_user.username
#                 deleted_email = target_user.email
#                 is_deleting_self = (target_user.id == request.user.id)

#                 target_user.delete()

#                 email_super_admin_audit(
#                     None, request.user,
#                     "Super Admin Removed",
#                     f"Super Admin '{request.user.username}' removed Super Admin account '{deleted_name}' ({deleted_email})."
#                 )

#                 # Agar admin ne khud ko delete kiya aur doosre admins bache hue the, toh logout kar do
#                 if is_deleting_self:
#                     logout(request)
#                     return redirect('/login/')

#                 messages.success(request, f"Super Admin '{deleted_name}' has been deleted.")

#             return redirect('/dashboard/super-admin/#tab-super-admins')

#         # 4. Create Org Admin
#         elif action == 'create_org_admin':
#             admin_username = request.POST.get('admin_username', '').strip()
#             admin_password = request.POST.get('admin_password', '').strip()
#             admin_email = request.POST.get('admin_email', '').strip()
#             org_id = request.POST.get('org_id')
#             target_org = get_object_or_404(Organization, id=org_id)

#             admin_user = User.objects.create_user(
#                 username=admin_username,
#                 email=admin_email,
#                 password=admin_password
#             )
#             UserProfile.objects.create(
#                 user=admin_user,
#                 organization=target_org,
#                 role='org_admin'
#             )

#             email_org_admin_created(admin_user, admin_password, target_org)
#             messages.success(request, f"Club Admin '{admin_username}' provisioned.")
#             return redirect('/dashboard/super-admin/#tab-admins')

#         # 5. Delete Regular User or Org Admin
#         elif action == 'delete_user':
#             user_id = request.POST.get('user_id')
#             if str(user_id) != str(request.user.id):
#                 u = User.objects.filter(id=user_id).first()
#                 if u:
#                     u_name = u.username
#                     u_email = u.email
#                     u.delete()
#                     email_super_admin_audit(None, request.user, "User Deleted", f"Deleted user '{u_name}' ({u_email}).")
#                     messages.success(request, f"User '{u_name}' deleted.")
#             return redirect('/dashboard/super-admin/#tab-members')
#         # 5. Provision New Club / Wellness Center Organization
#         elif action == 'create_org':
#             org_name = request.POST.get('org_name', '').strip()
#             raw_slug = request.POST.get('org_slug', '').strip()
#             founding_cap = request.POST.get('founding_cap', 100)
#             accent_color = request.POST.get('accent_color', '#38bdf8')

#             if org_name:
#                 # 1. Guaranteed Unique Slug Generator
#                 base_slug = slugify(raw_slug or org_name)
#                 final_slug = base_slug
#                 counter = 1
#                 while Organization.objects.filter(slug=final_slug).exists():
#                     final_slug = f"{base_slug}-{counter}"
#                     counter += 1

#                 try:
#                     cap_val = int(founding_cap)
#                 except (ValueError, TypeError):
#                     cap_val = 100

#                 # 2. Database Creation inside Atomic Block
#                 with transaction.atomic():
#                     new_org = Organization.objects.create(
#                         name=org_name,
#                         slug=final_slug,
#                         founding_cap=cap_val,
#                         branding={
#                             'accent_color': accent_color,
#                             'bg_color': '#07090e',
#                             'card_bg': '#111620',
#                             'text_color': '#ffffff',
#                             'tagline': 'WELLNESS CLUB',
#                             'font_h1': 'Inter',
#                             'font_h2': 'Inter',
#                             'font_h3': 'Inter',
#                             'font_p': 'Inter',
#                             'font_price': 'Inter'
#                         }
#                     )

#                     # 3. Default starter tier plans auto-provision
#                     MembershipPlan.objects.create(
#                         organization=new_org,
#                         tier_label="TIER 1",
#                         name="The Core Pass",
#                         standard_rate=199.00,
#                         rate_monthly=179.00,
#                         credits_per_period=8,
#                         deposit_amount=100.00,
#                         inclusions=["8 Biohacking Credits", "Continuous rollover"]
#                     )
#                     MembershipPlan.objects.create(
#                         organization=new_org,
#                         tier_label="TIER 2",
#                         name="The Prime Pass",
#                         standard_rate=299.00,
#                         rate_monthly=279.00,
#                         credits_per_period=16,
#                         deposit_amount=100.00,
#                         is_featured=True,
#                         inclusions=["16 Biohacking Credits", "Priority booking window"]
#                     )

#                 # 4. Super Admin Audit Log Email
#                 email_super_admin_audit(
#                     new_org, request.user,
#                     "New Wellness Center Provisioned",
#                     f"Super Admin created new club:\n- Name: {org_name}\n- Slug: {final_slug}\n- Cap: {cap_val}\n- Accent: {accent_color}"
#                 )

#                 # Form submit hone ke baad seedha Clubs tab par redirect
#                 return redirect('/dashboard/super-admin/#tab-clubs')
#     # Fetch All Super Admins
#     super_admins = User.objects.filter(
#         Q(is_superuser=True) | Q(profile__role='super_admin') | Q(profile__role='super_admin')
#     ).distinct().order_by('-date_joined')
#     total_super_admins = super_admins.count()

#     organizations = Organization.objects.all().order_by('name')
#     selected_club_slug = request.GET.get('club')

#     club_stats = []
#     for org in organizations:
#         m_count = UserProfile.objects.filter(role='member', organization=org).count()
#         club_stats.append({
#             'org': org,
#             'member_count': m_count,
#             'is_selected': (org.slug == selected_club_slug)
#         })

#     all_members = UserProfile.objects.filter(role='member').select_related('user', 'organization')
#     if selected_club_slug:
#         all_members = all_members.filter(organization__slug=selected_club_slug)

#     org_admins = UserProfile.objects.filter(role='org_admin').select_related('user', 'organization')

#     return render(request, 'tenancy/super_admin.html', {
#         'organizations': organizations,
#         'club_stats': club_stats,
#         'selected_club_slug': selected_club_slug,
#         'org_admins': org_admins,
#         'all_members': all_members,
#         'super_admins': super_admins,
#         'total_super_admins': total_super_admins,
#         'total_clubs': organizations.count(),
#         'total_members': UserProfile.objects.filter(role='member').count(),
#         'total_bookings': Booking.objects.count(),
#     })
from django.db.models import Q
from django.utils.text import slugify
from memberships.models import Membership

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

        # 6. Provision New Club / Wellness Center Organization
        elif action == 'create_org':
            org_name = request.POST.get('org_name', '').strip()
            raw_slug = request.POST.get('org_slug', '').strip()
            founding_cap = request.POST.get('founding_cap', 100)
            accent_color = request.POST.get('accent_color', '#38bdf8')

            if org_name:
                # Guaranteed Unique Slug Generator
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

                # Database Creation inside Atomic Block
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

                    # Default starter tier plans auto-provision
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

                # Super Admin Audit Log Email
                email_super_admin_audit(
                    new_org, request.user,
                    "New Wellness Center Provisioned",
                    f"Super Admin created new club:\n- Name: {org_name}\n- Slug: {final_slug}\n- Cap: {cap_val}\n- Accent: {accent_color}"
                )

                return redirect('/dashboard/super-admin/#tab-clubs')

    # ------------------ REAL-TIME DATA QUERIES & LIVE REVENUE ENGINE ------------------
    # 1. Fetch All Super Admins
    super_admins = User.objects.filter(
        Q(is_superuser=True) | Q(profile__role='super_admin')
    ).distinct().order_by('-date_joined')
    total_super_admins = super_admins.count()

    organizations = Organization.objects.all().order_by('name')
    selected_club_slug = request.GET.get('club')

    # 2. Live Calculation of Multi-Clinic Revenues & Individual Breakdown
    total_platform_revenue = 0.0
    club_stats = []

    for org in organizations:
        m_count = UserProfile.objects.filter(role='member', organization=org).count()
        b_count = Booking.objects.filter(organization=org).count()

        # Is clinic ke active members aur unki payment earnings
        org_active_mems = Membership.objects.filter(organization=org, status='active').select_related('plan')
        deposit_rev = sum(
            float(m.plan.deposit_amount) for m in org_active_mems 
            if m.plan and hasattr(m.plan, 'deposit_amount') and m.plan.deposit_amount
        )
        monthly_rev = sum(
            float(m.plan.rate_monthly) for m in org_active_mems 
            if m.plan and m.plan.rate_monthly
        )
        clinic_earnings = deposit_rev + monthly_rev

        # Global sum mein add karein
        total_platform_revenue += clinic_earnings

        club_stats.append({
            'org': org,
            'member_count': m_count,
            'booking_count': b_count,
            'monthly_recurring': monthly_rev,
            'total_earnings': clinic_earnings,
            'is_selected': (org.slug == selected_club_slug)
        })

    # Filtered Members List
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
        # LIVE REVENUE CONTEXT VARIABLES:
        'total_platform_revenue': total_platform_revenue,
        'clinics_summary': club_stats,
    })


# -------------------------------------------------------------
# 1. ORG ADMIN DASHBOARD (Finance, Total Patients & Management)
# -------------------------------------------------------------
@login_required
def org_admin_dashboard_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    tenant = getattr(request, 'tenant', None)
    org_slug = request.GET.get('org')
    if not tenant and org_slug:
        tenant = Organization.objects.filter(slug=org_slug).first()
    if not tenant and profile.organization:
        tenant = profile.organization

    if not request.user.is_superuser and (profile.role != 'org_admin' or profile.organization != tenant):
        return HttpResponseForbidden("Access Denied: You are not authorized to manage this clinic.")

    # ------------------ POST ACTIONS ------------------
    if request.method == 'POST':
        action = request.POST.get('action_type')

        # Notifications
        if action == 'mark_notification_read':
            notif_id = request.POST.get('notification_id')
            AdminNotification.objects.filter(id=notif_id, organization=tenant).update(is_read=True)
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#tab-overview")
        elif action == 'mark_all_notifications_read':
            AdminNotification.objects.filter(organization=tenant, is_read=False).update(is_read=True)
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#tab-notifications")

        # 1. PAYMENT APPROVAL & CREDIT ACTIVATION (Strict Org Admin Duty)[cite: 1, 2]
        elif action == 'confirm_member_plan':
            membership_id = request.POST.get('membership_id')
            with transaction.atomic():
                mem = Membership.objects.select_for_update().filter(id=membership_id, organization=tenant).first()
                if mem and mem.status in ['pending_deposit', 'unpaid']:
                    plan = mem.plan
                    mem.status = 'active'
                    mem.credit_balance += plan.credits_per_period
                    mem.save()

                    CreditLedger.objects.create(
                        organization=tenant,
                        membership=mem,
                        amount=plan.credits_per_period,
                        transaction_type='grant',
                        reason=f"Payment verified & plan activated by Clinic Admin: {plan.name} (+{plan.credits_per_period} cr)"
                    )
                    try:
                        email_plan_purchased(mem.user, plan, tenant, mem.credit_balance)
                    except Exception:
                        pass
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#tab-approvals")

        # 2. STAFF MANAGEMENT (Create, Update, Delete)
        elif action == 'create_staff':
            staff_role = request.POST.get('staff_role')
            staff_username = request.POST.get('username', '').strip()
            staff_email = request.POST.get('email', '').strip()
            staff_password = request.POST.get('password', '').strip()

            if staff_username and staff_password and staff_role in ['doctor', 'receptionist']:
                if not User.objects.filter(username=staff_username).exists():
                    with transaction.atomic():
                        new_staff = User.objects.create_user(username=staff_username, email=staff_email, password=staff_password)
                        UserProfile.objects.create(user=new_staff, organization=tenant, role=staff_role)
                        if staff_email:
                            try:
                                email_staff_account_created(new_staff, staff_password, staff_role, tenant)
                            except Exception:
                                pass
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#tab-staff")

        elif action == 'delete_staff':
            user_id = request.POST.get('user_id')
            target_user = User.objects.filter(id=user_id, profile__organization=tenant).first()
            if target_user:
                with transaction.atomic():
                    Booking.objects.filter(doctor=target_user).update(doctor=None)
                    target_user.delete()
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#tab-staff")

        # 3. DOCTOR SHIFTS
        elif action == 'save_doctor_shift':
            doctor_id = request.POST.get('doctor_id')
            day_of_week = request.POST.get('day_of_week')
            start_time_raw = request.POST.get('start_time', '').strip()
            end_time_raw = request.POST.get('end_time', '').strip()

            if doctor_id and (day_of_week is not None and str(day_of_week) != '') and start_time_raw and end_time_raw:
                doc_user = User.objects.filter(id=doctor_id).first()
                if doc_user:
                    DoctorShift.objects.create(
                        organization=tenant,
                        doctor=doc_user,
                        day_of_week=int(day_of_week),
                        start_time=start_time_raw,
                        end_time=end_time_raw,
                        is_active=True
                    )
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#tab-shifts")

        elif action == 'delete_doctor_shift':
            shift_id = request.POST.get('shift_id')
            DoctorShift.objects.filter(id=shift_id, organization=tenant).delete()
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#tab-shifts")

        # 4. MODALITIES & PLANS[cite: 3]
        elif action == 'save_service':
            name = request.POST.get('name', '').strip()
            duration = int(request.POST.get('duration_minutes', 30))
            credits_cost = int(request.POST.get('credit_cost', 1))
            Resource.objects.create(organization=tenant, name=name, duration_minutes=duration, credit_cost=credits_cost)
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#tab-services")

        elif action == 'delete_service':
            service_id = request.POST.get('service_id')
            Resource.objects.filter(id=service_id, organization=tenant).delete()
            return redirect(f"/dashboard/org-admin/?org={tenant.slug}#tab-services")

    # ------------------ EXPORT ENGINE ------------------
    export_action = request.GET.get('export')
    if export_action == 'patients_csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="Patients_{tenant.slug}.csv"'
        writer = csv.writer(response)
        writer.writerow(['Patient ID', 'Username', 'Email', 'Plan', 'Credit Balance', 'Status', 'Date Joined'])
        for pm in Membership.objects.filter(organization=tenant).select_related('user', 'plan'):
            writer.writerow([pm.user.id, pm.user.username, pm.user.email, pm.plan.name if pm.plan else 'N/A', pm.credit_balance, pm.status, pm.user.date_joined.strftime('%Y-%m-%d')])
        return response

    elif export_action == 'clinic_pdf':
        clinic_bookings = Booking.objects.filter(organization=tenant)
        active_mems = Membership.objects.filter(organization=tenant, status='active')
        pdf_context = {
            'tenant': tenant,
            'generated_at': timezone.now(),
            'total_patients': active_mems.count(),
            'total_bookings': clinic_bookings.count(),
            'total_revenue': sum(m.plan.rate_monthly for m in active_mems if m.plan),
            'doc_stats': [{
                'doctor_name': d.user.username,
                'email': d.user.email,
                'total_assigned': clinic_bookings.filter(doctor=d.user).count(),
                'completed': clinic_bookings.filter(doctor=d.user, status='completed').count(),
            } for d in UserProfile.objects.filter(organization=tenant, role='doctor').select_related('user')],
        }
        html = render_to_string('tenancy/clinic_performance_pdf.html', pdf_context)
        result = io.BytesIO()
        pdf = pisa.pisaDocument(io.BytesIO(html.encode("UTF-8")), result)
        if not pdf.err:
            response = HttpResponse(result.getvalue(), content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="Report_{tenant.slug}.pdf"'
            return response

    # Queries
    notifications = AdminNotification.objects.filter(organization=tenant)[:20]
    unread_notifications_count = AdminNotification.objects.filter(organization=tenant, is_read=False).count()
    all_memberships = Membership.objects.filter(organization=tenant).select_related('user', 'plan')
    active_memberships = all_memberships.filter(status='active')
    pending_plan_memberships = all_memberships.filter(status__in=['pending_deposit', 'unpaid'])
    
    total_deposit_earnings = sum(m.plan.deposit_amount for m in active_memberships if m.plan)
    total_monthly_recurring = sum(m.plan.rate_monthly for m in active_memberships if m.plan)
    total_earnings = total_deposit_earnings + total_monthly_recurring

    resources = Resource.objects.filter(organization=tenant)
    plans = MembershipPlan.objects.filter(organization=tenant)
    doctors = UserProfile.objects.filter(organization=tenant, role='doctor').select_related('user')
    receptionists = UserProfile.objects.filter(organization=tenant, role='receptionist').select_related('user')
    shifts = DoctorShift.objects.filter(organization=tenant).select_related('doctor').order_by('day_of_week')

    return render(request, 'memberships/org_admin.html', {
        'tenant': tenant,
        'notifications': notifications,
        'unread_notifications_count': unread_notifications_count,
        'memberships': active_memberships,
        'all_patients': all_memberships, # Full Patient Directory for Admin
        'pending_plan_memberships': pending_plan_memberships,
        'resources': resources,
        'plans': plans,
        'doctors': doctors,
        'receptionists': receptionists,
        'shifts': shifts,
        'total_earnings': total_earnings,
        'total_monthly_recurring': total_monthly_recurring,
        'active_members_count': active_memberships.count(),
    })


# -------------------------------------------------------------
# 2. RECEPTIONIST DASHBOARD (Patient Care, Queue & Full CRUD)
# -------------------------------------------------------------
def generate_patient_pdf_report(patient_user, tenant):
    bookings = Booking.objects.filter(membership__user=patient_user, organization=tenant).select_related('resource', 'doctor').prefetch_related('clinical_note').order_by('-start_time')
    mem = Membership.objects.filter(user=patient_user, organization=tenant).first()
    context = {'tenant': tenant, 'patient': patient_user, 'membership': mem, 'bookings': bookings, 'generated_at': timezone.now()}
    html = render_to_string('tenancy/patient_record_pdf.html', context)
    result = io.BytesIO()
    pdf = pisa.pisaDocument(io.BytesIO(html.encode("UTF-8")), result)
    return result.getvalue() if not pdf.err else None

@login_required
def reception_dashboard_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    tenant = getattr(request, 'tenant', None)
    org_slug = request.GET.get('org')
    if not tenant and org_slug:
        tenant = Organization.objects.filter(slug=org_slug).first()
    if not tenant and profile.organization:
        tenant = profile.organization

    if not request.user.is_superuser and profile.role not in ['receptionist', 'org_admin']:
        return HttpResponseForbidden("Access Denied: Receptionist console permissions required.")

    today = timezone.localdate()

    # ------------------ POST ACTIONS ------------------
    if request.method == 'POST':
        action = request.POST.get('action_type')

        # 1. RECEPTIONIST STATUS ENGINE (Arrived -> Doctor -> Check Out / Cancel)
        if action == 'update_booking_status':
            booking_id = request.POST.get('booking_id')
            new_status = request.POST.get('status')
            
            with transaction.atomic():
                booking = Booking.objects.select_for_update().filter(id=booking_id, organization=tenant).first()
                if booking and new_status in ['pending', 'waiting', 'in_consultation', 'completed', 'canceled']:
                    # Agar status cancel ho raha hai aur pehle cancel nahi tha -> Refund credits
                    if new_status == 'canceled' and booking.status != 'canceled':
                        mem = booking.membership
                        mem.credit_balance += booking.credits_used
                        mem.save()
                        CreditLedger.objects.create(
                            organization=tenant,
                            membership=mem,
                            amount=booking.credits_used,
                            transaction_type='refund',
                            reason=f"Receptionist canceled {booking.resource.name} appointment",
                            booking_reference=str(booking.id)
                        )
                    booking.status = new_status
                    booking.save()
            return redirect(f"/dashboard/reception/?org={tenant.slug}#tab-roster")
        # 2. Patient CRUD (Walk-in creation)
        elif action == 'create_patient':
            username = request.POST.get('username', '').strip()
            email = request.POST.get('email', '').strip()
            password = request.POST.get('password', '').strip()
            plan_id = request.POST.get('plan_id')

            if username and not User.objects.filter(username=username).exists():
                with transaction.atomic():
                    new_patient = User.objects.create_user(username=username, email=email, password=password or 'Pass@1234')
                    UserProfile.objects.create(user=new_patient, organization=tenant, role='member')
                    plan = MembershipPlan.objects.filter(id=plan_id, organization=tenant).first() or MembershipPlan.objects.filter(organization=tenant).first()
                    if plan:
                        Membership.objects.create(user=new_patient, organization=tenant, plan=plan, status='active', credit_balance=plan.credits_per_period)
            return redirect(f"/dashboard/reception/?org={tenant.slug if tenant else ''}#tab-patients")

        elif action == 'update_patient':
            user_id = request.POST.get('user_id')
            new_email = request.POST.get('email', '').strip()
            new_pass = request.POST.get('new_password', '').strip()
            target_user = User.objects.filter(id=user_id, profile__organization=tenant).first()
            if target_user:
                if new_email: target_user.email = new_email
                if new_pass: target_user.set_password(new_pass)
                target_user.save()
            return redirect(f"/dashboard/reception/?org={tenant.slug if tenant else ''}#tab-patients")

        elif action == 'delete_patient':
            user_id = request.POST.get('user_id')
            target_user = User.objects.filter(id=user_id, profile__organization=tenant).first()
            if target_user:
                with transaction.atomic():
                    Booking.objects.filter(membership__user=target_user).delete()
                    Membership.objects.filter(user=target_user, organization=tenant).delete()
                    target_user.delete()
            return redirect(f"/dashboard/reception/?org={tenant.slug if tenant else ''}#tab-patients")

    # ------------------ PDF EXPORT ------------------
    if request.GET.get('export_pdf'):
        p_id = request.GET.get('export_pdf')
        target_patient = get_object_or_404(User, id=p_id, profile__organization=tenant)
        pdf_bytes = generate_patient_pdf_report(target_patient, tenant)
        if pdf_bytes:
            res = HttpResponse(pdf_bytes, content_type='application/pdf')
            res['Content-Disposition'] = f'attachment; filename="Record_{target_patient.username}.pdf"'
            return res

    # ------------------ LIVE QUERIES ------------------
    # 1. Fetch ALL Bookings for this Clinic (Not just today, so future & past are never lost)
    all_bookings = Booking.objects.filter(
        organization=tenant
    ).select_related('membership__user', 'doctor', 'resource').order_by('-start_time')

    # 2. Patients & Staff
    all_patients = UserProfile.objects.filter(
        organization=tenant, role='member'
    ).select_related('user').order_by('-user__date_joined')

    doctors = UserProfile.objects.filter(
        organization=tenant, role='doctor'
    ).select_related('user')

    resources = Resource.objects.filter(organization=tenant, is_active=True)
    plans = MembershipPlan.objects.filter(organization=tenant)

    # Counters
    waiting_count = all_bookings.filter(status='waiting').count()
    in_consult_count = all_bookings.filter(status='in_consultation').count()
    completed_count = all_bookings.filter(status='completed').count()
    pending_count = all_bookings.filter(status='pending').count()

    return render(request, 'tenancy/reception_dashboard.html', {
        'tenant': tenant,
        'all_bookings': all_bookings,
        'all_patients': all_patients,
        'doctors': doctors,
        'resources': resources,
        'plans': plans,
        'today_date': today,
        'waiting_count': waiting_count,
        'in_consult_count': in_consult_count,
        'completed_count': completed_count,
        'pending_count': pending_count,
    })
@login_required
def doctor_dashboard_view(request):
    """
    Doctor Dedicated Operations Console:
    - Active Queue: All patients currently Waiting in Lobby or In-Consultation (Regardless of date)
    - Direct Doctor Actions: Check Out (Complete) OR Cancel & Refund
    - Upcoming Roster & Completed Consultation History
    """
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    tenant = getattr(request, 'tenant', None)
    
    org_slug = request.GET.get('org')
    if not tenant and org_slug:
        tenant = Organization.objects.filter(slug=org_slug).first()
    if not tenant and profile.organization:
        tenant = profile.organization

    if not request.user.is_superuser and profile.role != 'doctor':
        return HttpResponseForbidden("Access Denied: Doctor credentials required.")

    today = timezone.localdate()

    # ------------------ POST ACTIONS (2 DOCTOR ACTIONS) ------------------
    if request.method == 'POST':
        action = request.POST.get('action_type')

        # 1. STATUS UPDATE: Check Out / Complete OR Cancel & Refund
        if action == 'update_appointment_status':
            booking_id = request.POST.get('booking_id')
            new_status = request.POST.get('status')

            with transaction.atomic():
                booking = Booking.objects.select_for_update().filter(
                    id=booking_id, 
                    doctor=request.user, 
                    organization=tenant
                ).first()

                if booking and new_status in ['in_consultation', 'completed', 'canceled']:
                    # Action 1: Cancel & Auto-Refund to Patient
                    if new_status == 'canceled' and booking.status != 'canceled':
                        mem = booking.membership
                        mem.credit_balance += booking.credits_used
                        mem.save()
                        CreditLedger.objects.create(
                            organization=tenant,
                            membership=mem,
                            amount=booking.credits_used,
                            transaction_type='refund',
                            reason=f"Doctor Dr. {request.user.username} canceled visit for {booking.resource.name}",
                            booking_reference=str(booking.id)
                        )
                    # Action 2: Check Out / Complete
                    booking.status = new_status
                    booking.save()

            return redirect(f"/dashboard/doctor/?org={tenant.slug if tenant else ''}#tab-queue")

        # 2. SAVE PRESCRIPTION & OPTIONAL DIRECT CHECKOUT
        elif action == 'save_clinical_note':
            booking_id = request.POST.get('booking_id')
            patient_notes = request.POST.get('patient_notes', '').strip()
            private_notes = request.POST.get('private_notes', '').strip()
            mark_complete = request.POST.get('mark_complete') == 'true'

            with transaction.atomic():
                booking = Booking.objects.select_for_update().filter(
                    id=booking_id, 
                    doctor=request.user, 
                    organization=tenant
                ).first()

                if booking:
                    note, _ = ClinicalNote.objects.get_or_create(
                        booking=booking, 
                        defaults={'doctor': request.user}
                    )
                    note.patient_notes = patient_notes
                    note.private_notes = private_notes
                    note.doctor = request.user
                    note.save()

                    if mark_complete:
                        booking.status = 'completed'
                        booking.save()

            return redirect(f"/dashboard/doctor/?org={tenant.slug if tenant else ''}#tab-queue")

    # ------------------ LIVE QUERIES (NO DATE-LOCKOUT) ------------------
    all_doctor_bookings = Booking.objects.filter(
        doctor=request.user,
        organization=tenant
    ).select_related('membership__user', 'resource').prefetch_related('clinical_note').order_by('start_time')

    # 1. ACTIVE LIVE QUEUE:
    # Jo patient Lobby mein waiting hain YA In-Consultation hain (Chahe appointment date koi bhi ho)
    # Plus aaj ke pending scheduled appointments
    active_queue = [
        b for b in all_doctor_bookings 
        if b.status in ['waiting', 'in_consultation'] or (b.start_time.date() == today and b.status == 'pending')
    ]

    # 2. UPCOMING SCHEDULE (Sirf future ke jo abhi tak clinic nahi pohnche / pending hain)
    upcoming_bookings = [
        b for b in all_doctor_bookings 
        if b.status == 'pending' and b.start_time.date() > today
    ]

    # 3. FULFILLED & COMPLETED HISTORY
    completed_bookings = [
        b for b in all_doctor_bookings 
        if b.status == 'completed'
    ]

    # 4. PATIENT DIRECTORY
    assigned_patients = []
    seen_patient_ids = set()
    for b in all_doctor_bookings:
        p_user = b.membership.user
        if p_user.id not in seen_patient_ids:
            seen_patient_ids.add(p_user.id)
            patient_history = all_doctor_bookings.filter(membership__user=p_user)
            assigned_patients.append({
                'user': p_user,
                'total_visits': patient_history.count(),
                'completed_visits': patient_history.filter(status='completed').count(),
                'last_visit': patient_history.last().start_time if patient_history.exists() else None
            })

    # Counters for Top Cards (REAL-TIME ACROSS ALL SESSIONS)
    waiting_count = sum(1 for b in all_doctor_bookings if b.status == 'waiting')
    in_consult_count = sum(1 for b in all_doctor_bookings if b.status == 'in_consultation')
    completed_count = len(completed_bookings)
    total_active_count = len(active_queue)

    return render(request, 'tenancy/doctor_dashboard.html', {
        'tenant': tenant,
        'active_queue': active_queue,
        'upcoming_bookings': upcoming_bookings,
        'completed_bookings': completed_bookings,
        'assigned_patients': assigned_patients,
        'total_patients_count': len(assigned_patients),
        'waiting_count': waiting_count,
        'in_consult_count': in_consult_count,
        'completed_count': completed_count,
        'total_active_count': total_active_count,
        'today_date': today,
    })
@login_required
def dynamic_portal_redirect(request):
    """
    Redirects any logged in user directly to their respective role dashboard.
    """
    user = request.user
    if user.is_superuser:
        return redirect('/dashboard/super-admin/')

    profile = getattr(user, 'profile', None) or getattr(user, 'userprofile', None)
    tenant_slug = profile.organization.slug if profile and profile.organization else 'biohacking'

    if profile:
        if profile.role == 'org_admin':
            return redirect(f"/dashboard/org-admin/?org={tenant_slug}")
        elif profile.role == 'doctor':
            return redirect(f"/dashboard/doctor/?org={tenant_slug}")
        elif profile.role == 'receptionist':
            return redirect(f"/dashboard/reception/?org={tenant_slug}")

    return redirect(f"/dashboard/member/?org={tenant_slug}")