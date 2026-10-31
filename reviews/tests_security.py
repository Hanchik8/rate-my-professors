"""Security tests: CSRF, cookie/transport settings, response headers,
cache-control rules and static template hardening."""
import os
import re
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.cache import cache
from django.http import HttpResponse, HttpResponseNotFound
from django.test import (
    Client,
    RequestFactory,
    SimpleTestCase,
    TestCase,
    override_settings,
)
from django.urls import reverse

from config import settings as site

from .middleware import STATIC_CACHE_MAX_AGE, PrivateCacheControlMiddleware
from .repository import InMemoryRepository
from .seed import seed

PASSWORD = "pass12345"


def _review_data(course, comment):
    return {
        "course": course,
        "term": "Осень 2026",
        "overall": 4,
        "difficulty": 3,
        "would_take_again": True,
        "grade": "A",
        "comment": comment,
        "tags": ["Интересные лекции"],
    }


class CsrfFormTests(TestCase):
    def setUp(self):
        cache.clear()
        import reviews.views as views
        from reviews import store

        self.repo = InMemoryRepository()
        seed(self.repo)
        self._orig_repo = store.repo
        self._orig_view_repo = views.repo
        store.repo = self.repo
        views.repo = self.repo
        self.prof = self.repo.search("Айбек")[0]["prof"]
        self.review = self.repo.reviews_for(self.prof.id)[0]
        self.client = Client(enforce_csrf_checks=True)

    def _owned_review(self, user):
        self.repo.add_review(
            self.prof.id,
            {
                "course": "Курс для проверки",
                "term": "Осень 2025",
                "overall": 4,
                "difficulty": 3,
                "would_take_again": True,
                "grade": "A",
                "tags": [],
                "comment": "Достаточно содержательный комментарий для проверки формы.",
            },
            user=user,
        )
        return self.repo.review(self.repo.reviews_for_user(user)[0]["review"].id)

    def tearDown(self):
        import reviews.views as views
        from reviews import store

        store.repo = self._orig_repo
        views.repo = self._orig_view_repo

    def test_rendered_post_forms_include_csrf_inputs(self):
        user = User.objects.create_user(username="csrf@example.com", password="pass12345")
        self.client.force_login(user)
        owned_review = self._owned_review(user)
        urls = [
            reverse("review_new", args=[self.prof.slug]),
            reverse("add_professor"),
            reverse("review_edit", args=[owned_review.id]),
            reverse("review_delete", args=[owned_review.id]),
            reverse("professor", args=[self.prof.slug]),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'name="csrfmiddlewaretoken"')

        self.client.logout()
        for url in (reverse("login"), reverse("signup")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'name="csrfmiddlewaretoken"')

    def test_state_changing_post_endpoints_reject_missing_csrf_token(self):
        user = User.objects.create_user(username="csrf@example.com", password="pass12345")
        self.client.force_login(user)
        owned_review = self._owned_review(user)
        urls = [
            reverse("review_new", args=[self.prof.slug]),
            reverse("add_professor"),
            reverse("review_edit", args=[owned_review.id]),
            reverse("review_delete", args=[owned_review.id]),
            reverse("review_vote", args=[self.review.id]),
            reverse("review_report", args=[self.review.id]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, {}).status_code, 403)


class CsrfAnonymousEndpointTests(TestCase):
    """Anonymous auth endpoints must reject POSTs without a CSRF token."""

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def test_auth_posts_reject_missing_csrf_token(self):
        urls = [
            reverse("login"),
            reverse("signup"),
            reverse("password_reset"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, {}).status_code, 403)

    def test_password_reset_form_includes_csrf_input(self):
        response = self.client.get(reverse("password_reset"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="csrfmiddlewaretoken"')


class CookieSettingsTests(TestCase):
    def test_session_cookie_is_httponly_and_samesite(self):
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, "Lax")

    def test_csrf_cookie_is_samesite(self):
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, "Lax")
        self.assertTrue(settings.CSRF_COOKIE_HTTPONLY)

    def test_cookie_samesite_rejects_permissive_or_invalid_environment_values(self):
        with patch.dict(os.environ, {"SESSION_COOKIE_SAMESITE": "None"}):
            self.assertEqual(site._get_samesite_setting("SESSION_COOKIE_SAMESITE"), "Lax")
        with patch.dict(os.environ, {"CSRF_COOKIE_SAMESITE": "strict"}):
            self.assertEqual(site._get_samesite_setting("CSRF_COOKIE_SAMESITE"), "Strict")

    def test_secure_cookies_track_debug_flag(self):
        debug = site._security_settings(debug=True)
        self.assertFalse(debug["SESSION_COOKIE_SECURE"])
        self.assertFalse(debug["CSRF_COOKIE_SECURE"])

        production = site._security_settings(debug=False)
        self.assertTrue(production["SESSION_COOKIE_SECURE"])
        self.assertTrue(production["CSRF_COOKIE_SECURE"])

    def test_secure_cookies_can_be_overridden(self):
        self.assertTrue(
            site._security_settings(debug=True, session_secure=True)["SESSION_COOKIE_SECURE"]
        )
        self.assertFalse(
            site._security_settings(debug=False, session_secure=False)["SESSION_COOKIE_SECURE"]
        )
        self.assertTrue(
            site._security_settings(debug=True, csrf_secure=True)["CSRF_COOKIE_SECURE"]
        )
        self.assertFalse(
            site._security_settings(debug=False, csrf_secure=False)["CSRF_COOKIE_SECURE"]
        )


class TransportSecuritySettingsTests(TestCase):
    def test_https_hardening_is_off_for_debug(self):
        security = site._security_settings(debug=True)
        self.assertFalse(security["SECURE_SSL_REDIRECT"])
        self.assertEqual(security["SECURE_HSTS_SECONDS"], 0)
        self.assertFalse(security["SECURE_HSTS_INCLUDE_SUBDOMAINS"])
        self.assertFalse(security["SECURE_HSTS_PRELOAD"])

    def test_https_hardening_is_on_by_default_in_production(self):
        security = site._security_settings(debug=False)
        self.assertTrue(security["SECURE_SSL_REDIRECT"])
        self.assertGreaterEqual(security["SECURE_HSTS_SECONDS"], 31536000)
        self.assertTrue(security["SECURE_HSTS_INCLUDE_SUBDOMAINS"])
        self.assertTrue(security["SECURE_HSTS_PRELOAD"])
        self.assertTrue(security["SECURE_CONTENT_TYPE_NOSNIFF"])
        self.assertEqual(security["SECURE_PROXY_SSL_HEADER"], ("HTTP_X_FORWARDED_PROTO", "https"))

    def test_https_hardening_can_be_overridden_from_env(self):
        self.assertTrue(
            site._security_settings(debug=True, ssl_redirect=True)["SECURE_SSL_REDIRECT"]
        )
        self.assertEqual(
            site._security_settings(debug=False, hsts_seconds=0)["SECURE_HSTS_SECONDS"], 0
        )
        self.assertFalse(
            site._security_settings(
                debug=False, hsts_include_subdomains=False
            )["SECURE_HSTS_INCLUDE_SUBDOMAINS"]
        )
        self.assertFalse(
            site._security_settings(debug=False, hsts_preload=False)["SECURE_HSTS_PRELOAD"]
        )

    def test_header_settings_have_safe_values(self):
        self.assertTrue(settings.SECURE_CONTENT_TYPE_NOSNIFF)
        self.assertEqual(settings.SECURE_REFERRER_POLICY, "strict-origin-when-cross-origin")
        self.assertEqual(settings.X_FRAME_OPTIONS, "DENY")

    def test_frame_options_environment_value_cannot_disable_protection(self):
        with patch.dict(os.environ, {"X_FRAME_OPTIONS": "ALLOWALL"}):
            self.assertEqual(site._get_x_frame_options(), "DENY")
        with patch.dict(os.environ, {"X_FRAME_OPTIONS": "sameorigin"}):
            self.assertEqual(site._get_x_frame_options(), "SAMEORIGIN")

    def test_env_helpers_parse_values(self):
        with patch.dict(os.environ, {"TEST_SECURITY_BOOL": "yes", "TEST_SECURITY_INT": "42"}):
            self.assertTrue(site._get_bool_setting("TEST_SECURITY_BOOL", False))
            self.assertEqual(site._get_int_setting("TEST_SECURITY_INT", 0), 42)
        with patch.dict(os.environ, {"TEST_SECURITY_BOOL": "off", "TEST_SECURITY_INT": "bad"}):
            self.assertFalse(site._get_bool_setting("TEST_SECURITY_BOOL", True))
            self.assertEqual(site._get_int_setting("TEST_SECURITY_INT", 7), 7)


class SecurityHeaderResponseTests(TestCase):
    def setUp(self):
        self.response = self.client.get(reverse("home"))

    def test_home_page_responds(self):
        self.assertEqual(self.response.status_code, 200)

    def test_x_content_type_options_header(self):
        self.assertEqual(self.response.headers.get("X-Content-Type-Options"), "nosniff")

    def test_referrer_policy_header(self):
        self.assertEqual(
            self.response.headers.get("Referrer-Policy"),
            "strict-origin-when-cross-origin",
        )

    def test_x_frame_options_header(self):
        self.assertEqual(self.response.headers.get("X-Frame-Options"), "DENY")

    def test_csrf_cookie_flags(self):
        response = self.client.get(reverse("login"))
        cookie = response.cookies[settings.CSRF_COOKIE_NAME]
        self.assertEqual(cookie["httponly"], settings.CSRF_COOKIE_HTTPONLY)
        self.assertEqual(cookie["samesite"], settings.CSRF_COOKIE_SAMESITE)
        self.assertEqual(bool(cookie["secure"]), settings.CSRF_COOKIE_SECURE)

    def test_session_cookie_flags_when_session_is_set(self):
        request = self.client.request().wsgi_request
        middleware = SessionMiddleware(lambda request: HttpResponse())
        middleware.process_request(request)
        request.session["flag_test"] = True
        response = middleware.process_response(request, HttpResponse())
        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertEqual(bool(cookie["httponly"]), settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(cookie["samesite"], settings.SESSION_COOKIE_SAMESITE)
        self.assertEqual(bool(cookie["secure"]), settings.SESSION_COOKIE_SECURE)

    def test_permissions_policy_header(self):
        self.assertEqual(
            self.response.headers.get("Permissions-Policy"),
            "camera=(), microphone=(), geolocation=()",
        )

    def test_content_security_policy_header(self):
        policy = self.response.headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", policy)
        self.assertIn("script-src 'self'", policy)
        self.assertIn("object-src 'none'", policy)
        self.assertIn("frame-ancestors 'none'", policy)

    @override_settings(
        X_FRAME_OPTIONS="SAMEORIGIN",
        PERMISSIONS_POLICY="camera=()",
    )
    def test_headers_follow_overridden_settings(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertEqual(response.headers.get("Permissions-Policy"), "camera=()")


class CacheControlTestCase(TestCase):
    def setUp(self):
        import reviews.views as views
        from reviews import store

        self.repo = InMemoryRepository()
        seed(self.repo)
        self._orig_repo = store.repo
        self._orig_view_repo = views.repo
        store.repo = self.repo
        views.repo = self.repo
        self.prof = self.repo.search("Айбек")[0]["prof"]
        self.user = User.objects.create_user(
            username="user@example.com", email="user@example.com", password=PASSWORD
        )

    def tearDown(self):
        import reviews.views as views
        from reviews import store

        store.repo = self._orig_repo
        views.repo = self._orig_view_repo

    def login(self):
        self.client.login(username="user@example.com", password=PASSWORD)

    def assert_private(self, response):
        self.assertNotEqual(response.status_code, 404)
        cache_control = response.headers.get("Cache-Control", "")
        self.assertIn("private", cache_control)
        self.assertIn("no-store", cache_control)

    def assert_public(self, response):
        self.assertEqual(response.status_code, 200)
        cache_control = response.headers.get("Cache-Control", "")
        self.assertNotIn("no-store", cache_control)
        self.assertNotIn("private", cache_control)


class PrivatePagesCacheControlTests(CacheControlTestCase):
    def test_login_page_is_not_cacheable(self):
        self.assert_private(self.client.get(reverse("login")))

    def test_signup_page_is_not_cacheable(self):
        self.assert_private(self.client.get(reverse("signup")))

    def test_profile_page_is_not_cacheable(self):
        self.login()
        self.assert_private(self.client.get(reverse("profile")))

    def test_review_form_is_not_cacheable(self):
        self.login()
        self.assert_private(self.client.get(reverse("review_new", args=[self.prof.slug])))

    def test_review_edit_page_is_not_cacheable(self):
        self.login()
        review = self.repo.add_review(
            self.prof.id,
            _review_data("Алгоритмы", "Комментарий достаточно длинный для теста."),
            user=self.user,
        )
        self.assert_private(self.client.get(reverse("review_edit", args=[review.id])))

    def test_review_report_response_is_not_cacheable(self):
        self.login()
        review = self.repo.add_review(
            self.prof.id,
            _review_data("Алгоритмы", "Комментарий достаточно длинный для теста."),
            status="approved",
        )
        response = self.client.post(
            reverse("review_report", args=[review.id]), {"reason": "spam"}
        )
        self.assert_private(response)

    def test_security_headers_are_preserved_on_private_pages(self):
        self.login()
        response = self.client.get(reverse("profile"))
        self.assertEqual(
            response.headers.get("Permissions-Policy"),
            "camera=(), microphone=(), geolocation=()",
        )
        self.assertIn("default-src", response.headers.get("Content-Security-Policy", ""))
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(
            response.headers.get("Referrer-Policy"), "strict-origin-when-cross-origin"
        )
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")


class PublicPagesCacheControlTests(CacheControlTestCase):
    def test_home_page_has_no_no_store(self):
        response = self.client.get(reverse("home"))
        self.assert_public(response)
        self.assertIn("public", response.headers.get("Cache-Control", ""))
        self.assertIn("max-age=300", response.headers.get("Cache-Control", ""))

    def test_about_page_has_no_no_store(self):
        self.assert_public(self.client.get(reverse("about")))

    def test_school_page_has_no_no_store(self):
        school = self.repo.school(self.prof.school_id)
        self.assert_public(self.client.get(reverse("school_detail", args=[school.slug])))

    def test_professor_page_has_no_no_store(self):
        self.assert_public(self.client.get(reverse("professor", args=[self.prof.slug])))

    def test_sitemap_and_robots_responses_are_publicly_cacheable(self):
        urls = (reverse("robots_txt"), reverse("sitemap_index"), "/sitemap-home.xml")
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assert_public(response)
                self.assertIn("public", response.headers.get("Cache-Control", ""))
                self.assertIn("max-age=300", response.headers.get("Cache-Control", ""))

    def test_authenticated_home_sitemaps_and_robots_are_not_shared_cacheable(self):
        self.login()
        urls = (
            reverse("home"),
            reverse("robots_txt"),
            reverse("sitemap_index"),
            "/sitemap-home.xml",
        )
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                cache_control = response.headers.get("Cache-Control", "")
                self.assertIn("private", cache_control)
                self.assertIn("no-store", cache_control)

    def test_non_get_home_request_is_not_publicly_cacheable(self):
        response = self.client.post(reverse("home"))
        self.assertNotIn("public", response.headers.get("Cache-Control", ""))


class StaticFilesCacheControlTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _get(self, path, response=None, user=None):
        response = response or HttpResponse("body")
        middleware = PrivateCacheControlMiddleware(lambda request: response)
        request = self.factory.get(path)
        request.user = user or AnonymousUser()
        return middleware(request)

    def test_static_asset_is_publicly_cacheable(self):
        response = self._get("/static/reviews/style.css")
        cache_control = response.headers.get("Cache-Control", "")
        self.assertIn("public", cache_control)
        self.assertIn(f"max-age={STATIC_CACHE_MAX_AGE}", cache_control)

    def test_authenticated_static_asset_is_not_shared_cacheable(self):
        response = self._get("/static/reviews/style.css", user=User())
        self.assertNotIn("public", response.headers.get("Cache-Control", ""))

    def test_missing_static_asset_is_not_cached(self):
        response = self._get("/static/reviews/missing.css", response=HttpResponseNotFound())
        self.assertNotIn("public", response.headers.get("Cache-Control", ""))

    def test_non_get_static_request_is_not_cached(self):
        middleware = PrivateCacheControlMiddleware(lambda request: HttpResponse("body"))
        request = self.factory.post("/static/reviews/style.css")
        request.user = AnonymousUser()
        response = middleware(request)
        self.assertNotIn("public", response.headers.get("Cache-Control", ""))


APP_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = APP_DIR / "templates"
FORM_TAG = re.compile(r"<form\b[^>]*>", re.IGNORECASE)
FORM_METHOD = re.compile(r"method\s*=\s*[\"']?\s*(\w+)", re.IGNORECASE)
VARIABLE_EXPRESSION = re.compile(r"\{\{([^{}]*)\}\}")
SAFE_FILTER = re.compile(r"\|\s*safe\b")

# ``person_jsonld`` is serialized with ``json.dumps`` and hardened by
# escaping ``&``, ``<`` and ``>`` in ``reviews.views.professor_detail``
# (verified by ``reviews.tests_jsonld``), so ``|safe`` is safe there.
SAFE_ALLOWED_VARIABLES = {"person_jsonld"}


def _template_paths():
    return sorted(TEMPLATE_DIR.rglob("*.html")) + sorted(
        path for path in TEMPLATE_DIR.rglob("*.txt")
    )


def _app_python_paths():
    paths = [
        path for path in APP_DIR.glob("*.py")
        if not path.name.startswith("test")
    ]
    templatetags = APP_DIR / "templatetags"
    if templatetags.is_dir():
        paths.extend(templatetags.glob("*.py"))
    return sorted(paths)


def _post_form_issues(content):
    issues = []
    for match in FORM_TAG.finditer(content):
        method = FORM_METHOD.search(match.group(0))
        if not method or method.group(1).lower() != "post":
            continue
        end = content.find("</form>", match.start())
        if end == -1:
            end = len(content)
        body = content[match.start():end]
        if "{% csrf_token %}" not in body:
            issues.append(match.start())
    return issues


def _safe_filter_variables(content):
    variables = []
    for match in VARIABLE_EXPRESSION.finditer(content):
        expression = match.group(1)
        if SAFE_FILTER.search(expression):
            variables.append(expression.split("|", 1)[0].strip())
    return variables


class PostFormCsrfTests(SimpleTestCase):
    def test_every_post_form_contains_csrf_token(self):
        failures = []
        for path in _template_paths():
            content = path.read_text(encoding="utf-8")
            for offset in _post_form_issues(content):
                failures.append(
                    f"{path.relative_to(TEMPLATE_DIR)}: POST form at offset {offset}"
                )
        self.assertEqual(
            failures, [], "POST forms without {% csrf_token %}: " + ", ".join(failures)
        )


class SafeFilterTests(SimpleTestCase):
    def test_safe_filter_not_used_on_user_variables(self):
        violations = []
        for path in _template_paths():
            content = path.read_text(encoding="utf-8")
            for variable in _safe_filter_variables(content):
                if variable not in SAFE_ALLOWED_VARIABLES:
                    failures = f"{path.relative_to(TEMPLATE_DIR)}: {variable}"
                    violations.append(failures)
        self.assertEqual(
            violations, [], "|safe used on non-allowlisted variables: " + ", ".join(violations)
        )

    def test_allowed_safe_variable_is_escaped_server_side(self):
        views_source = (APP_DIR / "views.py").read_text(encoding="utf-8")
        self.assertIn('"person_jsonld"', views_source)
        for character in ('&', '<', '>'):
            self.assertIn(
                f'"{character}"', views_source,
                f"person_jsonld must escape {character!r} before |safe",
            )

    def test_mark_safe_not_used_in_app_code(self):
        offenders = [
            path.name for path in _app_python_paths()
            if "mark_safe" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])
