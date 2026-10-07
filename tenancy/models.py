import uuid
from django.db import models
from django.contrib.auth.models import User

class Organization(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    custom_domain = models.CharField(max_length=255, blank=True, null=True, unique=True)
    branding = models.JSONField(
        default=dict,
        help_text="Branding tokens: accent_color, accent_hover, primary_color, tagline, logo_url"
    )
    founding_cap = models.PositiveIntegerField(
        default=100, 
        help_text="Total available founding slots (Admin configured)"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class UserProfile(models.Model):
    ROLE_CHOICES = (
        ('super_admin', 'Super Admin'),
        ('org_admin', 'Org Admin'),
        ('member', 'Member'),
    )
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, null=True, blank=True, related_name='users')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='member')

    def __str__(self):
        return f"{self.user.username} ({self.role}) - {self.organization.slug if self.organization else 'Global'}"
# Add in tenancy/models.py

class AdminNotification(models.Model):
    NOTIFICATION_TYPES = (
        ('plan_purchase', 'Plan Purchase Pending'),
        ('new_member', 'New Member Registered'),
        ('service_booked', 'Service Appointment Scheduled'),
        ('general', 'General Alert'),
    )

    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPES, default='general')
    target_tab = models.CharField(max_length=50, default='tab-overview', help_text="e.g. tab-approvals, tab-bookings, tab-members")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.organization.slug} - {self.title} (Read: {self.is_read})"