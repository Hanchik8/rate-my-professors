import json
import tempfile
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from reviews.management.commands.import_professors import clean_record
from reviews.models import Professor, Review, School


class CleanRecordTests(TestCase):
    def test_normalizes_fields(self):
        rec = clean_record({"last_name": " Иванов ", "first_name": "Иван  Иванович, к.ф.-м.н.",
                            "department": "кафедра прикладной математики", "title": "Доцент"})
        self.assertEqual(rec, {"last_name": "Иванов", "first_name": "Иван Иванович",
                               "department": "Прикладной математики", "title": "доцент"})

    def test_rejects_junk_and_maps_unknown_title(self):
        self.assertIsNone(clean_record({"last_name": "Деканат", "first_name": "тел. 0312 123456"}))
        self.assertIsNone(clean_record({"last_name": "", "first_name": "Анна"}))
        self.assertEqual(clean_record({"last_name": "Smith", "first_name": "John",
                                       "title": "lecturer"})["title"], "преподаватель")
        self.assertEqual(clean_record({"last_name": "Петров", "first_name": "П. П."})["first_name"], "П. П.")


class ImportProfessorsTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(code="knu", name="КНУ", slug="knu", city="Бишкек")
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "knu.json").write_text(json.dumps({"code": "knu", "professors": [
            {"last_name": "Асанов", "first_name": "Бакыт Токтогулович", "department": "Физика", "title": "профессор"},
            {"last_name": "АСАНОВ", "first_name": "бакыт токтогулович", "department": "Физика", "title": "профессор"},
            {"last_name": "Ли", "first_name": "А. В.", "department": "История", "title": "доцент", "initials_only": True},
            {"last_name": "???", "first_name": "x1"},
        ]}), encoding="utf-8")
        (self.dir / "nope.json").write_text(json.dumps({"code": "nope", "professors": []}), encoding="utf-8")

    def test_imports_dedupes_and_is_idempotent(self):
        out = StringIO()
        call_command("import_professors", str(self.dir), stdout=out, stderr=StringIO())
        self.assertEqual(Professor.objects.filter(school=self.school, is_demo=False, status="approved").count(), 2)
        self.assertIn("новых 2, отброшено 1, дублей 1", out.getvalue())
        call_command("import_professors", str(self.dir), stdout=StringIO(), stderr=StringIO())
        self.assertEqual(Professor.objects.count(), 2)

    def test_dry_run_and_skip_initials(self):
        call_command("import_professors", str(self.dir), "--dry-run", stdout=StringIO(), stderr=StringIO())
        self.assertEqual(Professor.objects.count(), 0)
        call_command("import_professors", str(self.dir), "--skip-initials", stdout=StringIO(), stderr=StringIO())
        self.assertEqual(Professor.objects.count(), 1)


class PrepareProductionTests(TestCase):
    def test_wipes_content_but_keeps_schools_and_staff(self):
        school = School.objects.create(code="knu", name="КНУ", slug="knu", city="Бишкек")
        prof = Professor.objects.create(school=school, first_name="Анна", last_name="Ким", slug="anna-kim",
                                        department="Физика", title="доцент")
        User = get_user_model()
        user = User.objects.create_user("u@example.com", "u@example.com", "x")
        User.objects.create_superuser("a@example.com", "a@example.com", "x")
        Review.objects.create(professor=prof, course="Физика", overall=5, difficulty=3,
                              would_take_again=True, comment="x" * 30, author=user, status="approved")
        call_command("prepare_production", stdout=StringIO())
        self.assertEqual(Review.objects.count(), 1)
        call_command("prepare_production", "--yes", stdout=StringIO())
        self.assertEqual((Review.objects.count(), Professor.objects.count(), School.objects.count()), (0, 0, 1))
        self.assertEqual(list(User.objects.values_list("username", flat=True)), ["a@example.com"])
