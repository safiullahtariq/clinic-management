from django.urls import path
from .views import PublicResourcesAPIView, ResourceSlotsAPIView, CreateBookingAPIView,CancelBookingAPIView

app_name = 'scheduling'

urlpatterns = [
    path('v1/public/resources', PublicResourcesAPIView.as_view(), name='api_resources'),
    path('v1/resources/<uuid:resource_id>/slots', ResourceSlotsAPIView.as_view(), name='api_slots'),
    path('v1/bookings', CreateBookingAPIView.as_view(), name='api_bookings'),
    path('v1/bookings/<uuid:booking_id>/cancel', CancelBookingAPIView.as_view(), name='api_cancel_booking'),
]