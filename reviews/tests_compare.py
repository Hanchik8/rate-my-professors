"""Tests for the professor comparison page and its card links."""
from django.test import TestCase
from django.urls import reverse

from . import store as store_mod
from .repository import InMemoryRepository
from .seed import seed


class CompareViewTests(TestCase):
    def setUp(self):
        self._original_repo = store_mod.repo
        import reviews.views as views

        self._original_view_repo = views.repo
        self.repo = InMemoryRepository()
        seed(self.repo)
        store_mod.repo = self.repo
        views.repo = self.repo
        self.professors = [row["prof"] for row in self.repo.search("")]

    def tearDown(self):
        import reviews.views as views

        store_mod.repo = self._original_repo
        views.repo = self._original_view_repo

    def _url(self, *professors):
        ids = ",".join(prof.id for prof in professors)
        return f"{reverse('compare')}?ids={ids}"

    def test_compare_shows_two_professors_with_stats(self):
        first, second = self.professors[:2]
        response = self.client.get(self._url(first, second))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["professors"]), 2)
        self.assertContains(response, first.full_name)
        self.assertContains(response, second.full_name)
        self.assertContains(response, "Средний балл")
        self.assertContains(response, "Отзывов")
        self.assertContains(response, "Сложность")
        self.assertContains(response, "Пойдут снова")
        self.assertEqual(
            response.context["professors"][0]["stats"],
            self.repo.stats(first.id),
        )

    def test_compare_accepts_three_professors(self):
        response = self.client.get(self._url(*self.professors[:3]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["professors"]), 3)
        for prof in self.professors[:3]:
            self.assertContains(response, prof.full_name)

    def test_invalid_selections_return_404_with_a_message(self):
        first, second = self.professors[:2]
        cases = {
            "no ids": ("", "Для сравнения"),
            "one id": (first.id, "Для сравнения"),
            "duplicate ids": (f"{first.id},{first.id}", "Для сравнения"),
            "too many ids": (
                ",".join(prof.id for prof in self.professors[:4]),
                "Для сравнения",
            ),
            "unknown id": (
                f"{first.id},00000000-0000-0000-0000-000000000000",
                "Преподаватель не найден",
            ),
            "malformed ids": ("not-a-uuid,also-not-a-uuid", "Преподаватель не найден"),
        }
        for label, (ids, message) in cases.items():
            with self.subTest(case=label):
                response = self.client.get(reverse("compare"), {"ids": ids})
                self.assertEqual(response.status_code, 404)
                self.assertContains(response, message, status_code=404)

    def test_card_compare_links_on_home_and_school_pages(self):
        prof = self.professors[0]
        compare_url = f"{reverse('compare')}?ids={prof.id}"
        school = self.repo.school(prof.school_id)

        home = self.client.get(reverse("home"))
        self.assertContains(home, compare_url)
        self.assertContains(home, "Сравнить")

        school_page = self.client.get(reverse("school_detail", args=[school.slug]))
        self.assertContains(school_page, compare_url)
        self.assertContains(school_page, "Сравнить")