import uuid
from django.db import models
from django.contrib.auth.models import User
from tenancy.models import Organization

class MembershipPlan(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='plans')
    tier_label = models.CharField(max_length=60, default="TIER 1", help_text="e.g. TIER 1, TIER 2, TIER 4 - EXECUTIVE")
    name = models.CharField(max_length=120)  # Core Pass, Prime Pass, etc.
    standard_rate = models.DecimalField(max_digits=8, decimal_places=2, default=199.00)
    rate_monthly = models.DecimalField(max_digits=8, decimal_places=2)  # Founding rate: 179.00
    credits_per_period = models.PositiveIntegerField()
    deposit_amount = models.DecimalField(max_digits=8, decimal_places=2, default=100.00)
    is_featured = models.BooleanField(default=False)
    # Stored array of bullet inclusions, e.g. ["8 Biohacking Credits", "Continuous rollover"]
    inclusions = models.JSONField(default=list)
    allotments = models.JSONField(default=dict)
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)
    stripe_subscription_id = models.CharField(max_length=255, blank=True, null=True)
    def __str__(self):
        return f"{self.organization.slug} - {self.name}"

class Membership(models.Model):
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('pending_deposit', 'Pending Admin Approval (Paid)'),
        ('unpaid', 'Payment Required (Unpaid)'),
        ('canceled', 'Canceled'),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='memberships')
    plan = models.ForeignKey(MembershipPlan, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unpaid')
    credit_balance = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.plan.name} ({self.status})"

class CreditLedger(models.Model):
    TRANSACTION_TYPES = (
        ('grant', 'Grant'),
        ('spend', 'Spend'),
        ('refund', 'Refund'),
    )
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)
    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name='ledger')
    amount = models.IntegerField()
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES, default='spend')
    reason = models.CharField(max_length=255)
    booking_reference = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)