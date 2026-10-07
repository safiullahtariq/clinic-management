from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from tenancy.models import Organization, UserProfile
from memberships.models import MembershipPlan, Membership, CreditLedger
from scheduling.models import Resource

class Command(BaseCommand):
    help = "Seeds exact reference tiers, modalities, and admins"

    def handle(self, *args, **options):
        org, _ = Organization.objects.get_or_create(
            slug="longevity-haus",
            defaults={
                "name": "Longevity Haus",
                "founding_cap": 100,
                "branding": {
                    "tagline": "DR. PHILLIPS, FLORIDA",
                    "accent_color": "#60a5fa",
                    "accent_hover": "#3b82f6",
                    "primary_color": "#06090e"
                }
            }
        )

        # 4 Tiers matching reference screenshot exactly
        plans_data = [
            {
                "tier_label": "TIER 1",
                "name": "The Core Pass",
                "standard_rate": 199.00,
                "rate_monthly": 179.00,
                "credits": 8,
                "is_featured": False,
                "inclusions": [
                    "8 Biohacking Credits",
                    "Continuous rollover — credits never expire while active"
                ],
                "allotments": {"bonus": "Founding bonus: 1 IM vitamin shot; 10% retail discount"}
            },
            {
                "tier_label": "TIER 2",
                "name": "The Prime Pass",
                "standard_rate": 349.00,
                "rate_monthly": 279.00,
                "credits": 16,
                "is_featured": False,
                "inclusions": [
                    "16 Biohacking Credits",
                    "1 Gold IV Drip per month",
                    "Continuous rollover — credits never expire while active"
                ],
                "allotments": {"bonus": "Founding bonus: 2 IM shots; 15% IV & peptide discount"}
            },
            {
                "tier_label": "TIER 3",
                "name": "The Elite Longevity Pass",
                "standard_rate": 549.00,
                "rate_monthly": 439.00,
                "credits": 24,
                "is_featured": True,  # Highlighted card with gradient button
                "inclusions": [
                    "24 Biohacking Credits",
                    "2 Gold IV Drips per month",
                    "10% off ongoing Peptides & NAD+",
                    "Continuous rollover — credits never expire while active"
                ],
                "allotments": {"bonus": "Founding bonus includes consultation"}
            },
            {
                "tier_label": "TIER 4 — EXECUTIVE",
                "name": "Haus Executive Pass",
                "standard_rate": 999.00,
                "rate_monthly": 799.00,
                "credits": 40,
                "is_featured": False,
                "inclusions": [
                    "40 Biohacking Credits — fully shareable with family, guests, or athletes (no restrictions)",
                    "4 Gold IV Drips per month",
                    "15% off ongoing Peptides & NAD+",
                    "Continuous rollover — credits never expire while active"
                ],
                "allotments": {"bonus": "15% off peptides & NAD+"}
            },
        ]

        for p in plans_data:
            MembershipPlan.objects.update_or_create(
                organization=org, name=p["name"],
                defaults={
                    "tier_label": p["tier_label"],
                    "standard_rate": p["standard_rate"],
                    "rate_monthly": p["rate_monthly"],
                    "credits_per_period": p["credits"],
                    "is_featured": p["is_featured"],
                    "inclusions": p["inclusions"],
                    "allotments": p["allotments"],
                    "deposit_amount": 100.00
                }
            )

        # Modalities
        modalities = [
            ("Whole-Body Cryotherapy", 30, 1, 1),
            ("Compression Therapy", 30, 1, 1),
            ("Infrared Sauna", 30, 1, 1),
            ("Red Light Bed", 30, 1, 1),
            ("HBOT Solo", 60, 3, 1),
            ("HBOT Shared", 60, 5, 2),
        ]
        for name, dur, cost, cap in modalities:
            Resource.objects.update_or_create(
                organization=org, name=name,
                defaults={"duration_minutes": dur, "credit_cost": cost, "capacity": cap}
            )

        self.stdout.write(self.style.SUCCESS("Database seeded with exact reference cards!"))