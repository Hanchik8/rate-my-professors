from django.conf import settings
from django.contrib.auth.signals import user_login_failed
from django.test import TestCase


class SecurityLoggingTests(TestCase):
    def test_failed_login_is_logged_without_password(self):
        with self.assertLogs("security", level="WARNING") as cm:
            user_login_failed.send(
                sender=None,
                credentials={"username": "bob", "password": "s3cret"},
            )
        out = "\n".join(cm.output)
        self.assertIn("bob", out)
        self.assertNotIn("s3cret", out)

    def test_upload_limits_set(self):
        self.assertEqual(settings.DATA_UPLOAD_MAX_MEMORY_SIZE, 2_621_440)
        self.assertEqual(settings.FILE_UPLOAD_MAX_MEMORY_SIZE, 2_621_440)
