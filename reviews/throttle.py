"""Tiny cache-backed rate limiter used to slow down abusive bursts.

Limits are fixed-window counters stored in the Django cache, so no extra
dependency is needed.  A multi-process deployment must use a shared cache
backend (Redis/Memcached) for the limit to be global; the locmem default is
fine for a single process and for tests.

Authenticated requests are keyed by username, anonymous ones by client IP, so
one user cannot exhaust another user's budget.
"""
from functools import wraps

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.utils.translation import gettext as _

_CACHE_PREFIX = "ratelimit"


def _client_ip(request):
    """Best-effort client IP, honouring the first ``X-Forwarded-For`` hop."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or "unknown"


def _subject(request, user=None):
    """Return the identity the counter is attached to."""
    if user is None:
        user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        return f"user:{user.get_username()}"
    return f"ip:{_client_ip(request)}"


def _config(action):
    """Return ``(enabled, limit, window)`` for ``action`` from settings."""
    if not getattr(settings, "RATELIMIT_ENABLE", True):
        return False, 0, 0
    limit, window = getattr(settings, "RATELIMIT", {}).get(action, (0, 0))
    return True, limit, window


def is_rate_limited(request, action, user=None):
    """Return ``True`` when ``action`` exceeded its limit for this subject."""
    enabled, limit, window = _config(action)
    if not enabled:
        return False
    key = f"{_CACHE_PREFIX}:{action}:{_subject(request, user)}"
    if cache.add(key, 1, timeout=window):
        return False
    try:
        hits = cache.incr(key)
    except ValueError:
        # Counter expired between add and incr; start a fresh window.
        cache.set(key, 1, timeout=window)
        return False
    return hits > limit


def rate_limit(action):
    """Decorator that answers ``429`` once ``action``'s budget is spent."""

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method == "POST" and is_rate_limited(request, action):
                return HttpResponse(
                    _("Слишком много запросов. Попробуйте позже."), status=429
                )
            return view(request, *args, **kwargs)

        return wrapper

    return decorator
