"""Pagination boundaries and empty professor-search results in list views."""
import re
from html import unescape
from urllib.parse import parse_qs, urlsplit

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .constants import PAGE_SIZE
from .django_repo import DjangoRepository
from .repository import InMemoryRepository


class _ListedRepoMixin:
    def _make_repo(self):
        raise NotImplementedError

    def setUp(self):
        cache.clear()
        import reviews.views as views
        from reviews import store as store_mod

        self.repo = self._make_repo()
        self._orig_store_repo = store_mod.repo
        self._orig_views_repo = views.repo
        store_mod.repo = self.repo
        views.repo = self.repo
        self.school = self.repo.add_school("Тестовый список", "Бишкек")

    def tearDown(self):
        import reviews.views as views
        from reviews import store as store_mod

        store_mod.repo = self._orig_store_repo
        views.repo = self._orig_views_repo
        cache.clear()
        super().tearDown()

    def _add_professors(self, count, *, school=None, prefix="Список",
                        department="Пагинация границ"):
        school = school or self.school
        return [
            self.repo.add_professor(
                school.id, f"{prefix}{i:02d}", f"Профессор{i:02d}",
                department, "доцент",
            )
            for i in range(count)
        ]


class HomePaginationEmptyContractMixin(_ListedRepoMixin):
    def test_empty_search_has_no_pagination_and_shows_empty_state(self):
        response = self.client.get(
            reverse("home"), {"q": "несуществующийпреподаватель"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["results"]), [])
        self.assertIsNone(response.context["page_obj"])
        self.assertNotContains(response, 'class="pagination"')
        self.assertContains(response, "Ничего не нашлось")

    def test_empty_search_with_any_page_parameter_stays_empty(self):
        for page in ("2", "999", "abc", "0", "-1"):
            with self.subTest(page=page):
                response = self.client.get(
                    reverse("home"), {"q": "несуществующийпреподаватель", "page": page}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(list(response.context["results"]), [])
                self.assertIsNone(response.context["page_obj"])
                self.assertNotContains(response, 'class="pagination"')
                self.assertContains(response, "Ничего не нашлось")

    def test_unmatched_query_with_existing_filters_shows_empty_state(self):
        self._add_professors(3, department="Существующая кафедра")

        response = self.client.get(reverse("home"), {
            "q": "несуществующийпреподаватель",
            "school": self.school.slug,
            "city": self.school.city,
            "department": "Существующая кафедра",
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["results"]), [])
        self.assertIsNone(response.context["page_obj"])
        self.assertContains(response, "Ничего не нашлось")
        self.assertNotContains(response, 'class="pagination"')

    def test_exactly_page_size_results_have_no_pagination(self):
        self._add_professors(PAGE_SIZE, department="Граница ровно")

        response = self.client.get(
            reverse("home"), {"department": "Граница ровно"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["results"]), PAGE_SIZE)
        self.assertIsNone(response.context["page_obj"])
        self.assertNotContains(response, 'class="pagination"')

    def test_page_size_plus_one_splits_into_two_pages(self):
        professors = self._add_professors(
            PAGE_SIZE + 1, department="Граница плюс один"
        )
        params = {"department": "Граница плюс один"}

        first = self.client.get(reverse("home"), params)
        second = self.client.get(reverse("home"), {**params, "page": 2})
        out_of_range = self.client.get(reverse("home"), {**params, "page": 999})

        self.assertEqual(first.context["page_obj"].paginator.num_pages, 2)
        self.assertEqual(len(first.context["results"]), PAGE_SIZE)
        self.assertEqual(second.context["page_obj"].number, 2)
        self.assertEqual(len(second.context["results"]), 1)
        self.assertEqual(out_of_range.context["page_obj"].number, 2)
        self.assertEqual(len(out_of_range.context["results"]), 1)

        first_ids = {row["prof"].id for row in first.context["results"]}
        second_ids = {row["prof"].id for row in second.context["results"]}
        self.assertFalse(first_ids & second_ids)
        self.assertEqual(first_ids | second_ids, {p.id for p in professors})

    def test_pagination_links_preserve_query_filter_and_sort(self):
        self._add_professors(
            PAGE_SIZE + 1, prefix="Ссылка", department="Ссылки пагинации"
        )
        params = {
            "q": "Профессор",
            "department": "Ссылки пагинации",
            "sort": "reviews",
        }

        response = self.client.get(reverse("home"), params)
        match = re.search(r'href="([^"]*page=2[^"]*)"', response.content.decode())

        self.assertIsNotNone(match)
        query = parse_qs(urlsplit(unescape(match.group(1))).query)
        self.assertEqual(query.get("q"), ["Профессор"])
        self.assertEqual(query.get("department"), ["Ссылки пагинации"])
        self.assertEqual(query.get("sort"), ["reviews"])
        self.assertEqual(query.get("page"), ["2"])


class SchoolPaginationEmptyContractMixin(_ListedRepoMixin):
    def test_school_without_professors_shows_empty_state_without_pagination(self):
        response = self.client.get(
            reverse("school_detail", args=[self.school.slug])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["results"]), [])
        self.assertIsNone(response.context["page_obj"])
        self.assertContains(response, "Пока нет преподавателей")
        self.assertNotContains(response, 'class="pagination"')

    def test_school_exactly_page_size_results_have_no_pagination(self):
        self._add_professors(PAGE_SIZE)

        response = self.client.get(
            reverse("school_detail", args=[self.school.slug])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["results"]), PAGE_SIZE)
        self.assertIsNone(response.context["page_obj"])
        self.assertNotContains(response, 'class="pagination"')

    def test_school_page_size_plus_one_splits_into_two_pages(self):
        professors = self._add_professors(PAGE_SIZE + 1)
        url = reverse("school_detail", args=[self.school.slug])

        first = self.client.get(url)
        second = self.client.get(url, {"page": 2})
        out_of_range = self.client.get(url, {"page": 999})

        self.assertEqual(first.context["page_obj"].paginator.num_pages, 2)
        self.assertEqual(len(first.context["results"]), PAGE_SIZE)
        self.assertEqual(second.context["page_obj"].number, 2)
        self.assertEqual(len(second.context["results"]), 1)
        self.assertEqual(out_of_range.context["page_obj"].number, 2)
        self.assertEqual(len(out_of_range.context["results"]), 1)

        first_ids = {row["prof"].id for row in first.context["results"]}
        second_ids = {row["prof"].id for row in second.context["results"]}
        self.assertFalse(first_ids & second_ids)
        self.assertEqual(first_ids | second_ids, {p.id for p in professors})


class MemoryHomePaginationEmptyTests(HomePaginationEmptyContractMixin, TestCase):
    def _make_repo(self):
        return InMemoryRepository()


class DjangoHomePaginationEmptyTests(HomePaginationEmptyContractMixin, TestCase):
    def _make_repo(self):
        return DjangoRepository()


class MemorySchoolPaginationEmptyTests(SchoolPaginationEmptyContractMixin, TestCase):
    def _make_repo(self):
        return InMemoryRepository()


class DjangoSchoolPaginationEmptyTests(SchoolPaginationEmptyContractMixin, TestCase):
    def _make_repo(self):
        return DjangoRepository()