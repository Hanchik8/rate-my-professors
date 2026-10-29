import os
import subprocess
import sys

from django.test import SimpleTestCase


class MigrationStateTests(SimpleTestCase):
    def test_makemigrations_check_finds_no_changes(self):
        env = os.environ.copy()
        env.setdefault("DEBUG", "True")
        result = subprocess.run(
            [sys.executable, "manage.py", "makemigrations", "--check", "--dry-run"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("No changes detected", result.stdout)
