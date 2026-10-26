"""Application-specific HTTP middleware."""
from django.conf import settings


class PermissionsPolicyMiddleware:
    """Add the configured Permissions-Policy header to every response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers["Permissions-Policy"] = settings.PERMISSIONS_POLICY
        return response
