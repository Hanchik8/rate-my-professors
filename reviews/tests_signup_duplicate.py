"""Duplicate-email signup shows actionable links without account disclosure."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

PASSWORD = "correct-pass-123"


class DuplicateSignupTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="taken@example.com",
            email="taken@example.com",
            password=PASSWORD,
        )

    def _signup(self, email, **extra):
        return self.client.post(
            reverse("signup"),
            {"email": email, "password1": PASSWORD, "password2": PASSWORD},
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