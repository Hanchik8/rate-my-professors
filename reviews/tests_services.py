"""Tests for the shared professor listing service."""

from django.test import SimpleTestCase
import os
import subprocess
import sys

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from io import StringIO

from . import services
from .caching import stats_cache_key
from .django_repo import DjangoRepository
from .constants import MAX_COMMENT_LENGTH, MIN_COMMENT_LENGTH, PAGE_SIZE, RATE_LIMITS
from .forms import ReviewForm
from .models import Professor, Report, Review, School
from .tests import _valid
from .views import _paginate


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


class MigrationStateTests(SimpleTestCase):
    def test_makemigrations_check_finds_no_changes(self):
        env = os.environ.copy()
        env.setdefault("DEBUG", "True")
        result = subprocess.run(
            [sys.executable, "manage.py", "makemigrations", "--check", "--dry-run"],
            capture_output=True, text=True, env=env, check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        self.assertIn("No changes detected", result.stdout)


class ProfessorStatsCacheTests(TestCase):
    def setUp(self):
        cache.clear()
        self.repo = DjangoRepository()
        school = School.objects.create(name="Test University", slug="test-university", city="Test")
        self.professor = Professor.objects.create(
            school=school, first_name="Test", last_name="Teacher", slug="test-teacher",
            department="Test", title="Professor", status="approved",
        )

    def tearDown(self):
        cache.clear()

    def make_review(self, overall):
        return Review.objects.create(
            professor=self.professor, course="Course", overall=overall, difficulty=2,
            would_take_again=True, comment="Test review", status="approved",
        )

    def test_stats_are_cached(self):
        self.make_review(4)
        professor_id = str(self.professor.pk)
        stats = self.repo.stats(professor_id)
        self.assertEqual(stats["overall"], 4)
        self.assertEqual(cache.get(stats_cache_key(professor_id)), stats)

    def test_review_create_and_update_invalidate_stats(self):
        professor_id = str(self.professor.pk)
        self.assertEqual(self.repo.stats(professor_id)["count"], 0)
        review = self.make_review(3)
        self.assertEqual(self.repo.stats(professor_id)["overall"], 3)
        review.overall = 5
        review.save()
        self.assertEqual(self.repo.stats(professor_id)["overall"], 5)


class SharedConstantsTests(SimpleTestCase):
    def test_database_connection_max_age_setting(self):
        self.assertEqual(settings.DATABASES["default"]["CONN_MAX_AGE"], 0)

    def test_review_comment_limits_are_sane(self):
        self.assertEqual(MIN_COMMENT_LENGTH, 20)
        self.assertEqual(MAX_COMMENT_LENGTH, 1000)
        self.assertLess(MIN_COMMENT_LENGTH, MAX_COMMENT_LENGTH)

    def test_sanitize_reexports_comment_limits(self):
        from . import sanitize
        self.assertEqual(sanitize.MIN_COMMENT_LENGTH, MIN_COMMENT_LENGTH)
        self.assertEqual(sanitize.MAX_COMMENT_LENGTH, MAX_COMMENT_LENGTH)

    def test_pagination_uses_page_size_constant(self):
        page_items, page_obj = _paginate(list(range(PAGE_SIZE + 1)), 1)
        self.assertEqual(len(page_items), PAGE_SIZE)
        self.assertEqual(page_obj.paginator.per_page, PAGE_SIZE)

    def test_settings_rate_limits_match_constants(self):
        self.assertEqual(settings.RATELIMIT, RATE_LIMITS)

    def test_expected_rate_limit_actions_are_defined(self):
        self.assertEqual(set(RATE_LIMITS), {"login", "signup", "review", "report", "vote", "verify", "resend"})
        for limit, window in RATE_LIMITS.values():
            self.assertGreater(limit, 0)
            self.assertGreater(window, 0)

    def test_review_and_report_allow_five_posts_per_minute(self):
        self.assertEqual(RATE_LIMITS["review"], (5, 60))
        self.assertEqual(RATE_LIMITS["report"], (5, 60))


class ReviewAndReportFieldLimitTests(SimpleTestCase):
    def test_text_model_fields_have_matching_length_limits(self):
        self.assertEqual(Review._meta.get_field("comment").max_length, MAX_COMMENT_LENGTH)
        for field in ("course", "term", "grade"):
            self.assertIsNotNone(Review._meta.get_field(field).max_length)
        self.assertIsNotNone(Report._meta.get_field("reason").max_length)

    def test_model_full_clean_rejects_overlong_review_text(self):
        for field in ("course", "term", "grade", "comment"):
            model_field = Review._meta.get_field(field)
            values = {"course": "Курс", "term": "", "grade": "", "overall": 5,
                      "difficulty": 1, "would_take_again": True, "comment": "Достаточно длинный комментарий."}
            values[field] = "x" * (model_field.max_length + 1)
            review = Review(**values)
            with self.subTest(field=field), self.assertRaises(ValidationError) as caught:
                review.clean() if field == "comment" else model_field.clean(getattr(review, field), review)
            self.assertTrue(caught.exception.messages)

    def test_review_form_rejects_overlong_course_and_term(self):
        for field in ("course", "term"):
            limit = Review._meta.get_field(field).max_length
            form = ReviewForm(_valid({field: "x" * (limit + 1)}))
            with self.subTest(field=field):
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    def test_report_model_full_clean_rejects_overlong_reason(self):
        field = Report._meta.get_field("reason")
        report = Report(reason="x" * (field.max_length + 1))
        with self.assertRaises(ValidationError) as caught:
            report.full_clean()
        self.assertIn("reason", caught.exception.message_dict)


class CheckDataCommandTests(TestCase):
    def test_reports_clean_data_without_modifying_records(self):
        school = School.objects.create(name="Example University", slug="example-university", city="Example")
        professor = Professor.objects.create(school=school, first_name="Ada", last_name="Lovelace",
            slug="ada-lovelace", department="Math", title="Professor")
        review = Review.objects.create(professor=professor, course="Math", overall=5, difficulty=2,
            would_take_again=True, comment="Excellent")
        output = StringIO()
        call_command("check_data", stdout=output)
        self.assertIn("Профессора без вуза: 0", output.getvalue())
        self.assertIn("Отзывы без профессора: 0", output.getvalue())
        self.assertIn("Дубли профессоров: 0", output.getvalue())
        self.assertTrue(Professor.objects.filter(pk=professor.pk).exists())
        self.assertTrue(Review.objects.filter(pk=review.pk).exists())

    def test_case_insensitive_duplicate_professors_are_blocked_by_the_database(self):
        # Production schema has a case-insensitive unique index, so check_data
        # never sees such duplicates: the database refuses them up front.
        from django.db import IntegrityError, transaction
        school = School.objects.create(name="Example University", slug="example-university", city="Example")
        Professor.objects.create(school=school, first_name="Ada", last_name="Lovelace",
            slug="ada-lovelace", department="Math", title="Professor")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Professor.objects.create(school=school, first_name="ADA", last_name="Lovelace",
                slug="ada-lovelace-duplicate", department="Math", title="Professor")
        output = StringIO()
        call_command("check_data", stdout=output)
        self.assertIn("Дубли профессоров: 0", output.getvalue())
