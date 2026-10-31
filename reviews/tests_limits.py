"""Shared constants and model-level field length limits."""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .constants import MAX_COMMENT_LENGTH, MIN_COMMENT_LENGTH, PAGE_SIZE, RATE_LIMITS
from .forms import ReviewForm
from .models import Report, Review
from .tests import _valid
from .views import _paginate


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
        items = list(range(PAGE_SIZE + 1))
        page_items, page_obj = _paginate(items, 1)

        self.assertEqual(len(page_items), PAGE_SIZE)
        self.assertEqual(page_obj.paginator.per_page, PAGE_SIZE)

    def test_settings_rate_limits_match_constants(self):
        self.assertEqual(settings.RATELIMIT, RATE_LIMITS)

    def test_expected_rate_limit_actions_are_defined(self):
        self.assertEqual(
            set(RATE_LIMITS), {"login", "signup", "review", "report", "vote", "verify", "resend"}
        )
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
            values = {
                "course": "Курс", "term": "", "grade": "",
                "overall": 5, "difficulty": 1, "would_take_again": True,
                "comment": "Достаточно длинный комментарий.",
            }
            values[field] = "x" * (model_field.max_length + 1)
            review = Review(**values)
            with self.subTest(field=field), self.assertRaises(ValidationError) as caught:
                if field == "comment":
                    review.clean()
                else:
                    model_field.clean(getattr(review, field), review)
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