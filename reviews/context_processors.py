from django.conf import settings


def contact_email(request):
    """Expose the support address configured via CONTACT_EMAIL to templates."""
    return {"contact_email": settings.CONTACT_EMAIL}