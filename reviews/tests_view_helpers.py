"""Focused tests for the shared helpers used by the HTTP views."""
from types import SimpleNamespace

from django.conf import settings
from django import forms
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse
from django.test import override_settings

from .views import (
    SafeLogoutView,
    ThrottledLoginView,
    _auth_success_url,
    _is_author,
    _is_valid_post,
    _requested_next_url,
    _review_form_context,
)


class _SampleForm(forms.Form):
    name = forms.CharField()


class IsAuthorTests(SimpleTestCase):
    def test_matching_ids_are_compared_as_strings(self):
        review = SimpleNamespace(author_id=7)
        self.assertTrue(_is_author(review, SimpleNamespace(id="7")))

    def test_different_ids_are_not_the_author(self):
        review = SimpleNamespace(author_id=7)
        self.assertFalse(_is_author(review, SimpleNamespace(id=8)))

    def test_missing_author_is_never_the_author(self):
        review = SimpleNamespace(author_id=None)
        self.assertFalse(_is_author(review, SimpleNamespace(id=None)))
        self.assertFalse(_is_author(review, SimpleNamespace(id=7)))


class IsValidPostTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_get_request_is_not_a_valid_post(self):
        request = self.factory.get("/")
        self.assertFalse(_is_valid_post(request, _SampleForm()))

    def test_valid_post_is_accepted(self):
        request = self.factory.post("/", {"name": "ok"})
        self.assertTrue(_is_valid_post(request, _SampleForm(request.POST)))

    def test_invalid_post_is_rejected(self):
        request = self.factory.post("/", {})
        self.assertFalse(_is_valid_post(request, _SampleForm(request.POST)))


class RequestedNextUrlTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_post_next_takes_precedence_over_get_next(self):
        request = self.factory.post("/?next=/from-get", {"next": "/from-post"})

        self.assertEqual(_requested_next_url(request), "/from-post")

    def test_safe_get_next_is_used_when_post_next_is_missing(self):
        request = self.factory.get("/?next=/from-get")

        self.assertEqual(_requested_next_url(request), "/from-get")

    def test_external_next_is_rejected(self):
        request = self.factory.get("/?next=https://evil.example/")

        self.assertIsNone(_requested_next_url(request))


class AuthSuccessUrlTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(LOGIN_REDIRECT_URL="/after-login/")
    def test_login_uses_safe_next_or_login_default(self):
        view = ThrottledLoginView()
        view.request = self.factory.get("/?next=/requested/")
        self.assertEqual(view.get_success_url(), "/requested/")
        view.request = self.factory.get("/?next=https://evil.example/")
        self.assertEqual(view.get_success_url(), "/after-login/")

    @override_settings(LOGOUT_REDIRECT_URL="/after-logout/")
    def test_logout_uses_its_configured_default(self):
        view = SafeLogoutView()
        view.request = self.factory.get("/")
        self.assertEqual(view.get_success_url(), "/after-logout/")

    @override_settings(LOGIN_REDIRECT_URL="/fallback/")
    def test_helper_resolves_the_configured_default(self):
        request = self.factory.get("/")
        self.assertEqual(_auth_success_url(request, settings.LOGIN_REDIRECT_URL), "/fallback/")


class ReviewFormContextTests(SimpleTestCase):
    def setUp(self):
        self.prof = SimpleNamespace(slug="prof")
        self.form = _SampleForm()

    def test_new_review_context_includes_account_urls(self):
        context = _review_form_context(self.prof, self.form)

        self.assertEqual(context["url"], reverse("rules"))
        self.assertEqual(context["login_url"], reverse("login"))
        self.assertEqual(context["signup_url"], reverse("signup"))
        self.assertNotIn("editing", context)

    def test_edit_review_context_marks_editing_and_omits_account_urls(self):
        context = _review_form_context(self.prof, self.form, editing=True)

        self.assertEqual(context["url"], reverse("rules"))
        self.assertTrue(context["editing"])
        self.assertNotIn("login_url", context)
        self.assertNotIn("signup_url", context)
