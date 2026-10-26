"""Focused coverage for professor search, filters and pagination.

The repository contract mixin runs against both storage backends so search
semantics cannot drift between the in-memory and ORM implementations.
"""
import re
from html import unescape
from urllib.parse import parse_qs, urlsplit

from django.test import TestCase
from django.urls import reverse

from .django_repo import DjangoRepository
from .repository import InMemoryRepository
from .tests import _MemoryRepoTestCase, _repo_review


class SearchContractMixin:
    def _make(self):
        raise NotImplementedError

    def setUp(self):
        super().setUp()
        self.repo = self._make()
        self.bishkek = self.repo.add_school("Первый вуз", "Бишкек")
        self.osh = self.repo.add_school("Второй вуз", "Ош")
        self.ivan = self.repo.add_professor(
            self.bishkek.id, "Иван", "Петров", "Физика", "доцент"
        )
        self.anna = self.repo.add_professor(
            self.bishkek.id, "Анна", "Смирнова", "Математика", "профессор"
        )
        self.alan = self.repo.add_professor(
            self.osh.id, "Алан", "Тьюринг", "Информатика", "доцент"
        )
        self.john = self.repo.add_professor(
            self.osh.id, "Джон", "О'Коннор", "Лингвистика", "доцент"
        )
        self.pending = self.repo.add_professor(
            self.bishkek.id, "Пётр", "Скрытый", "Физика", "доцент", status="pending"
        )
        self.repo.add_review(self.ivan.id, _repo_review(course="К1", overall=4),
                             status="approved")
        self.repo.add_review(self.anna.id, _repo_review(course="К2", overall=5),
                             status="approved")
        self.repo.add_review(self.alan.id, _repo_review(course="К3", overall=3),
                             status="approved")

    @property
    def approved_ids(self):
        return {self.ivan.id, self.anna.id, self.alan.id, self.john.id}

    def _ids(self, **kwargs):
        return {x["prof"].id for x in self.repo.search(**kwargs)}

    def test_empty_query_returns_all_approved(self):
        for q in ("", "   ", "\t\n"):
            with self.subTest(q=q):
                self.assertEqual(self._ids(q=q), self.approved_ids)

    def test_query_matches_name_and_department_case_insensitively(self):
        self.assertEqual(self._ids(q="пЕтРоВ"), {self.ivan.id})
        self.assertEqual(self._ids(q="ФИЗИКА"), {self.ivan.id})
        self.assertEqual(self._ids(q="о'Ко"), {self.john.id})
        self.assertEqual(self._ids(q="ИВАн ПЕТРОВ"), {self.ivan.id})

    def test_special_characters_are_literal_not_wildcards(self):
        # SQL LIKE wildcards, regex metacharacters and quote/injection payloads
        # must never broaden the result set.
        for q in ("%", "_", "%%", ".*", "[а-я]", "\\", "'; DROP TABLE professors; --"):
            with self.subTest(q=q):
                self.assertEqual(self._ids(q=q), set())

    def test_special_characters_match_only_when_present_literally(self):
        self.assertEqual(self._ids(q="'"), {self.john.id})

    def test_school_filter_returns_only_that_school(self):
        self.assertEqual(self._ids(school_slug=self.bishkek.slug),
                         {self.ivan.id, self.anna.id})
        self.assertEqual(self._ids(school_slug=self.osh.slug),
                         {self.alan.id, self.john.id})

    def test_unknown_school_city_and_department_return_empty(self):
        self.assertEqual(self._ids(school_slug="no-such-school"), set())
        self.assertEqual(self._ids(city="Атлантида"), set())
        self.assertEqual(self._ids(department="Несуществующая"), set())

    def test_query_and_filters_are_combined(self):
        self.assertEqual(
            self._ids(q="петров", school_slug=self.bishkek.slug, city="Бишкек",
                      department="Физика"),
            {self.ivan.id},
        )
        self.assertEqual(
            self._ids(q="петров", school_slug=self.osh.slug, city="Ош",
                      department="Информатика"),
            set(),
        )

    def test_pending_professor_never_leaks_through_search_or_filters(self):
        self.assertNotIn(self.pending.id, self._ids())
        self.assertNotIn(self.pending.id, self._ids(q="Скрытый"))
        self.assertNotIn(self.pending.id, self._ids(department="Физика"))
        self.assertNotIn(self.pending.id, self._ids(school_slug=self.bishkek.slug))


class MemorySearchContractTests(SearchContractMixin, TestCase):
    def _make(self):
        return InMemoryRepository()


class DjangoSearchContractTests(SearchContractMixin, TestCase):
    def _make(self):
        return DjangoRepository()


class HomeSearchPaginationTests(_MemoryRepoTestCase):
    def _add_professors(self, count, last_prefix="Джонс"):
        school = self.repo.schools()[0]
        for i in range(count):
            self.repo.add_professor(
                school.id, f"Смит{i:02d}", f"{last_prefix}{i:02d}",
                "Пагинация", "доцент",
            )

    def test_pagination_keeps_query_and_filters(self):
        self._add_professors(15)
        params = {"q": "смит", "department": "Пагинация"}
        first = self.client.get(reverse("home"), params)
        second = self.client.get(reverse("home"), {**params, "page": 2})

        self.assertEqual(first.context["page_obj"].paginator.num_pages, 2)
        self.assertEqual(len(first.context["results"]), 10)
        self.assertEqual(len(second.context["results"]), 5)
        for r in first.context["results"] + second.context["results"]:
            self.assertEqual(r["prof"].department, "Пагинация")
            self.assertTrue(r["prof"].full_name.startswith("Смит"))

        first_ids = {r["prof"].id for r in first.context["results"]}
        second_ids = {r["prof"].id for r in second.context["results"]}
        self.assertFalse(first_ids & second_ids)
        self.assertEqual(len(first_ids | second_ids), 15)

    def test_pagination_links_encode_special_characters_in_query(self):
        self._add_professors(15, last_prefix="Джонс&Ко")
        q = "джонс&ко"
        response = self.client.get(reverse("home"), {"q": q})

        self.assertEqual(response.context["page_obj"].paginator.num_pages, 2)
        match = re.search(r'href="([^"]*page=2[^"]*)"', response.content.decode())
        self.assertIsNotNone(match)
        query = parse_qs(urlsplit(unescape(match.group(1))).query)
        self.assertEqual(query.get("q"), [q])
        self.assertEqual(query.get("page"), ["2"])

    def test_out_of_range_and_invalid_pages_fall_back(self):
        for page in ("999", "abc", "0", "-1"):
            with self.subTest(page=page):
                response = self.client.get(reverse("home"), {"page": page})
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["results"])

    def test_special_character_query_shows_empty_state(self):
        for q in ("%", "_", ".*", "'; DROP TABLE professors; --"):
            with self.subTest(q=q):
                response = self.client.get(reverse("home"), {"q": q})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(list(response.context["results"]), [])
                self.assertContains(response, "Ничего не нашлось")

    def test_unknown_filter_values_show_empty_state(self):
        for params in ({"school": "no-such-school"}, {"city": "Атлантида"},
                       {"department": "Несуществующая"}):
            with self.subTest(**params):
                response = self.client.get(reverse("home"), params)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(list(response.context["results"]), [])
                self.assertContains(response, "Ничего не нашлось")
