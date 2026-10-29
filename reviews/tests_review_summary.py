"""Render tests for the compact rating summary on the professor page."""
import re
from pathlib import Path

from django.test import TestCase
from django.urls import reverse
from django.utils import translation
from django.utils.formats import localize

from .repository import InMemoryRepository
from .seed import seed

STYLESHEET = Path(__file__).parent / "static" / "reviews" / "style.css"


class ReviewSummaryRenderTests(TestCase):
    def setUp(self):
        import reviews.views as views
        from reviews import store

        self.repo = InMemoryRepository()
        seed(self.repo)
        self._original_store = store.repo
        self._original_view = views.repo
        store.repo = self.repo
        views.repo = self.repo

    def tearDown(self):
        import reviews.views as views
        from reviews import store

        store.repo = self._original_store
        views.repo = self._original_view

    def _professor(self):
        return self.repo.search("Айбек")[0]["prof"]

    def _new_professor_without_reviews(self):
        school = next(s for s in self.repo.schools() if self.repo.professors_for_school(s.id))
        return self.repo.add_professor(
            school.id, "Тихон", "Безотзывов", "Физика", "доцент"
        )

    def test_summary_renders_average_rating_and_count_above_reviews(self):
        prof = self._professor()
        stats = self.repo.stats(prof.id)

        with translation.override("ru"):
            response = self.client.get(reverse("professor", args=[prof.slug]))
            html = response.content.decode()
            rating = localize(stats["overall"])
            expected_label = (
                f"Средний рейтинг: {rating} / 5, Отзывов: {stats['count']}"
            )

        self.assertEqual(response.status_code, 200)
        self.assertIn('class="review-summary"', html)
        self.assertIn('role="group"', html)
        self.assertIn(f'aria-label="{expected_label}"', html)
        self.assertIn('class="review-summary-label">Средний рейтинг<', html)
        self.assertIn(
            f'class="review-summary-count">Отзывов: {stats["count"]}<', html
        )
        self.assertLess(html.index('class="review-summary"'), html.index('class="review"'))

    def test_summary_empty_state_shows_no_ratings(self):
        prof = self._new_professor_without_reviews()

        with translation.override("ru"):
            response = self.client.get(reverse("professor", args=[prof.slug]))
            html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn('class="review-summary"', html)
        self.assertIn('aria-label="Нет оценок"', html)
        self.assertIn('class="tile small none">-<', html)
        self.assertIn('class="review-summary-count">Отзывов: 0<', html)

    def test_summary_labels_are_localized(self):
        prof = self._professor()
        expected = {
            "en": ("Average rating", "Ratings"),
            "ky": ("Орточо рейтинг", "Сын-пикирлер"),
        }
        for lang, (rating_label, count_label) in expected.items():
            with self.subTest(lang=lang):
                response = self.client.get(
                    reverse("professor", args=[prof.slug]),
                    HTTP_ACCEPT_LANGUAGE=lang,
                )
                html = response.content.decode()
                self.assertIn(
                    f'class="review-summary-label">{rating_label}<', html
                )
                self.assertIn(
                    f'class="review-summary-count">{count_label}:', html
                )

    def test_summary_styles_use_theme_tokens(self):
        css = STYLESHEET.read_text(encoding="utf-8")
        summary = re.search(r"\.review-summary\{.*?\}", css, re.DOTALL)
        text_block = re.search(r"\.review-summary-text\{.*?\}", css, re.DOTALL)
        count_block = re.search(r"\.review-summary-count\{.*?\}", css, re.DOTALL)

        self.assertIsNotNone(summary)
        self.assertIn("var(--surface)", summary.group(0))
        self.assertIn("var(--line)", summary.group(0))
        self.assertIn("var(--muted)", count_block.group(0))
        self.assertIsNotNone(text_block)
        self.assertIn("@media (prefers-color-scheme:dark)", css)
