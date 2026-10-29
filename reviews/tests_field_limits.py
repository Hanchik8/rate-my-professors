"""Model-level length constraints for user-submitted review text."""

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .constants import MAX_COMMENT_LENGTH
from .forms import ReviewForm
from .models import Report, Review
from .tests import _valid


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

    def test_review_form_rejects_overlong_course_term_and_comment(self):
        for field in ("course", "term", "comment"):
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
