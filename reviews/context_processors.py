"""Template context shared across every page."""
from __future__ import annotations

from django.conf import settings

from .repository import InMemoryRepository
from .store import get_repo


def site_url(request):
    """Provide the configured canonical origin, falling back to the request."""
    return {"site_url": settings.SITE_URL or f"{request.scheme}://{request.get_host()}"}


def repository_mode(request):
    """Expose whether the active repository is the volatile in-memory one."""
    backend = getattr(settings, "REPO_BACKEND", "")
    if backend == "memory":
        is_memory = True
    elif backend == "django":
        is_memory = False
    else:
        is_memory = isinstance(get_repo(), InMemoryRepository)
    return {"is_memory_repo": is_memory}


def site(request):
    """Site name, public URL and demo flag used by the base template."""
    return {
        "SITE_NAME": settings.SITE_NAME,
        "SITE_URL": settings.SITE_URL or request.build_absolute_uri("/").rstrip("/"),
        "DEMO_MEMORY_MODE": isinstance(get_repo(), InMemoryRepository),
    }
