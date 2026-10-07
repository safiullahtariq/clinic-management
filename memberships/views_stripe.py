import stripe
from django.conf import settings
from django.shortcuts import redirect, get_object_or_404, render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.contrib.auth.models import User
from django.core.mail import send_mail

from tenancy.models import Organization, UserProfile
from memberships.models import MembershipPlan, Membership, CreditLedger
from tenancy.emails import email_super_admin_audit

stripe.api_key = settings.STRIPE_SECRET_KEY


def send_plan_purchase_emails(user, plan, org):
    """Sends confirmation email to member once plan is activated."""
    if user.email:
        member_subject = f"Membership Activated: {plan.name} at {org.name}"
        member_message = f"""Hi {user.username},

Your payment has been verified and your pass is now active!

Plan: {plan.name} ({plan.tier_label})
Monthly Rate: ${plan.rate_monthly}/mo
Biohacking Credits Added: +{plan.credits_per_period} credits
Location: {org.name}

You can now reserve modalities and services directly in your Member Portal.

Best regards,
The {org.name} Team
"""
        send_mail(member_subject, member_message, settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=True)


def notify_admin_pending_plan_approval(user, plan, org):
    """Alerts club admin that a payment has been submitted and requires manual approval."""
    org_admins = UserProfile.objects.filter(organization=org, role='org_admin').select_related('user')
    admin_emails = [a.user.email for a in org_admins if a.user.email]
    
    if admin_emails:
        admin_subject = f"Action Required: New Plan Purchase by {user.username} - {plan.name}"
        admin_message = f"""Hello Admin,

A member has purchased a membership pass that requires confirmation:

Member: {user.username} ({user.email})
Plan: {plan.name} (${plan.rate_monthly}/mo)
Credits Pending: +{plan.credits_per_period} credits
Club: {org.name}

Please open the Club Console, verify the payment in 'Plan Approvals', and click 'Confirm Payment & Release Credits' to activate their credits.
"""
        send_mail(admin_subject, admin_message, settings.DEFAULT_FROM_EMAIL, admin_emails, fail_silently=True)


import stripe
from django.conf import settings
from django.shortcuts import redirect, get_object_or_404, render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.db import transaction

from tenancy.models import Organization
from memberships.models import MembershipPlan, Membership
from tenancy.emails import notify_plan_purchase_pending

stripe.api_key = settings.STRIPE_SECRET_KEY


@login_required
def create_checkout_session(request):
    if request.method != 'POST':
        return HttpResponse("Method not allowed", status=405)

    plan_id = request.POST.get('plan_id')
    tenant = getattr(request, 'tenant', None)
    org_slug = request.GET.get('org')
    if not tenant and org_slug:
        tenant = Organization.objects.filter(slug=org_slug).first()

    plan = get_object_or_404(MembershipPlan, id=plan_id, organization=tenant)
    domain_url = request.build_absolute_uri('/')[:-1]
    tenant_slug = tenant.slug if tenant else 'longevity-haus'

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            customer_email=request.user.email if request.user.email else None,
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'unit_amount': int(plan.rate_monthly * 100),
                    'product_data': {
                        'name': f"{plan.tier_label} - {plan.name}",
                        'description': f"{plan.credits_per_period} Biohacking Credits / month at {tenant.name}",
                    },
                    'recurring': {'interval': 'month'},
                },
                'quantity': 1,
            }],
            mode='subscription',
            success_url=f"{domain_url}/payment/success/?session_id={{CHECKOUT_SESSION_ID}}&org={tenant_slug}&plan_id={plan.id}",
            cancel_url=f"{domain_url}/dashboard/member/?org={tenant_slug}",
            metadata={
                'user_id': str(request.user.id),
                'tenant_id': str(tenant.id) if tenant else '',
                'plan_id': str(plan.id),
            }
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def payment_success_view(request):
    """
    Called ONLY when Stripe payment completes successfully.
    Updates the unpaid membership (or creates a new one) into 'pending_deposit',
    and sends confirmation emails to the member and org admin.
    """
    tenant = getattr(request, 'tenant', None)
    org_slug = request.GET.get('org')
    if not tenant and org_slug:
        tenant = Organization.objects.filter(slug=org_slug).first()

    plan_id = request.GET.get('plan_id')
    session_id = request.GET.get('session_id')

    if plan_id and tenant:
        try:
            plan = MembershipPlan.objects.get(id=plan_id, organization=tenant)
            with transaction.atomic():
                # Check if member already had an unpaid row for this plan
                existing_unpaid = Membership.objects.filter(
                    user=request.user,
                    organization=tenant,
                    plan=plan,
                    status='unpaid'
                ).first()

                if existing_unpaid:
                    existing_unpaid.status = 'pending_deposit'
                    existing_unpaid.save()
                    mem_obj = existing_unpaid
                else:
                    mem_obj = Membership.objects.create(
                        user=request.user,
                        organization=tenant,
                        plan=plan,
                        status='pending_deposit',
                        credit_balance=0
                    )

                # Send real-time emails to Member, Org Admin & Super Admin
                notify_plan_purchase_pending(request.user, plan, tenant)

        except MembershipPlan.DoesNotExist:
            pass

    return render(request, 'memberships/payment_success.html', {
        'tenant': tenant,
        'session_id': session_id,
    })
@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    endpoint_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', None)

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except Exception:
        return HttpResponse(status=400)

    # Webhook handling for recurring subscriptions
    if event['type'] == 'invoice.payment_succeeded':
        invoice = event['data']['object']
        subscription_id = invoice.get('subscription')
        if subscription_id:
            membership = Membership.objects.filter(stripe_subscription_id=subscription_id, status='active').first()
            if membership and membership.plan:
                with transaction.atomic():
                    plan = membership.plan
                    membership.credit_balance += plan.credits_per_period
                    membership.save()

                    CreditLedger.objects.create(
                        organization=membership.organization,
                        membership=membership,
                        amount=plan.credits_per_period,
                        transaction_type='grant',
                        reason=f"Monthly Renewal: {plan.name} (+{plan.credits_per_period} credits)"
                    )
                    send_plan_purchase_emails(membership.user, plan, membership.organization)

    return HttpResponse(status=200)