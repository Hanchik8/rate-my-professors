import logging

from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse

logger = logging.getLogger(__name__)


class HealthCheckMiddleware:
    """GET /healthz -> 200 {"status": "ok"} when the database and cache answer, else 503.

    It runs first in MIDDLEWARE so Docker/load balancer checks work over plain
    HTTP with any Host header (no ALLOWED_HOSTS check, no HTTPS redirect).
    It reveals nothing except ok/fail.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path != "/healthz":
            return self.get_response(request)
        checks = {}
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            checks["db"] = "ok"
        except Exception:  # noqa: BLE001 - any failure means unhealthy
            logger.exception("healthcheck: database failed")
            checks["db"] = "fail"
        try:
            cache.set("healthz", "1", 5)
            checks["cache"] = "ok" if cache.get("healthz") == "1" else "fail"
        except Exception:  # noqa: BLE001
            logger.exception("healthcheck: cache failed")
            checks["cache"] = "fail"
        healthy = all(v == "ok" for v in checks.values())
        response = JsonResponse({"status": "ok" if healthy else "fail", **checks}, status=200 if healthy else 503)
        response["Cache-Control"] = "no-store"
        return response
