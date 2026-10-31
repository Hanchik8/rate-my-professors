"""Coverage for professor search, filters, pagination and empty states.

The repository contract mixin runs against both storage backends so search
semantics cannot drift between the in-memory and ORM implementations.
"""
import re
from html import unescape
from urllib.parse import parse_qs, urlsplit

from django.core.cache import cache
from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from .constants import PAGE_SIZE
from .django_repo import DjangoRepository
from .repository import InMemoryRepository
from .tests import _MemoryRepoTestCase, _repo_review


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
        for q in ("", "   ", "\t\n", None):
            with self.subTest(q=q):
                self.assertEqual(self._ids(q=q), self.approved_ids)

    def test_query_matches_name_and_department_case_insensitively(self):
        self.assertEqual(self._ids(q="пЕтРоВ"), {self.ivan.id})
        self.assertEqual(self._ids(q="ФИЗИКА"), {self.ivan.id})
        self.assertEqual(self._ids(q="о'Ко"), {self.john.id})
        self.assertEqual(self._ids(q="ИВАн ПЕТРОВ"), {self.ivan.id})

    def test_query_word_order_does_not_matter(self):
        gulnara = self.repo.add_professor(
            self.bishkek.id, "Гульнара", "Асанова", "Лингвистика", "доцент"
        )
        self.assertEqual(self._ids(q="Гульнара Асанова"), {gulnara.id})
        self.assertEqual(self._ids(q="Асанова Гульнара"), {gulnara.id})
        self.assertEqual(self._ids(q="Иван Петров"), {self.ivan.id})
        self.assertEqual(self._ids(q="Петров Иван"), {self.ivan.id})
        self.assertEqual(self._ids(q="  Петров   Иван  "), {self.ivan.id})

    def test_latin_query_matches_cyrillic_professor_names(self):
        asanova = self.repo.add_professor(
            self.bishkek.id, "Гульнара", "Асанова", "Лингвистика", "доцент"
        )
        bekboev = self.repo.add_professor(
            self.bishkek.id, "Айбек", "Бекбоев", "Физика", "доцент"
        )
        self.assertEqual(self._ids(q="Asanova"), {asanova.id})
        self.assertEqual(self._ids(q="Bekboev"), {bekboev.id})
        self.assertEqual(self._ids(q="Bekboev Физика"), {bekboev.id})

    def test_query_requires_every_word_to_match(self):
        self.assertEqual(self._ids(q="Иван Смирнова"), set())
        self.assertEqual(self._ids(q="Петров Физика"), {self.ivan.id})
        self.assertEqual(self._ids(q="Смирнова Физика"), set())

    def test_query_is_insensitive_to_yo_and_e(self):
        with_yo = self.repo.add_professor(
            self.bishkek.id, "Пётр", "Ёлкин", "Физика", "доцент"
        )
        with_e = self.repo.add_professor(
            self.bishkek.id, "Елена", "Егорова", "Математика", "доцент"
        )

        for q in ("пётр ёлкин", "петр елкин", "ПЁТР ЁЛКИН", "ПЕТР ЕЛКИН", "ёлкин", "елкин"):
            with self.subTest(q=q):
                self.assertEqual(self._ids(q=q), {with_yo.id})
        for q in ("елена егорова", "ёлена ёгорова", "ЕЛЕНА ЕГОРОВА", "ЁЛЕНА ЁГОРОВА"):
            with self.subTest(q=q):
                self.assertEqual(self._ids(q=q), {with_e.id})

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

    def test_surrounding_whitespace_is_trimmed_in_all_filters(self):
        self.assertEqual(self._ids(q="  петров  "), {self.ivan.id})
        self.assertEqual(self._ids(department="  Физика  "), {self.ivan.id})
        self.assertEqual(self._ids(city="  Бишкек  "),
                         {self.ivan.id, self.anna.id})
        self.assertEqual(self._ids(school_slug=f"  {self.bishkek.slug}  "),
                         {self.ivan.id, self.anna.id})

    def test_whitespace_only_filters_return_all_approved(self):
        for kwargs in (
            {"school_slug": "   "},
            {"city": "\t\n"},
            {"department": "  "},
        ):
            with self.subTest(**kwargs):
                self.assertEqual(self._ids(**kwargs), self.approved_ids)

    def test_overlong_query_and_filter_values_return_empty(self):
        long_text = "я" * 10000
        for kwargs in (
            {"q": long_text},
            {"school_slug": "s" * 10000},
            {"city": long_text},
            {"department": long_text},
        ):
            with self.subTest(**kwargs):
                self.assertEqual(self._ids(**kwargs), set())

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

    def test_invalid_sort_values_fall_back_to_rating_order(self):
        expected = [row["prof"].id for row in self.repo.search("", sort="rating")]
        for sort in ("", "RATING", "Reviews", "newest", "helpful",
                     "rating desc", "'; DROP TABLE professors; --"):
            with self.subTest(sort=sort):
                actual = [row["prof"].id for row in self.repo.search("", sort=sort)]
                self.assertEqual(actual, expected)

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


class HomeSearchPaginationTests(_MemoryRepoTestCase):
    def test_home_search_input_has_aria_label(self):
        response = self.client.get(reverse("home"))

        self.assertContains(response, '<input type="search" name="q"')
        self.assertRegex(
            response.content.decode(),
            r'<input\b(?=[^>]*\btype="search")(?=[^>]*\bname="q")'
            r'(?=[^>]*\baria-label="Поиск")[^>]*>',
        )

    def _add_professors(self, count, last_prefix="Джонс"):
        school = self.repo.schools()[0]
        for i in range(count):
            self.repo.add_professor(
                school.id, f"Смит{i:02d}", f"{last_prefix}{i:02d}",
                "Пагинация", "доцент",
            )

    def test_home_and_school_pages_expose_mobile_viewport_and_labeled_search(self):
        home = self.client.get(reverse("home"))
        school = self.repo.schools()[0]
        school_response = self.client.get(reverse("school_detail", args=[school.slug]))

        for response in (home, school_response):
            with self.subTest(path=response.request["PATH_INFO"]):
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, '<meta name="viewport" content="width=device-width, initial-scale=1">')

        self.assertContains(home, 'aria-label="Поиск"')
        self.assertContains(home, 'aria-label="Город"')
        self.assertContains(home, 'aria-label="Вуз"')
        self.assertContains(home, 'aria-label="Кафедра"')
        self.assertContains(home, 'aria-label="Сортировка"')

    def test_home_search_matches_professor_name(self):
        response = self.client.get(reverse("home"), {"q": "Айбек Токтогулов"})

        self.assertEqual(response.status_code, 200)
        names = [row["prof"].full_name for row in response.context["results"]]
        self.assertEqual(names, ["Айбек Токтогулов"])

    def test_home_sort_by_rating_orders_results_by_average(self):
        school = self.repo.schools()[0]
        high = self.repo.add_professor(
            school.id, "Рейтинг", "Высокий", "Проверка сортировки", "доцент"
        )
        low = self.repo.add_professor(
            school.id, "Рейтинг", "Низкий", "Проверка сортировки", "доцент"
        )
        self.repo.add_review(high.id, _repo_review(course="Рейтинг 1", overall=5), status="approved")
        self.repo.add_review(low.id, _repo_review(course="Рейтинг 2", overall=2), status="approved")

        response = self.client.get(
            reverse("home"), {"department": "Проверка сортировки", "sort": "rating"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["prof"].id for row in response.context["results"]],
            [high.id, low.id],
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

    def test_out_of_range_page_for_filtered_query_stays_in_results(self):
        self._add_professors(15)
        params = {"q": "смит", "department": "Пагинация", "page": "999"}
        response = self.client.get(reverse("home"), params)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].number,
                         response.context["page_obj"].paginator.num_pages)
        self.assertEqual(len(response.context["results"]), 5)
        for row in response.context["results"]:
            self.assertEqual(row["prof"].department, "Пагинация")
            self.assertTrue(row["prof"].full_name.startswith("Смит"))

    def test_out_of_range_page_with_no_results_is_empty(self):
        response = self.client.get(
            reverse("home"), {"q": "неттакого", "page": "999"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["results"]), [])
        self.assertContains(response, "Ничего не нашлось")

    def test_extremely_long_page_value_falls_back(self):
        response = self.client.get(reverse("home"), {"page": "9" * 5000})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["results"])

    def test_overlong_query_and_filter_values_show_empty_state(self):
        long_text = "я" * 10000
        for param in ("q", "school", "city", "department"):
            with self.subTest(param=param):
                response = self.client.get(reverse("home"), {param: long_text})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(list(response.context["results"]), [])
                self.assertContains(response, "Ничего не нашлось")

    def test_whitespace_only_filters_list_everyone(self):
        for params in (
            {"school": "   "},
            {"city": "\t\n"},
            {"department": "  "},
        ):
            with self.subTest(**params):
                response = self.client.get(reverse("home"), params)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["results"])

    def test_invalid_sort_values_keep_rating_order(self):
        expected = [
            row["prof"].id
            for row in self.client.get(reverse("home"), {"sort": "rating"}).context["results"]
        ]
        for sort in ("", "RATING", "Reviews", "newest", "helpful",
                     "rating desc", "'; DROP TABLE professors; --"):
            with self.subTest(sort=sort):
                response = self.client.get(reverse("home"), {"sort": sort})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["sort"], "rating")
                self.assertEqual(
                    [row["prof"].id for row in response.context["results"]],
                    expected,
                )

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
        self.assertContains(response, "Попробуйте сократить запрос или изменить фильтры.")
        self.assertContains(response, "Сбросить фильтры")
        self.assertContains(response, f'href="{reverse("home")}"')

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
        self.assertContains(response, "Добавьте преподавателя, чтобы студенты могли делиться опытом.")
        self.assertContains(response, f'href="{reverse("add_professor")}"')
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


class HomeEmptyStateRenderTests(_MemoryRepoTestCase):
    """An empty search result renders a hint and a link that resets filters."""

    EMPTY_STATE_TEXTS = {
        "ru": ("Ничего не нашлось", "Попробуйте сократить запрос или изменить фильтры.",
               "Сбросить фильтры"),
        "ky": ("Эч нерсе табылган жок", "Суроону кыскартып же чыпкаларды өзгөртүп көрүңүз.",
               "Чыпкаларды тазалоо"),
        "en": ("Nothing found", "Try a shorter query or change the filters.",
               "Reset filters"),
    }

    def setUp(self):
        cache.clear()
        super().setUp()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def _empty_response(self, **extra):
        return self.client.get(reverse("home"), {"q": "неттакого", **extra})

    def _reset_href(self, response):
        """Return the reset-filters link target, whatever the attribute order."""
        html = response.content.decode()
        anchor = re.search(r'<a\b[^>]*empty-state-action[^>]*>', html)
        self.assertIsNotNone(anchor, "empty state must render the reset-filters link")
        href = re.search(r'href="([^"]*)"', anchor.group(0))
        self.assertIsNotNone(href, "reset-filters link must carry an href")
        return unescape(href.group(1))

    def test_empty_results_render_hint_and_reset_link(self):
        response = self._empty_response()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["results"]), [])
        self.assertContains(response, 'role="status"')
        self.assertContains(response, "Ничего не нашлось")
        self.assertContains(response, "Попробуйте сократить запрос или изменить фильтры.")
        self.assertContains(response, ">Сбросить фильтры</a>")

    def test_reset_link_targets_home_without_query_parameters(self):
        response = self._empty_response(city="Ош", department="Несуществующая")

        target = urlsplit(self._reset_href(response))
        self.assertEqual(target.path, reverse("home"))
        self.assertEqual(target.query, "")

    def test_reset_link_leads_to_unfiltered_results(self):
        response = self._empty_response()

        reset = self.client.get(self._reset_href(response))

        self.assertEqual(reset.status_code, 200)
        self.assertTrue(reset.context["results"])
        self.assertNotContains(reset, "Ничего не нашлось")
        self.assertNotContains(reset, "Сбросить фильтры")

    def test_empty_state_hidden_when_search_has_results(self):
        response = self.client.get(reverse("home"), {"q": "Айбек"})

        self.assertTrue(response.context["results"])
        self.assertNotContains(response, "Ничего не нашлось")
        self.assertNotContains(response, "Сбросить фильтры")

    def test_empty_state_rendered_in_every_supported_language(self):
        for lang, texts in self.EMPTY_STATE_TEXTS.items():
            with self.subTest(lang=lang):
                response = self.client.get(
                    reverse("home"), {"q": "неттакого"}, HTTP_ACCEPT_LANGUAGE=lang
                )
                self.assertEqual(response.status_code, 200)
                for text in texts:
                    self.assertContains(response, text)
                for other, other_texts in self.EMPTY_STATE_TEXTS.items():
                    if other == lang:
                        continue
                    for text in other_texts:
                        self.assertNotContains(response, text)


class SearchIndicatorTests(_MemoryRepoTestCase):
    def test_query_shows_header_and_reset_link_preserving_filters(self):
        cache.clear()
        response = self.client.get(
            "/", {"q": "Айбек", "city": "Бишкек", "sort": "reviews"}
        )
        total = len(response.context["results"])

        self.assertContains(response, f"Результаты по запросу «Айбек»: {total}")
        self.assertContains(response, ">Сбросить поиск</a>")

        html = response.content.decode()
        anchor = re.search(r'<a\b[^>]*class="reset-search"[^>]*>', html)
        self.assertIsNotNone(anchor)
        href = unescape(re.search(r'href="([^"]*)"', anchor.group(0)).group(1))
        target = urlsplit(href)
        query = parse_qs(target.query)

        self.assertEqual(target.path, reverse("home"))
        self.assertNotIn("q", query)
        self.assertEqual(query.get("city"), ["Бишкек"])
        self.assertEqual(query.get("sort"), ["reviews"])

        without_query = self.client.get("/")
        self.assertNotContains(without_query, "Результаты по запросу")
        self.assertNotContains(without_query, "Сбросить поиск")
        cache.clear()


class PaginationRenderTests(SimpleTestCase):
    def test_renders_window_edges_and_preserves_filters(self):
        page_obj = Paginator(list(range(250)), 10).get_page(5)
        request = RequestFactory().get("/", {
            "q": "смит",
            "department": "Физика",
            "sort": "reviews",
            "page": "5",
        })

        html = render_to_string(
            "reviews/_pagination.html",
            {"page_obj": page_obj, "request": request},
        )

        self.assertRegex(html, r'aria-current="page"[^>]*>5</span>')
        self.assertIn("…", html)
        for label in ("Первая", "Назад", "Вперёд", "Последняя"):
            self.assertIn(f">{label}</a>", html)

        match = re.search(r'href="([^"]*page=6[^"]*)"', html)
        self.assertIsNotNone(match)
        query = parse_qs(urlsplit(unescape(match.group(1))).query)
        self.assertEqual(query, {
            "q": ["смит"],
            "department": ["Физика"],
            "sort": ["reviews"],
            "page": ["6"],
        })