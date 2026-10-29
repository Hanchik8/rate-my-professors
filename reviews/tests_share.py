"""Share control on the professor page: static JS, no-JS fallback, no inline JS."""
from pathlib import Path

from django.test import TestCase
from django.urls import reverse

from . import store as store_mod
from .repository import InMemoryRepository
from .seed import seed


class ProfessorShareTests(TestCase):
    def setUp(self):
        import reviews.views as views

        self.repo = InMemoryRepository()
        seed(self.repo)
        self._orig_store = store_mod.repo
        self._orig_views = views.repo
        store_mod.repo = self.repo
        views.repo = self.repo

    def tearDown(self):
        import reviews.views as views

        store_mod.repo = self._orig_store
        views.repo = self._orig_views

    def _get(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        response = self.client.get(reverse("professor", args=[prof.slug]))
        self.assertEqual(response.status_code, 200)
        return response, prof

    def test_share_button_script_and_fallback_are_rendered(self):
        response, prof = self._get()
        html = response.content.decode()
        # Button labelled via translatable strings, wired to the static script.
        self.assertContains(response, "data-share-button")
        self.assertContains(response, "Поделиться")
        self.assertContains(response, "reviews/share.js")
        # No-JS fallback: labelled read-only field with the absolute URL.
        self.assertContains(response, "Ссылка на страницу преподавателя")
        self.assertContains(response, "data-share-field")
        self.assertContains(response, f"/professors/{prof.slug}/")
        # Copied feedback string is available to the script and announced politely.
        self.assertContains(response, "Ссылка скопирована")
        self.assertContains(response, 'role="status"')
        self.assertIn('aria-label="Поделиться:', html)

    def test_share_javascript_exists_in_static_files(self):
        script = Path(__file__).parent / "static" / "reviews" / "share.js"
        self.assertTrue(script.is_file())
        self.assertTrue(script.read_text(encoding="utf-8").strip())

    def test_professor_page_has_no_inline_javascript(self):
        response, _ = self._get()
        self.assertNotRegex(
            response.content.decode(), r"<script(?![^>]*\bsrc=)(?![^>]*type=[\"']application/ld\+json[\"'])[^>]*>\s*[^\s<]"
        )
