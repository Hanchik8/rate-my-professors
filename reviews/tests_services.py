"""Tests for the shared professor listing service."""

from django.test import SimpleTestCase

from . import services


class ProfessorListingServiceTests(SimpleTestCase):
    def test_search_forwards_all_filters_and_sort_to_repository(self):
        expected = [{"prof": "professor"}]

        class Repository:
            def search(self, *args):
                self.args = args
                return expected

        repository = Repository()
        results = services.search_professors(
            repository, "Иван", school="school", city="Бишкек",
            department="Физика", sort="reviews",
        )

        self.assertEqual(results, expected)
        self.assertEqual(
            repository.args,
            ("Иван", "school", "Бишкек", "Физика", "reviews"),
        )

    def test_school_listing_uses_empty_query_and_school_filter(self):
        class Repository:
            def search(self, *args):
                self.args = args
                return []

        repository = Repository()
        results = services.professors_for_school(repository, "my-school")

        self.assertEqual(results, [])
        self.assertEqual(repository.args, ("", "my-school", "", "", "rating"))
