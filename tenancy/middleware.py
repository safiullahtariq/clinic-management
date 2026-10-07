from django.utils.deprecation import MiddlewareMixin
from .models import Organization

class TenantResolutionMiddleware(MiddlewareMixin):
    def process_request(self, request):
        # 1. Check query parameter: ?org=longevity-haus
        org_slug = request.GET.get('org')

        # 2. Check subdomain: {slug}.domain.com
        if not org_slug:
            host_header = request.get_host().split(':')[0]
            parts = host_header.split('.')
            if len(parts) > 2:
                org_slug = parts[0]

        # 3. Default fallback
        if not org_slug:
            org_slug = 'longevity-haus'

        try:
            request.tenant = Organization.objects.get(slug=org_slug, is_active=True)
        except Organization.DoesNotExist:
            request.tenant = None