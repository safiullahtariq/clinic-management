from django.urls import path
from .views import founders_landing_page, register_view, PublicPlansAPIView
from .views_stripe import create_checkout_session, payment_success_view, stripe_webhook

app_name = 'memberships'

urlpatterns = [
    path('', founders_landing_page, name='founders_landing'),
    path('join/', register_view, name='register'),
    path('v1/public/plans', PublicPlansAPIView.as_view(), name='api_plans'),
    path('payment/checkout/', create_checkout_session, name='stripe_checkout'),
    path('payment/success/', payment_success_view, name='payment_success'),
    path('payment/webhook/', stripe_webhook, name='stripe_webhook'),
]