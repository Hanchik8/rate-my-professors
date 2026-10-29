"""Query-count tests for the profile and professor pages."""
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .django_repo import DjangoRepository


def _review_data(course, tags=None):
    return {
        "course": course,
        "term": "Осень 2026",
        "overall": 4,
        "difficulty": 3,
        "would_take_again": True,
        "grade": "A",
        "comment": "Достаточно длинный комментарий для теста запросов.",
        "tags": tags or ["Интересные лекции"],
    }


@override_settings(CACHES={
    "default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"},
})
class PageQueryCountTests(TestCase):
    def setUp(self):
        import reviews.views as views
        from reviews import store

        self.repo = DjangoRepository()
        self._original_store_repo = store.repo
        self._original_view_repo = views.repo
        store.repo = self.repo
        views.repo = self.repo

        self.user = User.objects.create_user(
            username="querycount@example.com",
            email="querycount@example.com",
            password="pass12345",
        )
        self.school = self.repo.add_school("Тестовый университет", "Бишкек")
        self.prof = self.repo.add_professor(
            self.school.id, "Иван", "Петров", "Физика", "доцент"
        )
        self.client.force_login(self.user)

    @override_settings(CACHES={
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    })
    def test_home_filter_options_are_cached_and_invalidated(self):
        cache.clear()
        url = reverse("home")

        # The first request loads schools/cities/departments; later requests
        # should reuse those options, while the catalog version invalidates
        # them after a school or review write.
        self.client.get(url)
        with CaptureQueriesContext(connection) as warm:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(any("FROM \"reviews_school\"" in q["sql"] for q in warm.captured_queries))

        new_school = self.repo.add_school("Другой университет", "Ош")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(new_school.name, [school.name for school in response.context["schools"]])

        self._add_reviews("Новый отзыв", 1)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_home_pagination_uses_materialized_results_without_count_query(self):
        self._add_reviews("Отзыв", 2)
        for index in range(12):
            self.repo.add_professor(
                self.school.id, f"Имя{index}", f"Фамилия{index}", "Физика", "доцент"
            )
        url = reverse("home")
        self.client.get(url)  # populate options and result caches

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(url, {"page": "2"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].number, 2)
        self.assertFalse(any(
            "COUNT(" in q["sql"].upper() and "REVIEWS_PROFESSOR" in q["sql"].upper()
            for q in captured.captured_queries
        ))

    def tearDown(self):
        import reviews.views as views
        from reviews import store

        store.repo = self._original_store_repo
        views.repo = self._original_view_repo
        super().tearDown()

    def _add_reviews(self, prefix, count):
        for index in range(count):
            self.repo.add_review(
                self.prof.id,
                _review_data(
                    f"{prefix} {index}",
                    tags=["Интересные лекции", "Много тестов"],
                ),
                user=self.user,
                status="approved",
            )

    def _query_count(self, url, data=None):
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(url, data or {})
        self.assertEqual(response.status_code, 200)
        return len(captured.captured_queries)

    def test_profile_query_count_does_not_grow_with_reviews(self):
        url = reverse("profile")
        self._add_reviews("Базовый", 2)
        self.client.get(url)  # warm session storage

        before = self._query_count(url)
        self._add_reviews("Больше", 6)
        with self.assertNumQueries(before):
            response = self.client.get(url)
        self.assertEqual(len(response.context["reviews"]), 8)

    def test_professor_sort_query_count_does_not_grow_with_reviews(self):
        url = reverse("professor", args=[self.prof.slug])
        sorts = ("new", "old", "high", "low", "helpful")
        self._add_reviews("Базовый", 2)
        self.client.get(url)  # warm session storage

        before = {
            sort: self._query_count(url, {"sort": sort})
            for sort in sorts
        }

        self._add_reviews("Больше", 6)

        for sort in sorts:
            with self.subTest(sort=sort):
                with self.assertNumQueries(before[sort]):
                    response = self.client.get(url, {"sort": sort})
                self.assertEqual(len(response.context["reviews"]), 8)

    def test_home_and_school_query_counts_do_not_grow_with_professors(self):
        # Catalog queries are normally cached; dummy cache makes cold and warm
        # behavior deterministic, so warm these page payloads before measuring.
        home_url = reverse("home")
        school_url = reverse("school_detail", args=[self.school.slug])
        self.client.get(home_url)
        self.client.get(school_url)

        home_before = self._query_count(home_url)
        school_before = self._query_count(school_url)

        for index in range(4):
            self.repo.add_professor(
                self.school.id, f"Имя{index}", f"Фамилия{index}", "Физика", "доцент"
            )

        with self.assertNumQueries(home_before):
            home_response = self.client.get(home_url)
        with self.assertNumQueries(school_before):
            school_response = self.client.get(school_url)
        self.assertEqual(len(home_response.context["results"]), 5)
        self.assertEqual(len(school_response.context["results"]), 5)

    def test_school_page_query_count_is_constant_with_professors(self):
        url = reverse("school_detail", args=[self.school.slug])
        self.client.get(url)  # warm the school result cache
        before = self._query_count(url)

        for index in range(5):
            self.repo.add_professor(
                self.school.id, f"Кафедра{index}", f"Преподаватель{index}", "Математика", "доцент"
            )

        with self.assertNumQueries(before):
            response = self.client.get(url)
        self.assertEqual(len(response.context["results"]), 6)
