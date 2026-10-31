from django.test import TestCase
from django.urls import reverse

from . import store as store_mod
from .repository import InMemoryRepository
from .seed import seed

LANGUAGES = ["ru", "ky", "en"]


class RobotsTxtI18nTests(TestCase):
    def test_robots_txt_status_and_content_type_per_language(self):
        for lang in LANGUAGES:
            with self.subTest(language=lang):
                response = self.client.get("/robots.txt", HTTP_ACCEPT_LANGUAGE=lang)
                self.assertEqual(response.status_code, 200, f"status 200 expected for {lang}")
                self.assertIn("text/plain", response["Content-Type"], f"text/plain expected for {lang}")

    def test_robots_txt_key_content_per_language(self):
        for lang in LANGUAGES:
            with self.subTest(language=lang):
                response = self.client.get("/robots.txt", HTTP_ACCEPT_LANGUAGE=lang)
                self.assertContains(response, "User-agent: *")
                self.assertContains(response, "Allow: /")
                self.assertContains(response, "Sitemap:")
                self.assertContains(response, reverse("sitemap_index"))


class SitemapXmlI18nTests(TestCase):
    def setUp(self):
        self._orig = store_mod.repo
        self.repo = InMemoryRepository()
        seed(self.repo)
        store_mod.repo = self.repo

    def tearDown(self):
        store_mod.repo = self._orig

    def test_sitemap_index_status_and_content_type_per_language(self):
        for lang in LANGUAGES:
            with self.subTest(language=lang):
                response = self.client.get(reverse("sitemap_index"), HTTP_ACCEPT_LANGUAGE=lang)
                self.assertEqual(response.status_code, 200, f"status 200 expected for {lang}")
                self.assertIn("xml", response["Content-Type"], f"xml content-type expected for {lang}")

    def test_sitemap_index_key_content_per_language(self):
        for lang in LANGUAGES:
            with self.subTest(language=lang):
                response = self.client.get(reverse("sitemap_index"), HTTP_ACCEPT_LANGUAGE=lang)
                self.assertContains(response, "/sitemap-home.xml")
                self.assertContains(response, "/sitemap-schools.xml")
                self.assertContains(response, "/sitemap-professors.xml")

    def test_sitemap_sections_status_and_content_type_per_language(self):
        for section in ("home", "schools", "professors"):
            for lang in LANGUAGES:
                with self.subTest(language=lang, section=section):
                    response = self.client.get(
                        f"/sitemap-{section}.xml", HTTP_ACCEPT_LANGUAGE=lang
                    )
                    self.assertEqual(response.status_code, 200, f"status 200 expected for {lang}/{section}")
                    self.assertIn("xml", response["Content-Type"], f"xml content-type expected for {lang}/{section}")


class SchoolPagePublicTests(TestCase):
    def setUp(self):
        self._orig_repo = store_mod.repo
        import reviews.views as views
        self._orig_view_repo = views.repo
        self.repo = InMemoryRepository()
        store_mod.repo = views.repo = self.repo
        self.school = self.repo.add_school("Публичный университет", "Бишкек")

    def tearDown(self):
        import reviews.views as views
        store_mod.repo = self._orig_repo
        views.repo = self._orig_view_repo

    def test_school_page_status_and_content_type(self):
        response = self.client.get(reverse("school_detail", args=[self.school.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])

    def test_school_page_displays_school_and_empty_state(self):
        response = self.client.get(reverse("school_detail", args=[self.school.slug]))
        self.assertContains(response, self.school.name)
        self.assertContains(response, self.school.city)
        self.assertContains(response, "Пока нет кафедр.")
        self.assertContains(response, "Пока нет преподавателей.")
        self.assertContains(response, reverse("add_professor"))

    def test_school_page_returns_404_for_unknown_school(self):
        response = self.client.get(reverse("school_detail", args=["unknown-school"]))
        self.assertEqual(response.status_code, 404)


ABOUT_CASES = [
    ("ru", "О проекте"),
    ("ky", "Долбоор жөнүндө"),
    ("en", "About"),
]


class AboutI18nTests(TestCase):
    def test_about_status_and_content_type_per_language(self):
        for lang, _ in ABOUT_CASES:
            with self.subTest(language=lang):
                response = self.client.get(reverse("about"), HTTP_ACCEPT_LANGUAGE=lang)
                self.assertEqual(response.status_code, 200, f"status 200 expected for {lang}")
                self.assertIn("text/html", response["Content-Type"], f"text/html expected for {lang}")

    def test_about_key_content_per_language(self):
        for lang, heading in ABOUT_CASES:
            with self.subTest(language=lang):
                response = self.client.get(reverse("about"), HTTP_ACCEPT_LANGUAGE=lang)
                self.assertContains(response, heading, msg_prefix=f"heading '{heading}' not found for {lang}")
                self.assertContains(response, "ProfLens")
