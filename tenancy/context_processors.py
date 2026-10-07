from memberships.models import Membership

def founding_slots_context(request):
    tenant = getattr(request, 'tenant', None)
    if not tenant:
        return {}

    total_cap = getattr(tenant, 'founding_cap', 100)
    # Jitne members ne active membership claim ki hai
    claimed_count = Membership.objects.filter(organization=tenant, status='active').count()
    remaining = max(0, total_cap - claimed_count)
    
    progress = 0
    if total_cap > 0:
        progress = min(100, int((claimed_count / total_cap) * 100))

    return {
        'total_founding_slots': total_cap,
        'claimed_founding_slots': claimed_count,
        'remaining_founding_slots': remaining,
        'slots_progress_percent': progress,
        'is_slots_full': remaining <= 0,
    }
# tenancy/context_processors.py

def user_portal_context(request):
    """
    Resolves the exact dashboard URL and label for the authenticated user,
    preventing any role mismatch in base templates.
    """
    portal_url = None
    portal_label = "My Portal"
    user_role = "anonymous"

    if request.user.is_authenticated:
        tenant_slug = getattr(getattr(request, 'tenant', None), 'slug', 'longevity-haus')

        # 1. Super Admin
        if request.user.is_superuser:
            user_role = "super_admin"
            portal_url = "/dashboard/super-admin/"
            portal_label = "Master Console"

        else:
            # Check user role via profile (supports both related_name='profile' and userprofile)
            profile = getattr(request.user, 'profile', None) or getattr(request.user, 'userprofile', None)
            role = getattr(profile, 'role', 'member') if profile else 'member'
            
            # Org Admin priority check
            if role == 'org_admin':
                user_role = "org_admin"
                org_slug = profile.organization.slug if (profile and profile.organization) else tenant_slug
                portal_url = f"/dashboard/org-admin/?org={org_slug}"
                portal_label = "Club Console"
            else:
                user_role = "member"
                portal_url = f"/dashboard/member/?org={tenant_slug}"
                portal_label = "My Portal"

    return {
        'portal_url': portal_url,
        'portal_label': portal_label,
        'portal_user_role': user_role,
    }