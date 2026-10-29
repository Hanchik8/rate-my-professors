"""Edge-case coverage for professor search input and page numbers.

Complements the search and pagination suites with adversarial input:
markup payloads in the query string, SQL-LIKE special characters that
must always match literally, control bytes, and exotic ``page`` values
(float-like, exponent, signed, whitespace-padded, unicode digits, huge).
"""
import re

from django.test import TestCase
from django.urls import reverse

from .constants import PAGE_SIZE
from .django_repo import DjangoRepository
from .repository import InMemoryRepository
from .tests_search_pagination_empty import _ListedRepoMixin


class SearchSpecialsContractMixin(_ListedRepoMixin):
    """Wildcards, quotes and control bytes match literally, never broadly."""

    def setUp(self):
        super().setUp()
        self.john = self.repo.add_professor(
            self.school.id, "Джон", "О'Коннор", "Каф%едра_1", "доцент"
        )
        self.ivan = self.repo.add_professor(
            self.school.id, "Иван", "Петров", "Физика", "доцент"
        )

    def _ids(self, **kwargs):
        return {row["prof"].id for row in self.repo.search(**kwargs)}

    def test_wildcard_characters_match_only_literal_occurrences(self):
        for q in ("%", "_", "'", "каф%едра_1", "о'коннор"):
            with self.subTest(q=q):
                self.assertEqual(self._ids(q=q), {self.john.id})

    def test_doubled_wildcards_and_absent_characters_match_nothing(self):
        for q in ("%%", "__", '"', "`"):
            with self.subTest(q=q):
                self.assertEqual(self._ids(q=q), set())

    def test_plain_professor_never_matches_bare_wildcard(self):
        for q in ("%", "_", "'"):
            with self.subTest(q=q):
                self.assertNotIn(self.ivan.id, self._ids(q=q))

    def test_control_characters_in_query_are_safe_and_match_nothing(self):
        for q in ("\x00", "a\x00b", "\x1b[31m"):
            with self.subTest(q=q):
                self.assertEqual(self._ids(q=q), set())

    def test_view_search_treats_wildcards_literally(self):
        response = self.client.get(reverse("home"), {"q": "%"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["prof"].id for row in response.context["results"]],
            [self.john.id],
        )

    def test_view_search_with_quote_finds_only_literal_match(self):
        response = self.client.get(reverse("home"), {"q": "'"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["prof"].id for row in response.context["results"]],
            [self.john.id],
        )

    def test_empty_and_whitespace_query_lists_everything_on_first_page(self):
        self._add_professors(PAGE_SIZE + 1)

        for q in ("", "   ", "\t\n"):
            with self.subTest(q=q):
                response = self.client.get(reverse("home"), {"q": q})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["page_obj"].number, 1)
                self.assertEqual(response.context["page_obj"].paginator.num_pages, 2)
                self.assertEqual(len(response.context["results"]), PAGE_SIZE)


class PageNumberFallbackContractMixin(_ListedRepoMixin):
    """Any ``page`` value yields a valid page, never a crash or a blank list."""

    def _url(self):
        raise NotImplementedError

    def setUp(self):
        super().setUp()
        self._add_professors(PAGE_SIZE + 1)
        self._last_page = 2

    def _results_on_page(self, number):
        return PAGE_SIZE if number == 1 else 1

    def test_exotic_page_values_fall_back_to_a_valid_page(self):
        cases = (
            ("", 1), ("abc", 1), ("1.5", 1), ("1e10", 1),
            ("2", 2), (" 2 ", 2), ("٢", 2),
            ("0", 2), ("-1", 2), ("+3", 2),
        )
        for page, expected in cases:
            with self.subTest(page=page):
                response = self.client.get(self._url(), {"page": page})
                self.assertEqual(response.status_code, 200)
                page_obj = response.context["page_obj"]
                self.assertEqual(page_obj.number, expected)
                self.assertEqual(page_obj.paginator.num_pages, self._last_page)
                self.assertEqual(
                    len(response.context["results"]),
                    self._results_on_page(expected),
                )

    def test_huge_numeric_page_values_fall_back_to_last_page(self):
        for page in ("9" * 1000, "-" + "9" * 1000, "٩" * 100):
            with self.subTest(page=page[:12]):
                response = self.client.get(self._url(), {"page": page})
                self.assertEqual(response.status_code, 200)
                page_obj = response.context["page_obj"]
                self.assertEqual(page_obj.number, self._last_page)
                self.assertEqual(
                    len(response.context["results"]),
                    self._results_on_page(self._last_page),
                )

    def test_special_query_with_exotic_page_shows_empty_state(self):
        response = self.client.get(
            reverse("home"), {"q": "<script>x</script>", "page": "1e10"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["results"]), [])
        self.assertIsNone(response.context["page_obj"])
        self.assertContains(response, "Ничего не нашлось")
        self.assertNotContains(response, "<script>x</script>")


class HomeMarkupSafetyTests(_ListedRepoMixin, TestCase):
    """Markup payloads in the query string render escaped, never executable."""

    def _make_repo(self):
        return InMemoryRepository()

    def test_script_tag_in_query_is_escaped_and_finds_nothing(self):
        response = self.client.get(
            reverse("home"), {"q": "<script>alert(1)</script>"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["results"]), [])
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;script&gt;alert(1)&lt;/script&gt;")
        self.assertContains(response, "Ничего не нашлось")

    def test_attribute_breakout_payload_stays_inside_value_attribute(self):
        payload = '"><img src=x onerror=alert(1)>'
        response = self.client.get(reverse("home"), {"q": payload})

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<img src=x")
        self.assertNotContains(response, 'value=""><img')
        html = response.content.decode()
        match = re.search(
            r'<input\b[^>]*\bname="q"[^>]*value="([^"]*)"', html
        )
        self.assertIsNotNone(match, "search input must echo the query as its value")
        self.assertEqual(match.group(1), "&quot;&gt;&lt;img src=x onerror=alert(1)&gt;")

    def test_markup_payloads_in_filters_render_no_raw_tags(self):
        for param in ("school", "city", "department"):
            with self.subTest(param=param):
                response = self.client.get(
                    reverse("home"), {param: "<script>x</script>"}
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(list(response.context["results"]), [])
                self.assertNotContains(response, "<script>x</script>")

    def test_control_characters_in_query_do_not_crash(self):
        for q in ("\x00", "a\x00b", "\x1b[31m"):
            with self.subTest(q=q):
                response = self.client.get(reverse("home"), {"q": q})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(list(response.context["results"]), [])


class MemorySearchSpecialsTests(SearchSpecialsContractMixin, TestCase):
    def _make_repo(self):
        return InMemoryRepository()


class DjangoSearchSpecialsTests(SearchSpecialsContractMixin, TestCase):
    def _make_repo(self):
        return DjangoRepository()


class HomePaginationEdgeTests(PageNumberFallbackContractMixin, TestCase):
    def _make_repo(self):
        return InMemoryRepository()

    def _url(self):
        return reverse("home")


class SchoolPaginationEdgeTests(PageNumberFallbackContractMixin, TestCase):
    def _make_repo(self):
        return InMemoryRepository()

    def _url(self):
        return reverse("school_detail", args=[self.school.slug])
