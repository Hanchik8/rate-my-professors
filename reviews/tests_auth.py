"""Authentication flows and access-control checks for login/signup/logout."""
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from .repository import InMemoryRepository
from .seed import seed

PASSWORD = "pass12345"
ENUM_PASSWORD = "correct-pass-123"
WRONG_PASSWORD = "wrong-secret-pass-456"


def _valid_review(overrides=None):
    data = {
        "course": "Алгоритмы",
        "term": "Осень 2025",
        "overall": "4",
        "difficulty": "3",
        "would_take_again": "yes",
        "grade": "A",
        "tags": ["Интересные лекции"],
        "comment": "Понятные лекции и честные экзамены, рекомендую.",
    }
    if overrides:
        data.update(overrides)
    return data


class _AuthTestCase(TestCase):
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

    def tearDown(self):
        import reviews.views as views
        from reviews import store

        store.repo = self._orig_repo
        views.repo = self._orig_view_repo

    def create_user(self, email="user@example.com"):
        return User.objects.create_user(username=email, email=email, password=PASSWORD)

    def login_via_view(self, email="user@example.com", next_url=""):
        data = {"username": email, "password": PASSWORD}
        if next_url:
            data["next"] = next_url
        return self.client.post(reverse("login"), data)


class LoginFlowTests(_AuthTestCase):
    def test_login_page_renders(self):
        r = self.client.get(reverse("login"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'name="username"')
        self.assertContains(r, 'name="password"')

    def test_valid_credentials_log_user_in(self):
        self.create_user()
        r = self.login_via_view()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("home"))
        self.assertIn("_auth_user_id", self.client.session)

    def test_invalid_credentials_do_not_log_in(self):
        self.create_user()
        r = self.client.post(
            reverse("login"), {"username": "user@example.com", "password": "wrong-pass"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_redirects_to_next(self):
        self.create_user()
        target = reverse("rules")
        r = self.login_via_view(next_url=target)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, target)


class SignupFlowTests(_AuthTestCase):
    def test_signup_creates_inactive_user_pending_email_code(self):
        r = self.client.post(
            reverse("signup"),
            {
                "email": "new@example.com",
                "password1": PASSWORD,
                "password2": PASSWORD,
            },
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("signup_verify"))
        self.assertFalse(User.objects.get(username="new@example.com").is_active)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_signup_duplicate_email_rejected(self):
        self.create_user(email="dup@example.com")
        r = self.client.post(
            reverse("signup"),
            {
                "email": "dup@example.com",
                "password1": PASSWORD,
                "password2": PASSWORD,
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertIn("email", r.context["form"].errors)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_signup_password_mismatch_rejected(self):
        r = self.client.post(
            reverse("signup"),
            {
                "email": "mismatch@example.com",
                "password1": PASSWORD,
                "password2": "different-pass",
            },
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(email="mismatch@example.com").exists())

    def test_authenticated_user_is_redirected_home(self):
        user = self.create_user()
        self.client.force_login(user)
        r = self.client.get(reverse("signup"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("home"))


class LogoutFlowTests(_AuthTestCase):
    def test_logout_clears_session_and_redirects_home(self):
        user = self.create_user()
        self.client.force_login(user)
        r = self.client.post(reverse("logout"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("home"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_requires_post(self):
        user = self.create_user()
        self.client.force_login(user)
        r = self.client.get(reverse("logout"))
        self.assertEqual(r.status_code, 405)

    def test_logout_rejects_external_next_urls(self):
        user = self.create_user()
        for target in ("https://evil.com/", "//evil.com/", "javascript:alert(1)"):
            with self.subTest(target=target):
                self.client.force_login(user)
                r = self.client.post(reverse("logout"), {"next": target})
                self.assertEqual(r.status_code, 302)
                self.assertEqual(r.url, reverse("home"))

    def test_after_logout_protected_page_redirects_to_login(self):
        user = self.create_user()
        self.client.force_login(user)
        self.client.post(reverse("logout"))
        r = self.client.get(reverse("review_new", args=[self.prof.slug]))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r.url)


class OpenRedirectTests(_AuthTestCase):
    UNSAFE_TARGETS = ("//evil.com", "https://evil.com", "javascript:alert(1)")

    def setUp(self):
        super().setUp()
        self.user = self.create_user()

    def test_login_rejects_unsafe_next_and_falls_back_home(self):
        for target in self.UNSAFE_TARGETS:
            with self.subTest(target=target):
                r = self.login_via_view(next_url=target)
                self.assertEqual(r.status_code, 302)
                self.assertEqual(r.url, reverse("home"))
                self.assertNotIn("evil.com", r.url)

    def test_login_allows_relative_next(self):
        r = self.login_via_view(next_url="/path")
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, "/path")

    def test_logout_rejects_unsafe_next_and_falls_back_home(self):
        for target in self.UNSAFE_TARGETS:
            with self.subTest(target=target):
                self.client.force_login(self.user)
                r = self.client.post(reverse("logout"), {"next": target})
                self.assertEqual(r.status_code, 302)
                self.assertEqual(r.url, reverse("home"))
                self.assertNotIn("evil.com", r.url)

    def test_logout_allows_relative_next(self):
        self.client.force_login(self.user)
        r = self.client.post(reverse("logout"), {"next": "/path"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, "/path")


class AnonymousPermissionTests(_AuthTestCase):
    def test_anonymous_cannot_open_review_form(self):
        url = reverse("review_new", args=[self.prof.slug])
        r = self.client.get(url)
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r.url)
        self.assertEqual(parse_qs(urlparse(r.url).query)["next"], [url])

    def test_anonymous_cannot_submit_review(self):
        url = reverse("review_new", args=[self.prof.slug])
        before = len(self.repo.reviews_for(self.prof.id, include_pending=True))
        r = self.client.post(url, _valid_review())
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r.url)
        self.assertEqual(parse_qs(urlparse(r.url).query)["next"], [url])
        self.assertEqual(
            len(self.repo.reviews_for(self.prof.id, include_pending=True)), before
        )

    def test_login_with_next_returns_to_review_form(self):
        self.create_user()
        url = reverse("review_new", args=[self.prof.slug])
        r = self.login_via_view(next_url=url)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, url)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_login_rejects_external_next_urls(self):
        self.create_user()
        for target in ("https://evil.com/", "//evil.com/", "javascript:alert(1)"):
            with self.subTest(target=target):
                r = self.login_via_view(next_url=target)
                self.assertEqual(r.status_code, 302)
                self.assertEqual(r.url, reverse("home"))

    def test_authenticated_user_can_submit_review(self):
        user = self.create_user()
        self.client.force_login(user)
        url = reverse("review_new", args=[self.prof.slug])
        r = self.client.post(url, _valid_review())
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("professor", args=[self.prof.slug]))

    def test_anonymous_cannot_vote(self):
        review = self.repo.reviews_for(self.prof.id)[0]
        r = self.client.post(reverse("review_vote", args=[review.id]), {"vote": "up"})
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r.url)

    def test_anonymous_cannot_add_professor(self):
        r = self.client.get(reverse("add_professor"))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r.url)


@override_settings(RATELIMIT_ENABLE=False, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="reset@example.com", email="reset@example.com", password="old-password-123"
        )

    def test_sends_reset_email(self):
        response = self.client.post(reverse("password_reset"), {"email": self.user.email})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/accounts/reset/", mail.outbox[0].body)
        self.assertIn("Чтобы задать новый пароль", mail.outbox[0].body)

    def test_reset_pages_use_site_templates(self):
        urls = [
            reverse("password_reset"),
            reverse("password_reset_done"),
            reverse("password_reset_confirm", kwargs={"uidb64": "invalid", "token": "invalid"}),
            reverse("password_reset_complete"),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, "Django administration")
                self.assertNotContains(response, "/admin/")
                self.assertContains(response, 'class="top"')

    def test_reset_pages_follow_selected_language(self):
        for language in ("ru", "ky", "en"):
            with self.subTest(language=language):
                response = self.client.get(reverse("password_reset"), HTTP_ACCEPT_LANGUAGE=language)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, f'<html lang="{language}"', html=False)

    def test_unknown_email_uses_same_confirmation(self):
        response = self.client.post(reverse("password_reset"), {"email": "missing@example.com"})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(RATELIMIT_ENABLE=True, RATELIMIT={"login": (1, 60)})
    def test_reset_form_is_rate_limited_by_login_policy(self):
        self.client.post(reverse("password_reset"), {"email": "missing@example.com"})
        response = self.client.post(reverse("password_reset"), {"email": "missing@example.com"})
        self.assertEqual(response.status_code, 429)


class DuplicateSignupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="taken@example.com",
            email="taken@example.com",
            password=ENUM_PASSWORD,
        )

    def _signup(self, email, **extra):
        return self.client.post(
            reverse("signup"),
            {"email": email, "password1": ENUM_PASSWORD, "password2": ENUM_PASSWORD},
            **extra,
        )

    def test_duplicate_email_shows_login_and_password_reset_links(self):
        response = self._signup("taken@example.com")

        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        self.assertContains(response, "Этот email уже зарегистрирован.")
        self.assertContains(response, f'href="{reverse("login")}"')
        self.assertContains(response, f'href="{reverse("password_reset")}"')
        self.assertContains(response, "Войти")
        self.assertContains(response, "Забыли пароль?")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_message_is_identical_for_confirmed_and_unconfirmed_accounts(self):
        confirmed = self._signup("taken@example.com")
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        unconfirmed = self._signup("TAKEN@EXAMPLE.COM")

        self.assertEqual(confirmed.status_code, unconfirmed.status_code)
        self.assertEqual(
            list(confirmed.context["form"].errors["email"]),
            list(unconfirmed.context["form"].errors["email"]),
        )
        for response in (confirmed, unconfirmed):
            self.assertNotContains(response, "подтвержд")
            self.assertNotContains(response, "confirmed")

    def test_message_is_translated_in_en_and_ky(self):
        expected = {
            "en": "This email is already registered.",
            "ky": "Бул email мурунтан эле катталган.",
        }
        for lang, text in expected.items():
            with self.subTest(lang=lang):
                response = self._signup(
                    "taken@example.com", HTTP_ACCEPT_LANGUAGE=lang
                )
                self.assertContains(response, text)


class LoginEnumerationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="known@example.com",
            email="known@example.com",
            password=ENUM_PASSWORD,
        )

    def _login(self, username, password):
        return self.client.post(
            reverse("login"), {"username": username, "password": password}
        )

    def test_unknown_and_existing_accounts_show_the_same_error(self):
        existing = self._login("known@example.com", WRONG_PASSWORD)
        unknown = self._login("unknown@example.com", WRONG_PASSWORD)

        self.assertEqual(existing.status_code, 200)
        self.assertEqual(unknown.status_code, 200)
        self.assertEqual(
            list(existing.context["form"].non_field_errors()),
            list(unknown.context["form"].non_field_errors()),
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_inactive_account_is_not_disclosed(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        inactive = self._login("known@example.com", ENUM_PASSWORD)
        unknown = self._login("unknown@example.com", ENUM_PASSWORD)

        self.assertEqual(inactive.status_code, 200)
        self.assertEqual(
            list(inactive.context["form"].non_field_errors()),
            list(unknown.context["form"].non_field_errors()),
        )

    def test_failed_login_view_does_not_log_the_password(self):
        with self.assertLogs("security", level="WARNING") as logs:
            response = self._login("known@example.com", WRONG_PASSWORD)

        self.assertEqual(response.status_code, 200)
        output = "\n".join(logs.output)
        self.assertIn("known@example.com", output)
        self.assertNotIn(WRONG_PASSWORD, output)


class SignupEnumerationTests(TestCase):
    def setUp(self):
        User.objects.create_user(
            username="taken@example.com",
            email="taken@example.com",
            password=ENUM_PASSWORD,
        )

    def _signup(self, email, password=ENUM_PASSWORD):
        return self.client.post(
            reverse("signup"),
            {"email": email, "password1": password, "password2": password},
        )

    def test_duplicate_email_does_not_reveal_the_account(self):
        response = self._signup("taken@example.com")

        self.assertEqual(response.status_code, 200)
        self.assertIn("email", response.context["form"].errors)
        rendered = response.content.decode().lower()
        for disclosure in ("уже существует", "already exists", "колдонуучу бар"):
            with self.subTest(disclosure=disclosure):
                self.assertNotIn(disclosure, rendered)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_duplicate_check_is_case_insensitive_and_generic(self):
        response = self._signup("TAKEN@EXAMPLE.COM")

        self.assertEqual(response.status_code, 200)
        message = " ".join(response.context["form"].errors["email"]).lower()
        self.assertNotIn("уже существует", message)
        self.assertNotIn("already exists", message)
