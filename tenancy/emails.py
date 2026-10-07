from django.core.mail import send_mail
from django.conf import settings
from tenancy.models import UserProfile, AdminNotification

# Primary platform host email recipient for all audit and platform-level events
SUPER_ADMIN_EMAIL = getattr(settings, 'PLATFORM_SUPER_ADMIN_EMAIL', 'umardaraz9056@gmail.com')


def get_org_admin_emails(org):
    """Returns a list of active email addresses for administrators of a given organization."""
    if not org:
        return []
    profiles = UserProfile.objects.filter(organization=org, role='org_admin').select_related('user')
    return [p.user.email for p in profiles if p.user and p.user.email]


# ==============================================================================
# 1. ORG ADMIN ONBOARDING & CREDENTIAL UPDATES
# ==============================================================================

def email_org_admin_created(admin_user, plain_password, org):
    """
    Sends welcome credentials to a newly provisioned Org Admin and
    dispatches an audit notification to the Super Admin.
    """
    if admin_user.email:
        subject = f"Welcome to {org.name} | Your Club Console Access"
        message = f"""Hello {admin_user.username},

You have been designated as an Organization Administrator for:
Club: {org.name} (Slug: {org.slug})

Your Sign-In Credentials:
- Username: {admin_user.username}
- Password: {plain_password}
- Console URL: http://127.0.0.1:8000/login/

Please sign in to configure your club's roster, membership tiers, and appointment approvals.

Best regards,
Haus Platform Operations
"""
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [admin_user.email], fail_silently=True)

    # Super Admin Audit Trail
    email_super_admin_audit(
        org, admin_user,
        "New Org Admin Provisioned",
        f"Admin '{admin_user.username}' ({admin_user.email}) was provisioned for club '{org.name}'."
    )


def email_org_admin_updated(admin_user, plain_password, org):
    """
    Sends a security alert to an Org Admin when their credentials or assigned club
    are updated by the Super Admin.
    """
    if admin_user.email:
        subject = f"Security Notice: Your Credentials Were Updated | {org.name}"
        pw_text = f"- New Password: {plain_password}\n" if plain_password else "- Password: (Unchanged)\n"
        message = f"""Hello {admin_user.username},

Your administrator account details for {org.name} have been updated by the Platform Administrator:

- Username: {admin_user.username}
- Notification Email: {admin_user.email}
{pw_text}- Console URL: http://127.0.0.1:8000/login/

If you did not authorize this change, please contact platform operations immediately.

Best regards,
Haus Platform Security
"""
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [admin_user.email], fail_silently=True)

    # Super Admin Audit Trail
    email_super_admin_audit(
        org, admin_user,
        "Admin Credentials Updated",
        f"Credentials updated for admin '{admin_user.username}' ({admin_user.email}). Assigned Club: {org.name}."
    )


# ==============================================================================
# 2. MEMBER REGISTRATION
# ==============================================================================

def email_new_member_joined(new_member_user, org):
    """
    Alerts the Super Admin and Club Org Admin when a new member registers,
    and logs an in-app sidebar notification for the Org Admin.
    """
    subject = f"New Member Registration: {new_member_user.username} at {org.name if org else 'Platform'}"
    message = f"""A new member has completed account registration:

Member Username: {new_member_user.username}
Member Email: {new_member_user.email}
Assigned Club: {org.name if org else 'General Platform'}

The account is initialized with 0 credits and pending founding tier selection.
"""
    recipients = [SUPER_ADMIN_EMAIL]
    if org:
        recipients.extend(get_org_admin_emails(org))

    recipients = list(set([r for r in recipients if r]))
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=True)

    # In-app sidebar notification for Org Admin
    if org:
        AdminNotification.objects.create(
            organization=org,
            title="New Member Enrolled",
            message=f"{new_member_user.username} ({new_member_user.email}) registered an account.",
            notification_type="new_member",
            target_tab="tab-members"
        )


# ==============================================================================
# 3. PLAN PURCHASES & APPROVALS
# ==============================================================================

def notify_plan_purchase_pending(user, plan, org):
    """
    Sent immediately after Stripe checkout:
    1. Member gets an acknowledgment that payment is awaiting club approval.
    2. Org Admin gets an action-required notice to confirm payment.
    3. Super Admin gets an audit log.
    4. Org Admin receives a sidebar notification with a redirect to 'Plan Approvals'.
    """
    # Member email
    if user.email:
        sub_member = f"Payment Received (Pending Approval): {plan.name} at {org.name}"
        msg_member = f"""Hi {user.username},

Thank you for purchasing the {plan.name}!

Your payment of ${plan.rate_monthly:.2f}/mo has been received and is currently PENDING confirmation by the club administration.
Once verified, your +{plan.credits_per_period} credits will be unlocked in your Member Portal.

Best regards,
The {org.name} Team
"""
        send_mail(sub_member, msg_member, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=True)

    # Org Admin email
    admin_emails = get_org_admin_emails(org)
    if admin_emails:
        sub_admin = f"Action Required: Confirm Plan Payment for {user.username} - {plan.name}"
        msg_admin = f"""Hello Admin,

Member '{user.username}' ({user.email}) submitted payment for:
- Plan: {plan.name} (${plan.rate_monthly}/mo)
- Credits to Allocate: +{plan.credits_per_period} credits
- Club: {org.name}

Open the Club Console under 'Plan Approvals' and click 'Confirm Payment & Release Credits' to activate their pass.
"""
        send_mail(sub_admin, msg_admin, settings.DEFAULT_FROM_EMAIL, admin_emails, fail_silently=True)

    # Super Admin audit log
    email_super_admin_audit(
        org, user,
        "New Plan Purchase (Pending Approval)",
        f"Member '{user.username}' submitted ${plan.rate_monthly} for plan '{plan.name}'. Awaiting Org Admin approval."
    )

    # In-app sidebar notification for Org Admin
    if org:
        AdminNotification.objects.create(
            organization=org,
            title=f"Plan Payment Pending: {plan.name}",
            message=f"{user.username} submitted payment for {plan.name}. Please confirm and release credits.",
            notification_type="plan_purchase",
            target_tab="tab-approvals"
        )


# Alias for backward compatibility
notify_admin_pending_plan_approval = notify_plan_purchase_pending


def email_plan_purchased(member_user, plan, org, remaining_credits):
    """
    Sent after the Org Admin clicks 'Confirm Payment & Release Credits':
    1. Member receives pass activation confirmation.
    2. Super Admin & Org Admin receive revenue confirmation alerts.
    """
    if member_user.email:
        sub_member = f"Payment Confirmed & Pass Activated: {plan.name} at {org.name}"
        msg_member = f"""Hi {member_user.username},

Your payment of ${plan.rate_monthly:.2f} has been verified and your pass is now active!

- Plan: {plan.name} ({plan.tier_label})
- Credits Added: +{plan.credits_per_period} credits
- Total Usable Balance: {remaining_credits} credits
- Location: {org.name}

You can now reserve your biohacking modalities.

Best regards,
The {org.name} Team
"""
        send_mail(sub_member, msg_member, settings.DEFAULT_FROM_EMAIL, [member_user.email], fail_silently=True)

    sub_admin = f"Revenue Alert: {member_user.username} activated {plan.name} (${plan.rate_monthly})"
    msg_admin = f"""Membership Plan Activated:

Club: {org.name}
Member: {member_user.username} ({member_user.email})
Plan: {plan.name} (${plan.rate_monthly}/mo)
Credits Granted: +{plan.credits_per_period}
Member Total Balance: {remaining_credits} cr
"""
    recipients = list(set([SUPER_ADMIN_EMAIL] + get_org_admin_emails(org)))
    send_mail(sub_admin, msg_admin, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=True)


# Alias for backward compatibility
email_plan_activated = email_plan_purchased


# ==============================================================================
# 4. SERVICE RESERVATION & CANCELLATION
# ==============================================================================

def email_service_booked(booking):
    """
    Sent when a member reserves a modality service:
    1. Member gets booking confirmation with deduction and remaining credits.
    2. Org Admin & Super Admin receive appointment alerts.
    3. Org Admin gets an in-app sidebar notification linking to 'Appointments'.
    """
    user = booking.membership.user
    org = booking.organization
    res = booking.resource

    # Member email
    if user.email:
        sub_member = f"Booking Confirmed: {res.name} at {org.name}"
        msg_member = f"""Hi {user.username},

Your modality appointment is confirmed:

Service: {res.name}
Time: {booking.start_time.strftime('%A, %b %d, %Y at %H:%M')}
Credits Used: {booking.credits_used} cr
Remaining Balance: {booking.membership.credit_balance} cr
Status: Service Booked (Pending Provision)

See you at {org.name}!
"""
        send_mail(sub_member, msg_member, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=True)

    # Admin alert
    sub_admin = f"Appointment Alert: {user.username} reserved {res.name}"
    msg_admin = f"""A member has reserved a modality:

Club: {org.name}
Member: {user.username} ({user.email})
Modality: {res.name}
Scheduled Time: {booking.start_time.strftime('%A, %b %d, %Y at %H:%M')}
Credits Deducted: {booking.credits_used} cr
"""
    recipients = list(set([SUPER_ADMIN_EMAIL] + get_org_admin_emails(org)))
    send_mail(sub_admin, msg_admin, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=True)

    # In-app sidebar notification for Org Admin
    if org:
        AdminNotification.objects.create(
            organization=org,
            title=f"New Appointment: {res.name}",
            message=f"{user.username} booked {res.name} on {booking.start_time.strftime('%b %d, %H:%M')}.",
            notification_type="service_booked",
            target_tab="tab-bookings"
        )


def email_booking_canceled(booking, refunded_credits, new_balance):
    """
    Sent when an appointment is canceled and credits are restored to the member's ledger.
    """
    user = booking.membership.user
    org = booking.organization

    if user.email:
        sub = f"Appointment Canceled: {booking.resource.name} at {org.name}"
        msg = f"""Hi {user.username},

Your appointment for {booking.resource.name} on {booking.start_time.strftime('%b %d, %Y at %H:%M')} has been canceled.

Refunded Credits: +{refunded_credits} cr
New Credit Balance: {new_balance} cr
"""
        send_mail(sub, msg, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=True)


# ==============================================================================
# 5. SUPER ADMIN SECURITY AUDIT LOGGING
# ==============================================================================

def email_super_admin_audit(org, actor_user, action_title, details):
    """
    Dispatches a structured security and activity audit email directly to the Super Admin.
    """
    subject = f"[Security Audit] {org.name if org else 'Platform'}: {action_title}"
    message = f"""Super Admin Security Log:

Actor: '{actor_user.username}' ({getattr(actor_user, 'email', 'N/A')})
Organization: {org.name if org else 'Platform-wide'}
Action: {action_title}
Details:
{details}
"""
    send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [SUPER_ADMIN_EMAIL], fail_silently=True)