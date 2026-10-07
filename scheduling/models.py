import uuid
from django.db import models
from tenancy.models import Organization
from memberships.models import Membership
from django.contrib.auth.models import User
class Resource(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='resources')
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    duration_minutes = models.PositiveIntegerField(default=30)
    credit_cost = models.PositiveIntegerField(default=1)
    capacity = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.organization.slug} - {self.name}"

class BlackoutDate(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='blackouts')
    date = models.DateField()
    reason = models.CharField(max_length=255, default="Maintenance / Holiday")

    def __str__(self):
        return f"{self.organization.slug} blackout: {self.date}"

class Booking(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Scheduled'),
        ('waiting', 'Arrived / Waiting'),           # Naya Status
        ('in_consultation', 'In Consultation'),     # Naya Status
        ('completed', 'Completed'),
        ('canceled', 'Canceled'),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name='bookings')
    # Ensure this is CASCADE so deleting service automatically clears its slots
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name='bookings')
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    doctor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='doctor_appointments', limit_choices_to={'profile__role': 'doctor'})
    credits_used = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='confirmed')
    created_at = models.DateTimeField(auto_now_add=True)

class DoctorShift(models.Model):
    DAY_CHOICES = [
        (0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'), 
        (3, 'Thursday'), (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday')
    ]
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    doctor = models.ForeignKey(User, on_delete=models.CASCADE, limit_choices_to={'profile__role': 'doctor'})
    day_of_week = models.IntegerField(choices=DAY_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Dr. {self.doctor.username} - {self.get_day_of_week_display()}"

class ClinicalNote(models.Model):
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='clinical_note')
    doctor = models.ForeignKey(User, on_delete=models.CASCADE)
    patient_notes = models.TextField(help_text="Visible to patient", blank=True)
    private_notes = models.TextField(help_text="Internal notes", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)