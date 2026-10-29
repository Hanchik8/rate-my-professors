"""Signup email confirmation by a 6-digit code."""
import re
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import email_verification
from .models import EmailVerification

PASSWORD = "pass12345"
EMAIL = "new@example.com"


@override_settings(
    REQUIRE_EMAIL_VERIFICATION=True,
    RATELIMIT_ENABLE=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class EmailVerificationFlowTests(TestCase):
    def signup(self, email=EMAIL):
        return self.client.post(
            reverse("signup"),
            {"email": email, "password1": PASSWORD, "password2": PASSWORD},
        )

    def code_from_mail(self, index=-1):
        match = re.search(r"\b(\d{6})\b", mail.outbox[index].body)
        self.assertIsNotNone(match)
        return match.group(1)

    def verify(self, code):
        return self.client.post(reverse("signup_verify"), {"code": code})

    def user(self):
        return User.objects.get(username=EMAIL)

    def wrong(self, code):
        return "000000" if code != "000000" else "111111"

    def test_signup_sends_code_and_keeps_account_inactive(self):
        r = self.signup()
        self.assertRedirects(r, reverse("signup_verify"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [EMAIL])
        code = self.code_from_mail()
        self.assertIn(code, mail.outbox[0].subject)
        self.assertFalse(self.user().is_active)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_only_hash_of_code_is_stored(self):
        self.signup()
        code = self.code_from_mail()
        record = EmailVerification.objects.get(user=self.user())
        self.assertNotIn(code, record.code_hash)
        self.assertEqual(record.code_hash, email_verification.hash_code(self.user(), code))
        ttl = record.expires_at - record.last_sent_at
        self.assertEqual(ttl, timedelta(minutes=10))

    def test_verify_page_renders(self):
        self.signup()
        r = self.client.get(reverse("signup_verify"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, EMAIL)
        self.assertContains(r, 'name="code"')

    def test_correct_code_activates_and_logs_in(self):
        self.signup()
        r = self.verify(self.code_from_mail())
        self.assertRedirects(r, reverse("home"), fetch_redirect_response=False)
        self.assertTrue(self.user().is_active)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user().pk)
        self.assertFalse(EmailVerification.objects.exists())

    def test_wrong_code_does_not_activate(self):
        self.signup()
        r = self.verify(self.wrong(self.code_from_mail()))
        self.assertEqual(r.status_code, 200)
        self.assertIn("code", r.context["form"].errors)
        self.assertFalse(self.user().is_active)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(EmailVerification.objects.get().attempts, 1)

    def test_expired_code_does_not_activate(self):
        self.signup()
        code = self.code_from_mail()
        EmailVerification.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        r = self.verify(code)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(self.user().is_active)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_code_is_voided_after_five_wrong_attempts(self):
        self.signup()
        code = self.code_from_mail()
        for _ in range(5):
            self.verify(self.wrong(code))
        record = EmailVerification.objects.get()
        self.assertEqual(record.attempts, 5)
        self.assertEqual(record.code_hash, "")
        r = self.verify(code)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(self.user().is_active)

    def test_resend_is_limited_to_once_per_minute(self):
        self.signup()
        r = self.client.post(reverse("signup_verify"), {"action": "resend"})
        self.assertRedirects(r, reverse("signup_verify"), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)

        EmailVerification.objects.update(last_sent_at=timezone.now() - timedelta(seconds=61))
        self.client.post(reverse("signup_verify"), {"action": "resend"})
        self.assertEqual(len(mail.outbox), 2)
        new_code = self.code_from_mail()
        self.assertEqual(EmailVerification.objects.get().attempts, 0)
        self.verify(new_code)
        self.assertTrue(self.user().is_active)

    @override_settings(RATELIMIT_ENABLE=True, RATELIMIT={"signup": (5, 600), "verify": (10, 60), "resend": (1, 60)})
    def test_resend_is_also_rate_limited_per_ip(self):
        cache.clear()
        self.signup()
        EmailVerification.objects.update(last_sent_at=timezone.now() - timedelta(seconds=61))
        self.client.post(reverse("signup_verify"), {"action": "resend"})
        EmailVerification.objects.update(last_sent_at=timezone.now() - timedelta(seconds=61))
        self.client.post(reverse("signup_verify"), {"action": "resend"})
        self.assertEqual(len(mail.outbox), 2)
        cache.clear()

    def test_unverified_user_cannot_log_in_and_sees_link(self):
        self.signup()
        self.client.session.flush()
        r = self.client.post(reverse("login"), {"username": EMAIL, "password": PASSWORD})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(r, reverse("signup_verify"))
        self.assertEqual(self.client.session["verify_email"], EMAIL)
        # The link leads to a working code form for that account.
        code = self.code_from_mail()
        self.verify(code)
        self.assertTrue(self.user().is_active)

    def test_unverified_hint_requires_correct_password(self):
        self.signup()
        self.client.session.flush()
        r = self.client.post(reverse("login"), {"username": EMAIL, "password": "wrong-pass"})
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, reverse("signup_verify"))

    def test_existing_active_user_logs_in_normally(self):
        User.objects.create_user(username="old@example.com", email="old@example.com", password=PASSWORD)
        r = self.client.post(reverse("login"), {"username": "old@example.com", "password": PASSWORD})
        self.assertEqual(r.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_verify_without_pending_signup_redirects_to_login(self):
        r = self.client.get(reverse("signup_verify"))
        self.assertRedirects(r, reverse("login"), fetch_redirect_response=False)

    def test_send_failure_does_not_break_signup(self):
        with mock.patch("reviews.email_verification.send_mail", side_effect=OSError("smtp down")), \
                self.assertLogs("reviews.email_verification", "ERROR"):
            r = self.signup()
        self.assertRedirects(r, reverse("signup_verify"), fetch_redirect_response=False)
        self.assertTrue(EmailVerification.objects.filter(user=self.user()).exists())

    def test_generated_codes_are_six_digits(self):
        for _ in range(50):
            self.assertRegex(email_verification.generate_code(), r"^\d{6}$")


@override_settings(REQUIRE_EMAIL_VERIFICATION=False, RATELIMIT_ENABLE=False)
class EmailVerificationDisabledTests(TestCase):
    def test_signup_logs_in_immediately_when_disabled(self):
        r = self.client.post(
            reverse("signup"),
            {"email": EMAIL, "password1": PASSWORD, "password2": PASSWORD},
        )
        self.assertRedirects(r, reverse("home"), fetch_redirect_response=False)
        self.assertTrue(User.objects.get(username=EMAIL).is_active)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(len(mail.outbox), 0)
