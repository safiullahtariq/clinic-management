from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

class PublicBrandingAPIView(APIView):
    def get(self, request):
        if not request.tenant:
            return Response({"error": "Tenant organization not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            "id": str(request.tenant.id),
            "name": request.tenant.name,
            "slug": request.tenant.slug,
            "branding": request.tenant.branding
        })