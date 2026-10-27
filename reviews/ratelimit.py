"""Simple POST-only rate limiting on top of the Django cache.

Usage:
    @ratelimit("login")          # rate comes from settings.RATELIMITS["login"], e.g. "10/m"
    def my_view(request): ...

* Only POST requests are counted. GET (opening a page) is never limited.
* The counter key is the client IP (see client_ip below), so one abuser
  cannot lock other people out of their accounts.
* Over the limit the view is not called and the user gets HTTP 429 with a
  Retry-After header.
* With REDIS_URL all gunicorn workers share counters; without it each process
  counts separately (limits are then per process).
"""
import functools
import hashlib
import ipaddress
import time

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import render

PERIODS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_rate(rate):
    """'10/m' -> (10, 60)."""
    count, period = rate.split("/")
    return int(count), PERIODS[period.strip().lower()[0]]


def _normalize_ip(value):
    try:
        ip = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.version == 6:
        # one person usually owns a whole /64, count it as one client
        return str(ipaddress.ip_network(f"{ip}/64", strict=False).network_address) + "/64"
    return str(ip)


def client_ip(request):
    """The real client IP.

    TRUSTED_PROXY_COUNT=0: the TCP peer (REMOTE_ADDR); X-Forwarded-For is ignored
    because anyone can send it.
    TRUSTED_PROXY_COUNT=N: every trusted proxy appends the address it saw to
    X-Forwarded-For, so the client is the N-th entry from the right. Entries
    further left were written by the client itself and are not trusted.
    """
    remote = _normalize_ip(request.META.get("REMOTE_ADDR", "")) or "unknown"
    count = getattr(settings, "TRUSTED_PROXY_COUNT", 0)
    if count <= 0:
        return remote
    forwarded = [p for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()]
    if not forwarded:
        return remote
    candidate = forwarded[-count] if len(forwarded) >= count else forwarded[0]
    return _normalize_ip(candidate) or remote


def is_limited(scope, request, rate=None):
    """Count this request and return seconds to wait if the limit is exceeded, else 0."""
    if not getattr(settings, "RATELIMIT_ENABLED", True):
        return 0
    limit, period = parse_rate(rate or settings.RATELIMITS[scope])
    window = int(time.time() // period)
    ident = hashlib.sha256(client_ip(request).encode()).hexdigest()[:24]
    key = f"rl:{scope}:{ident}:{window}"
    # add() creates the counter only if missing; incr() is atomic in Redis/locmem
    cache.add(key, 0, timeout=period + 5)
    try:
        current = cache.incr(key)
    except ValueError:  # key expired between add and incr
        cache.set(key, 1, timeout=period + 5)
        current = 1
    if current > limit:
        return period - int(time.time() % period) or 1
    return 0


def too_many_requests(request, retry_after):
    response = render(request, "429.html", {"retry_after": retry_after}, status=429)
    response["Retry-After"] = str(retry_after)
    return response


def ratelimit(scope):
    def decorator(view):
        @functools.wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method == "POST":
                retry_after = is_limited(scope, request)
                if retry_after:
                    return too_many_requests(request, retry_after)
            return view(request, *args, **kwargs)
        return wrapped
    return decorator
