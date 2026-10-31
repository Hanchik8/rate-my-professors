"""Application-specific HTTP middleware."""
from django.conf import settings
from django.http import JsonResponse
from django.http import QueryDict
from django.utils import translation
from django.utils.cache import patch_cache_control

STATIC_CACHE_MAX_AGE = 3600


class QueryLanguageMiddleware:
    """Honor supported ``?language=`` values and persist the selection."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        selected = request.GET.get("language")
        supported = {code for code, _ in settings.LANGUAGES}
        if selected in supported:
            translation.activate(selected)
            request.LANGUAGE_CODE = selected
        query = request.GET.copy()
        query.pop("language", None)
        request.alternate_query_string = query.urlencode()
        response = self.get_response(request)
        if selected in supported:
            response.set_cookie(
                settings.LANGUAGE_COOKIE_NAME, selected,
                max_age=settings.LANGUAGE_COOKIE_AGE,
                path=settings.LANGUAGE_COOKIE_PATH,
                domain=settings.LANGUAGE_COOKIE_DOMAIN,
                secure=settings.LANGUAGE_COOKIE_SECURE,
                httponly=settings.LANGUAGE_COOKIE_HTTPONLY,
                samesite=settings.LANGUAGE_COOKIE_SAMESITE,
            )
        return response


class PermissionsPolicyMiddleware:
    """Add the configured Permissions-Policy header to every response."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers["Permissions-Policy"] = settings.PERMISSIONS_POLICY
        return response


# URL names of pages that render or collect user-specific data. Responses for
# these views must never be stored by shared or browser caches.
PRIVATE_CACHE_URL_NAMES = frozenset({
    "profile",
    "review_new",
    "review_edit",
    "review_report",
    "login",
    "signup",
})

PUBLIC_CACHE_URL_NAMES = frozenset({
    "home",
    "robots_txt",
    "sitemap_index",
    "django.contrib.sitemaps.views.sitemap",
})


class PrivateCacheControlMiddleware:
    """Send ``Cache-Control: private, no-store`` on user-specific pages.

    Public pages (home, school/professor detail, about, static) are left
    untouched. Only the Cache-Control header is patched; other security
    headers (CSP, Permissions-Policy, ...) are preserved. The resolver match
    is read after the view ran, so it is available even for redirects and
    error responses produced by matched views.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        match = request.resolver_match
        if match is not None and match.url_name in PRIVATE_CACHE_URL_NAMES:
            patch_cache_control(response, private=True, no_store=True)
        elif (
            request.path.startswith(settings.STATIC_URL)
            and request.method == "GET"
            and response.status_code == 200
            and not request.user.is_authenticated
        ):
            patch_cache_control(response, public=True, max_age=STATIC_CACHE_MAX_AGE)
        elif (
            match is not None
            and match.url_name in PUBLIC_CACHE_URL_NAMES
            and request.method == "GET"
        ):
            if request.user.is_authenticated:
                patch_cache_control(response, private=True, no_store=True)
            elif response.status_code == 200:
                patch_cache_control(response, public=True, max_age=300)
        return response


class HealthCheckMiddleware:
    """Answer GET /healthz with 200 {"status": "ok"} before any other middleware.

    It runs first in MIDDLEWARE so Docker / load balancer liveness checks work
    over plain HTTP with any Host header (no ALLOWED_HOSTS check, no HTTPS
    redirect). Like the ``healthz`` view it never touches the database; the
    database-backed readiness check stays at /health/.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path != "/healthz":
            return self.get_response(request)
        response = JsonResponse({"status": "ok"})
        response["Cache-Control"] = "no-store"
        return response
