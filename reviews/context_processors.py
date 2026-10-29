from django.conf import settings


def site(request):
    from .store import repo
    return {
        "SITE_NAME": settings.SITE_NAME,
        "SITE_URL": settings.SITE_URL or request.build_absolute_uri("/").rstrip("/"),
        "DEMO_MEMORY_MODE": repo.__class__.__name__ == "InMemoryRepository",
    }
