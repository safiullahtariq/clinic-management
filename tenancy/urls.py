from django.urls import path
from .views import PublicBrandingAPIView
from tenancy.views_dashboards import doctor_dashboard_view,reception_dashboard_view,dynamic_portal_redirect
app_name = 'tenancy'

urlpatterns = [
    path('v1/public/branding', PublicBrandingAPIView.as_view(), name='api_branding'),
    path('dashboard/doctor/', doctor_dashboard_view, name='doctor_dashboard'),
    path('dashboard/reception/', reception_dashboard_view, name='reception_dashboard'),
    path('portal/', dynamic_portal_redirect, name='dynamic_portal'),
]