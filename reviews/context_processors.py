"""Template context shared across every page."""
from __future__ import annotations

from django.conf import settings

from .repository import InMemoryRepository
from .store import get_repo


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
