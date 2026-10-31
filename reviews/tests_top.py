from django.test import TestCase
from django.urls import reverse

from .repository import InMemoryRepository
from . import views


class TopViewTests(TestCase):
    def setUp(self):
        self.repo = InMemoryRepository()
        self.school = self.repo.add_school("Тестовый вуз", "Бишкек")
        self.other_school = self.repo.add_school("Другой вуз", "Ош")
        self.previous_repo = views.repo
        views.repo = self.repo

        self.best = self.repo.add_professor(self.school.id, "Анна", "Лучше", "Физика", "доцент")
        self.second = self.repo.add_professor(self.school.id, "Борис", "Средний", "Математика", "доцент")
        self.other = self.repo.add_professor(self.other_school.id, "Вера", "Иная", "Физика", "доцент")
        self.low_count = self.repo.add_professor(self.school.id, "Глеб", "Мало", "Физика", "доцент")
        self._ratings(self.best, [5, 5, 4])
        self._ratings(self.second, [3, 3, 3])
        self._ratings(self.other, [5, 5, 5])
        self._ratings(self.low_count, [5, 5])

    def tearDown(self):
        views.repo = self.previous_repo

    def _ratings(self, prof, ratings):
        for score in ratings:
            self.repo.add_review(prof.id, {
                "course": "Курс", "term": "", "overall": score, "difficulty": 3,
                "would_take_again": True, "grade": "A", "comment": "", "tags": [],
            }, status="approved")

    def test_top_requires_three_approved_reviews_and_sorts_by_average(self):
        response = self.client.get(reverse("top"))
        self.assertEqual([r["prof"].id for r in response.context["results"]],
                         [self.other.id, self.best.id, self.second.id])
        self.assertContains(response, "1.")
        self.assertNotContains(response, self.low_count.full_name)

    def test_school_and_department_filters(self):
        response = self.client.get(reverse("top"), {
            "school": self.school.slug, "department": "Физика",
        })
        self.assertEqual([r["prof"].id for r in response.context["results"]], [self.best.id])

    def test_limits_to_twenty(self):
        for i in range(20):
            prof = self.repo.add_professor(self.school.id, "Профессор", str(i), "История", "доцент")
            self._ratings(prof, [4, 4, 4])
        self.assertEqual(len(self.client.get(reverse("top")).context["results"]), 20)
