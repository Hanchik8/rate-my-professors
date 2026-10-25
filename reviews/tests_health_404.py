import json

from django.test import TestCase, override_settings
from django.urls import reverse


class HealthEndpointTests(TestCase):
    """GET /health/ — liveness probe for the container orchestrator."""

    def test_health_returns_200_json_ok(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(json.loads(response.content), {"status": "ok"})


@override_settings(DEBUG=False)
class Custom404PageTests(TestCase):
    """Custom 404.html is rendered (not Django's debug page) in every locale."""

    # (language code, expected translated heading from 404.html)
    CASES = [
        ("ru", "Страница не найдена"),
        ("ky", "Барак табылган жок"),
        ("en", "Page not found"),
    ]

    def _get_missing(self, lang):
        return self.client.get(
            "/no-such-page/", HTTP_ACCEPT_LANGUAGE=lang
        )

    def test_404_status_custom_template_and_content_per_language(self):
        for lang, heading in self.CASES:
            with self.subTest(language=lang):
                response = self._get_missing(lang)
                self.assertEqual(response.status_code, 404)
                self.assertTemplateUsed(response, "404.html")
                self.assertContains(response, heading, status_code=404)
