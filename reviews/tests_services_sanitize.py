"""Tests for defaults and edge cases in listing and text helpers."""

from django.test import SimpleTestCase

from . import services
from .sanitize import clean_text, strip_control_chars


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


class SanitizerFalsyInputTests(SimpleTestCase):
    def test_falsy_inputs_return_empty_string(self):
        for value in (None, "", 0, False):
            with self.subTest(value=value):
                self.assertEqual(strip_control_chars(value), "")
                self.assertEqual(clean_text(value), "")

    def test_clean_text_normalizes_carriage_return_before_stripping_controls(self):
        self.assertEqual(clean_text("a\r\x00b\r\nc"), "a\nb\nc")
