"""Focused tests for :mod:`reviews.sanitize`.

The helpers deliberately do not strip HTML: review text is stored as-is and
Django's autoescaping renders it as text.  These tests therefore pin down
both halves of that contract - control-character hygiene in the sanitizer and
HTML/XSS escaping at the rendering boundary.
"""
from unittest.mock import patch

from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse

from . import services
from .constants import MAX_COMMENT_LENGTH, MIN_COMMENT_LENGTH
from .sanitize import clean_text, strip_control_chars
from .tests import _MemoryRepoTestCase, _repo_review
from .throttle import is_rate_limited


class StripControlCharsTests(SimpleTestCase):
    def test_removes_every_c0_control_except_tab_lf_and_cr(self):
        for code in range(0x20):
            char = chr(code)
            with self.subTest(code=code):
                expected = char if char in "\t\n\r" else ""
                self.assertEqual(strip_control_chars(f"a{char}b"), f"a{expected}b")

    def test_removes_del_and_all_c1_controls(self):
        for code in range(0x7F, 0xA0):
            char = chr(code)
            with self.subTest(code=code):
                self.assertEqual(strip_control_chars(f"a{char}b"), "ab")

    def test_only_control_characters_become_empty_string(self):
        value = "".join(chr(code) for code in range(0x20) if chr(code) not in "\t\n\r")
        value += "".join(chr(code) for code in range(0x7F, 0xA0))
        self.assertEqual(strip_control_chars(value), "")

    def test_falsy_values_return_empty_string(self):
        for value in ("", None, 0, False):
            with self.subTest(value=value):
                self.assertEqual(strip_control_chars(value), "")
                self.assertEqual(clean_text(value), "")

    def test_keeps_ordinary_text_html_and_unicode_untouched(self):
        value = '<b>Отзыв</b> про курс — 100% полезно! <img src="x.png"> 😀'
        self.assertEqual(strip_control_chars(value), value)

    def test_preserves_tab_lf_and_cr_verbatim(self):
        self.assertEqual(strip_control_chars("a\tb\nc\rd"), "a\tb\nc\rd")

    def test_is_idempotent(self):
        dirty = "a\x00b\x07c\x1b d\x7f"
        once = strip_control_chars(dirty)
        self.assertEqual(strip_control_chars(once), once)


class CleanTextTests(SimpleTestCase):
    def test_empty_none_and_whitespace_only_values_become_empty(self):
        for value in ("", None, "   ", "\t\n\r\n", " \t \n "):
            with self.subTest(value=value):
                self.assertEqual(clean_text(value), "")

    def test_control_characters_only_become_empty(self):
        value = " \x00\x07\x1b\r\n\x7f\x85 "
        self.assertEqual(clean_text(value), "")

    def test_normalizes_crlf_and_lone_cr_to_lf(self):
        self.assertEqual(clean_text("a\r\nb\rc\rd"), "a\nb\nc\nd")
        self.assertEqual(clean_text("a\r\n\r\nb"), "a\n\nb")
        self.assertEqual(clean_text("a\r\x00b\r\nc"), "a\nb\nc")

    def test_preserves_internal_tabs_and_newlines_but_trims_outer_space(self):
        self.assertEqual(clean_text(" \t a\tb\nc \n "), "a\tb\nc")

    def test_trims_unicode_whitespace_around_text(self):
        self.assertEqual(clean_text("\u00a0 отзыв \u00a0"), "отзыв")

    def test_removes_control_chars_without_inserting_spaces(self):
        self.assertEqual(clean_text("Сло\x00во\x07 и\x1b ещё"), "Слово и ещё")

    def test_html_markup_is_preserved_verbatim(self):
        payload = '<script>alert("xss")</script>'
        self.assertEqual(clean_text(payload), payload)

        formatting = "<b>жирный</b> и <img src=x onerror=alert(1)>"
        self.assertEqual(clean_text(formatting), formatting)

    def test_html_entities_are_not_decoded_or_reencoded(self):
        value = "&lt;script&gt; &amp; &quot;кавычки&quot;"
        self.assertEqual(clean_text(value), value)

    def test_control_chars_inside_markup_are_removed_and_newlines_normalized(self):
        self.assertEqual(
            clean_text('<a href="x"\x00>\r\nтекст\x07</a>'),
            '<a href="x">\nтекст</a>',
        )

    def test_minimum_length_is_a_form_concern_not_a_sanitizer_concern(self):
        value = "x" * (MIN_COMMENT_LENGTH - 1)
        self.assertEqual(clean_text(value), value)
        self.assertEqual(len(clean_text(value)), MIN_COMMENT_LENGTH - 1)

    def test_maximum_length_text_is_preserved_exactly(self):
        value = "я" * MAX_COMMENT_LENGTH
        self.assertEqual(clean_text(value), value)
        self.assertEqual(len(clean_text(value)), MAX_COMMENT_LENGTH)

    def test_over_maximum_text_is_not_silently_truncated(self):
        value = "я" * (MAX_COMMENT_LENGTH + 1)
        self.assertEqual(len(clean_text(value)), MAX_COMMENT_LENGTH + 1)

    def test_sanitizing_twice_changes_nothing(self):
        dirty = " \x00 Первая\r\nВторая\x07\tстрока \x1b "
        once = clean_text(dirty)
        self.assertEqual(clean_text(once), once)

    def test_plain_text_is_returned_unchanged(self):
        value = "Понятные лекции и честные экзамены, рекомендую."
        self.assertEqual(clean_text(value), value)


class ReviewTextXssTests(_MemoryRepoTestCase):
    def test_script_comment_is_escaped_when_rendered(self):
        prof = self.prof()
        payload = '<script>alert("xss")</script> и ещё текст'
        review = self.repo.add_review(
            prof.id, _repo_review(course="XSS курс", comment=payload), status="approved"
        )
        self.assertEqual(review.comment, payload)

        response = self.client.get(reverse("professor", args=[prof.slug]))
        self.assertNotContains(response, payload)
        self.assertContains(response, "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;")

    def test_html_formatting_and_event_handlers_are_escaped_not_interpreted(self):
        prof = self.prof()
        payload = '<b>жирный</b><img src=x onerror=alert(1)>'
        self.repo.add_review(
            prof.id, _repo_review(course="HTML курс", comment=payload), status="approved"
        )

        response = self.client.get(reverse("professor", args=[prof.slug]))
        self.assertNotContains(response, "<b>жирный</b>")
        self.assertNotContains(response, "<img src=x onerror=alert(1)>")
        self.assertContains(response, "&lt;b&gt;жирный&lt;/b&gt;&lt;img")

    def test_control_characters_are_stripped_before_storage(self):
        prof = self.prof()
        review = self.repo.add_review(
            prof.id,
            _repo_review(
                course="Ал\x07горитмы",
                comment="Полезный\x00 курс с практикой\x1b и примерами.",
            ),
            status="approved",
        )
        self.assertEqual(review.course, "Алгоритмы")
        self.assertEqual(review.comment, "Полезный курс с практикой и примерами.")


class ThrottleTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.request = RequestFactory().post("/")
        self.request.META["REMOTE_ADDR"] = "192.0.2.1"

    @override_settings(RATELIMIT_ENABLE=True, RATELIMIT={"test": (2, 10)})
    def test_allows_limit_then_rejects_excess_hits(self):
        self.assertFalse(is_rate_limited(self.request, "test"))
        self.assertFalse(is_rate_limited(self.request, "test"))
        self.assertTrue(is_rate_limited(self.request, "test"))

    @override_settings(RATELIMIT_ENABLE=True, RATELIMIT={"test": (1, 10)})
    def test_fixed_window_resets_when_cache_entry_expires(self):
        now = [100.0]
        with patch("django.core.cache.backends.locmem.time.time", side_effect=lambda: now[0]):
            self.assertFalse(is_rate_limited(self.request, "test"))
            self.assertTrue(is_rate_limited(self.request, "test"))
            now[0] = 111.0
            self.assertFalse(is_rate_limited(self.request, "test"))

    @override_settings(RATELIMIT_ENABLE=True, RATELIMIT={"test": (1, 10)})
    def test_counters_are_independent_per_subject(self):
        other_request = RequestFactory().post("/")
        other_request.META["REMOTE_ADDR"] = "192.0.2.2"
        self.assertFalse(is_rate_limited(self.request, "test"))
        self.assertTrue(is_rate_limited(self.request, "test"))
        self.assertFalse(is_rate_limited(other_request, "test"))

    @override_settings(RATELIMIT_ENABLE=True, RATELIMIT={"test": (1, 10)})
    def test_authenticated_user_is_independent_of_other_users(self):
        user_a, user_b = _User("alice"), _User("bob")
        self.assertFalse(is_rate_limited(self.request, "test", user_a))
        self.assertTrue(is_rate_limited(self.request, "test", user_a))
        self.assertFalse(is_rate_limited(self.request, "test", user_b))


class _User:
    is_authenticated = True

    def __init__(self, username):
        self.username = username

    def get_username(self):
        return self.username


class ProfessorListingDefaultsTests(SimpleTestCase):
    def test_search_uses_empty_filters_and_rating_sort_by_default(self):
        class Repository:
            def search(self, *args):
                self.args = args
                return ["result"]

        repository = Repository()

        self.assertEqual(services.search_professors(repository), ["result"])
        self.assertEqual(repository.args, ("", "", "", "", "rating"))

    def test_school_listing_returns_repository_result_unchanged(self):
        expected = object()

        class Repository:
            def search(self, *args):
                self.args = args
                return expected

        repository = Repository()

        self.assertIs(services.professors_for_school(repository, "slug"), expected)
        self.assertEqual(repository.args, ("", "slug", "", "", "rating"))
