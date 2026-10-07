import uuid
from django.db import models
from tenancy.models import Organization
from memberships.models import Membership

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
        ('confirmed', 'Confirmed'),
        ('canceled', 'Canceled')
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name='bookings')
    # Ensure this is CASCADE so deleting service automatically clears its slots
    resource = models.ForeignKey(Resource, on_delete=models.CASCADE, related_name='bookings')
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    credits_used = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='confirmed')
    created_at = models.DateTimeField(auto_now_add=True)