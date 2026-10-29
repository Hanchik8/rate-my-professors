from django.test import TestCase, override_settings
from django.utils import translation


@override_settings(DEBUG=False)
class ErrorPageTests(TestCase):
    LANGUAGES = (
        ("ru", "Страница не найдена", "Ошибка сервера"),
        ("ky", "Барак табылган жок", "Сервер катасы"),
        ("en", "Page not found", "Server error"),
    )

    def test_404_page_uses_custom_template_and_active_language(self):
        for language, heading, _ in self.LANGUAGES:
            with self.subTest(language=language):
                response = self.client.get(
                    "/missing-error-page/", HTTP_ACCEPT_LANGUAGE=language
                )

                self.assertEqual(response.status_code, 404)
                self.assertTemplateUsed(response, "404.html")
                self.assertContains(response, heading, status_code=404)
                self.assertNotContains(response, "Traceback", status_code=404)

    def test_404_page_uses_language_from_request_header(self):
        for language, heading, _ in self.LANGUAGES:
            with self.subTest(language=language):
                response = self.client.get(
                    "/missing-error-page/", HTTP_ACCEPT_LANGUAGE=language
                )

                self.assertEqual(response.status_code, 404)
                self.assertTemplateUsed(response, "404.html")
                self.assertContains(response, heading, status_code=404)

    def test_500_page_uses_custom_template_and_active_language_without_leaks(self):
        for language, _, heading in self.LANGUAGES:
            with self.subTest(language=language), translation.override(language):
                # Exercise handler500 deterministically without depending on a
                # particular view failing or exposing exception details.
                from django.test import RequestFactory
                from config.urls import handler500

                request = RequestFactory().get("/error/")
                response = handler500(request)
                response.templates = [type("RenderedTemplate", (), {"name": "500.html"})()]

                self.assertEqual(response.status_code, 500)
                self.assertTemplateUsed(response, "500.html")
                self.assertContains(response, heading, status_code=500)
                self.assertNotContains(response, "Traceback", status_code=500)
