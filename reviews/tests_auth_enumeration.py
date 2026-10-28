"""Login/signup must not expose whether an account already exists.

The checks cover both the visible form errors and the security log: failed
authentication may record the attempted username, but never the password.
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

PASSWORD = "correct-pass-123"
WRONG_PASSWORD = "wrong-secret-pass-456"


class LoginEnumerationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="known@example.com",
            email="known@example.com",
            password=PASSWORD,
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
        inactive = self._login("known@example.com", PASSWORD)
        unknown = self._login("unknown@example.com", PASSWORD)

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
            password=PASSWORD,
        )

    def _signup(self, email, password=PASSWORD):
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
