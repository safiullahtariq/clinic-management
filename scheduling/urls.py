# from django.urls import path
# from .views import PublicResourcesAPIView, ResourceSlotsAPIView, CreateBookingAPIView,CancelBookingAPIView
# from scheduling.views import get_available_slots_api
# app_name = 'scheduling'

# urlpatterns = [
#     path('v1/public/resources', PublicResourcesAPIView.as_view(), name='api_resources'),
#     path('v1/resources/<uuid:resource_id>/slots', ResourceSlotsAPIView.as_view(), name='api_slots'),
#     path('v1/bookings', CreateBookingAPIView.as_view(), name='api_bookings'),
#     path('v1/bookings/<uuid:booking_id>/cancel', CancelBookingAPIView.as_view(), name='api_cancel_booking'),
#     path('api/available-slots/', get_available_slots_api, name='available_slots_api'),
#     path('v1/available-slots/', get_available_slots_api, name='api_available_slots_v1'),
#     path('available-slots/', get_available_slots_api, name='available_slots_direct'),
#     path('v1/bookings/', CreateBookingAPIView.as_view(), name='api_bookings_slash'),
#     path('bookings/', CreateBookingAPIView.as_view(), name='api_bookings_direct'),

#     # 2. Cancellation Endpoints
#     path('v1/bookings/<str:booking_id>/cancel', CancelBookingAPIView.as_view(), name='api_cancel_booking'),
#     path('v1/bookings/<str:booking_id>/cancel/', CancelBookingAPIView.as_view(), name='api_cancel_booking_slash'),

#     # 3. Resources & Slots Endpoints
#     path('v1/resources/<str:resource_id>/slots', ResourceSlotsAPIView.as_view(), name='api_slots'),

#     # 4. Empty Slots Engine
#     path('api/available-slots/', get_available_slots_api, name='api_available_slots'),

    
# ]
from django.urls import path
from .views import (
    PublicResourcesAPIView, 
    ResourceSlotsAPIView, 
    CreateBookingAPIView, 
    CancelBookingAPIView,
    get_available_slots_api
)

app_name = 'scheduling'

urlpatterns = [
    # API endpoints
    path('v1/bookings', CreateBookingAPIView.as_view(), name='api_bookings_noslash'),
    path('v1/bookings/', CreateBookingAPIView.as_view(), name='api_bookings'),
    path('v1/bookings/<str:booking_id>/cancel', CancelBookingAPIView.as_view(), name='api_cancel_booking_noslash'),
    path('v1/bookings/<str:booking_id>/cancel/', CancelBookingAPIView.as_view(), name='api_cancel_booking'),

    path('v1/public/resources', PublicResourcesAPIView.as_view(), name='api_resources'),
    path('v1/resources/<str:resource_id>/slots', ResourceSlotsAPIView.as_view(), name='api_slots'),

    # Real-time empty slots calculation engine
    path('api/available-slots/', get_available_slots_api, name='api_available_slots'),
    path('v1/available-slots/', get_available_slots_api, name='api_available_slots_v1'),
]