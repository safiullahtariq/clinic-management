import stripe
from django.conf import settings
from django.shortcuts import redirect, get_object_or_404, render
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.core.mail import send_mail

from tenancy.models import Organization, UserProfile
from memberships.models import MembershipPlan, Membership, CreditLedger

stripe.api_key = settings.STRIPE_SECRET_KEY


def send_plan_purchase_emails(user, plan, org):
    """Sends confirmation email to member once plan is activated."""
    if user.email:
        member_subject = f"Membership Activated: {plan.name} at {org.name}"
        member_message = f"""Hi {user.username},

Your payment has been verified and your membership is now active!

Plan: {plan.name} ({plan.tier_label})
Monthly Rate: ${plan.rate_monthly}/mo
Clinical Credits Added: +{plan.credits_per_period} credits
Clinic: {org.name}

Your credits are now available in your Patient Portal for appointment bookings.

Best regards,
The {org.name} Team
"""
        send_mail(
            member_subject,
            member_message,
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=True
        )


def fulfill_membership_activation(user, plan, org, subscription_id=None, reference_note="Stripe Checkout", charged_deposit=False):
    """
    Automates the Admin Approval:
    - Sets membership status to 'active'
    - Adds plan credits directly to balance
    - Creates an immutable CreditLedger grant record
    - Logs the one-time $100 deposit if collected
    """
    with transaction.atomic():
        membership = Membership.objects.select_for_update().filter(
            user=user,
            organization=org,
            plan=plan
        ).first()

        deposit_text = " (includes $100 initiation deposit)" if charged_deposit else ""

        if not membership:
            membership = Membership.objects.create(
                user=user,
                organization=org,
                plan=plan,
                status='active',
                credit_balance=plan.credits_per_period,
                stripe_subscription_id=subscription_id or ''
            )
            CreditLedger.objects.create(
                organization=org,
                membership=membership,
                amount=plan.credits_per_period,
                transaction_type='grant',
                reason=f"Initial purchase via {reference_note}{deposit_text}: {plan.name} (+{plan.credits_per_period} credits)"
            )
            send_plan_purchase_emails(user, plan, org)

        elif membership.status != 'active':
            membership.status = 'active'
            membership.credit_balance += plan.credits_per_period
            if subscription_id:
                membership.stripe_subscription_id = subscription_id
            membership.save()

            CreditLedger.objects.create(
                organization=org,
                membership=membership,
                amount=plan.credits_per_period,
                transaction_type='grant',
                reason=f"Auto-activated on {reference_note}{deposit_text}: {plan.name} (+{plan.credits_per_period} credits)"
            )
            send_plan_purchase_emails(user, plan, org)

        elif subscription_id and not membership.stripe_subscription_id:
            membership.stripe_subscription_id = subscription_id
            membership.save()

    return membership
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
    tenant_slug = tenant.slug if tenant else 'biohacking'

    # Check if patient has already paid the one-time initiation deposit
    # If they already had an active or previously active membership in this clinic, waive the deposit.
    has_prior_deposit = Membership.objects.filter(
        user=request.user,
        organization=tenant
    ).exclude(status='unpaid').exists()

    deposit_amount = getattr(plan, 'deposit_amount', 100.0) or 100.0

    # 1. Base Recurring Monthly Line Item
    line_items = [{
        'price_data': {
            'currency': 'usd',
            'unit_amount': int(plan.rate_monthly * 100),
            'product_data': {
                'name': f"{plan.tier_label} - {plan.name}",
                'description': f"{plan.credits_per_period} Clinical Credits / month at {tenant.name}",
            },
            'recurring': {'interval': 'month'},
        },
        'quantity': 1,
    }]

    # 2. First-time Purchase: Add the $100 One-Time Deposit Line Item
    if not has_prior_deposit and deposit_amount > 0:
        line_items.append({
            'price_data': {
                'currency': 'usd',
                'unit_amount': int(deposit_amount * 100),  # $100.00
                'product_data': {
                    'name': 'One-Time Initiation & Founding Deposit',
                    'description': f'One-time onboarding fee for {tenant.name} (applies to first purchase only)',
                },
            },
            'quantity': 1,
        })

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            customer_email=request.user.email if request.user.email else None,
            line_items=line_items,
            mode='subscription',
            success_url=f"{domain_url}/payment/success/?session_id={{CHECKOUT_SESSION_ID}}&org={tenant_slug}&plan_id={plan.id}",
            cancel_url=f"{domain_url}/dashboard/member/?org={tenant_slug}",
            metadata={
                'user_id': str(request.user.id),
                'tenant_id': str(tenant.id) if tenant else '',
                'plan_id': str(plan.id),
                'charged_deposit': 'true' if not has_prior_deposit else 'false',
            }
        )
        return redirect(checkout_session.url, code=303)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
@login_required
def payment_success_view(request):
    tenant = getattr(request, 'tenant', None)
    org_slug = request.GET.get('org')
    if not tenant and org_slug:
        tenant = Organization.objects.filter(slug=org_slug).first()

    plan_id = request.GET.get('plan_id')
    session_id = request.GET.get('session_id')

    if plan_id and tenant:
        try:
            plan = MembershipPlan.objects.get(id=plan_id, organization=tenant)
            subscription_id = None
            charged_deposit = False

            if session_id:
                try:
                    stripe_session = stripe.checkout.Session.retrieve(session_id)
                    subscription_id = stripe_session.get('subscription')
                    charged_deposit = stripe_session.get('metadata', {}).get('charged_deposit') == 'true'
                except Exception:
                    subscription_id = None

            fulfill_membership_activation(
                user=request.user,
                plan=plan,
                org=tenant,
                subscription_id=subscription_id,
                reference_note="Stripe Checkout",
                charged_deposit=charged_deposit
            )

        except MembershipPlan.DoesNotExist:
            pass

    return render(request, 'memberships/payment_success.html', {
        'tenant': tenant,
        'session_id': session_id,
    })

@csrf_exempt
def stripe_webhook(request):
    """
    Background Webhook Handler:
    - checkout.session.completed: Guarantees activation if user closed browser before redirect
    - invoice.payment_succeeded: Allocates monthly renewal credits on recurring billing
    """
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE')
    endpoint_secret = getattr(settings, 'STRIPE_WEBHOOK_SECRET', None)

    try:
        if endpoint_secret:
            event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
        else:
            import json
            event = stripe.Event.construct_from(json.loads(payload), stripe.api_key)
    except Exception:
        return HttpResponse(status=400)

    # 1. First-time Checkout Completion (Safety fallback)
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        metadata = session.get('metadata', {})
        user_id = metadata.get('user_id')
        plan_id = metadata.get('plan_id')
        tenant_id = metadata.get('tenant_id')
        subscription_id = session.get('subscription')

        if user_id and plan_id and tenant_id:
            try:
                from django.contrib.auth.models import User
                target_user = User.objects.filter(id=user_id).first()
                target_plan = MembershipPlan.objects.filter(id=plan_id).first()
                target_tenant = Organization.objects.filter(id=tenant_id).first()

                if target_user and target_plan and target_tenant:
                    fulfill_membership_activation(
                        user=target_user,
                        plan=target_plan,
                        org=target_tenant,
                        subscription_id=subscription_id,
                        reference_note="Stripe Webhook (checkout.session.completed)"
                    )
            except Exception:
                pass

    # 2. Recurring Monthly Subscription Renewal
    elif event['type'] == 'invoice.payment_succeeded':
        invoice = event['data']['object']
        subscription_id = invoice.get('subscription')
        billing_reason = invoice.get('billing_reason')

        # Run recurring grants only for subscription cycles, not the initial checkout
        if subscription_id and billing_reason == 'subscription_cycle':
            membership = Membership.objects.filter(
                stripe_subscription_id=subscription_id,
                status='active'
            ).first()

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