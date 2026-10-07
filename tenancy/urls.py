from django.urls import path
from .views import PublicBrandingAPIView

app_name = 'tenancy'

urlpatterns = [
    path('v1/public/branding', PublicBrandingAPIView.as_view(), name='api_branding'),
]