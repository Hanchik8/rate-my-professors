from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from reviews.models import Professor, Review, School


class CheckDataCommandTests(TestCase):
    def test_reports_clean_data_without_modifying_records(self):
        school = School.objects.create(name="Example University", slug="example-university", city="Example")
        professor = Professor.objects.create(
            school=school,
            first_name="Ada",
            last_name="Lovelace",
            slug="ada-lovelace",
            department="Math",
            title="Professor",
        )
        review = Review.objects.create(
            professor=professor,
            course="Math",
            overall=5,
            difficulty=2,
            would_take_again=True,
            comment="Excellent",
        )

        output = StringIO()
        call_command("check_data", stdout=output)

        self.assertIn("Профессора без вуза: 0", output.getvalue())
        self.assertIn("Отзывы без профессора: 0", output.getvalue())
        self.assertIn("Дубли профессоров: 0", output.getvalue())
        self.assertTrue(Professor.objects.filter(pk=professor.pk).exists())
        self.assertTrue(Review.objects.filter(pk=review.pk).exists())

    def test_reports_duplicate_professors_case_insensitively(self):
        school = School.objects.create(name="Example University", slug="example-university", city="Example")
        Professor.objects.create(
            school=school,
            first_name="Ada",
            last_name="Lovelace",
            slug="ada-lovelace",
            department="Math",
            title="Professor",
        )
        Professor.objects.create(
            school=school,
            first_name="ADA",
            last_name="Lovelace",
            slug="ada-lovelace-duplicate",
            department="Math",
            title="Professor",
        )

        output = StringIO()
        call_command("check_data", stdout=output)

        self.assertIn("Дубли профессоров: 1", output.getvalue())
        self.assertIn("Example University: Ada Lovelace", output.getvalue())
        self.assertEqual(Professor.objects.count(), 2)
