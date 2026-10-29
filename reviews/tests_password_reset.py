from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse


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

    def test_unknown_email_uses_same_confirmation(self):
        response = self.client.post(reverse("password_reset"), {"email": "missing@example.com"})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(RATELIMIT_ENABLE=True, RATELIMIT={"login": (1, 60)})
    def test_reset_form_is_rate_limited_by_login_policy(self):
        self.client.post(reverse("password_reset"), {"email": "missing@example.com"})
        response = self.client.post(reverse("password_reset"), {"email": "missing@example.com"})
        self.assertEqual(response.status_code, 429)
