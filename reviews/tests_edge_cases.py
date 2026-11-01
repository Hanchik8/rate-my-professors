"""Edge cases and defensive branches not reached by the scenario tests."""
import uuid
from unittest import mock

from django.contrib import admin
from django.contrib.auth.models import User
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from . import email_verification, throttle, view_helpers, views
from .admin import ProfessorAdmin, ReportAdmin
from .constants import MAX_COMMENT_LENGTH
from .django_repo import DjangoRepository
from .forms import ProfessorForm, _ensure_length
from .models import EmailVerification, Professor, Report, Review, School, Tag
from .repository import InMemoryRepository
from .templatetags.pagination import pagination_pages


def _request(path="/", **extra):
    request = RequestFactory().get(path, **extra)
    request.session = {}
    request._messages = FallbackStorage(request)
    request.user = mock.Mock(is_authenticated=True)
    return request


class ThrottleEdgeTests(TestCase):
    def test_client_ip_uses_first_forwarded_hop(self):
        request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="1.2.3.4, 5.6.7.8")
        self.assertEqual(throttle._client_ip(request), "1.2.3.4")

    @override_settings(RATELIMIT_ENABLE=True, RATELIMIT={"x": (1, 60)})
    def test_counter_expired_between_add_and_incr_starts_new_window(self):
        fake_cache = mock.Mock()
        fake_cache.add.return_value = False
        fake_cache.incr.side_effect = ValueError
        with mock.patch.object(throttle, "cache", fake_cache):
            self.assertFalse(throttle.is_rate_limited(RequestFactory().get("/"), "x"))
        fake_cache.set.assert_called_once()


class ViewEdgeTests(TestCase):
    def test_compare_treats_repo_lookup_errors_as_not_found(self):
        fake_repo = mock.Mock()
        fake_repo.professor_by_id.side_effect = ValidationError("bad id")
        ids = f"{uuid.uuid4()},{uuid.uuid4()}"
        with mock.patch.object(views, "repo", fake_repo):
            response = self.client.get(reverse("compare"), {"ids": ids})
        self.assertEqual(response.status_code, 404)

    def _save_with_error(self, error):
        form = mock.Mock(cleaned_data={"course": "Алгебра"})
        fake_repo = mock.Mock()
        fake_repo.has_user_reviewed.return_value = False
        fake_repo.add_review.side_effect = error
        with mock.patch.object(views, "repo", fake_repo):
            saved = views._save_review(form, mock.Mock(id="p1"), _request())
        self.assertFalse(saved)
        return form

    def test_save_review_race_duplicate_is_attached_to_course(self):
        form = self._save_with_error(ValueError("duplicate review"))
        self.assertEqual(form.add_error.call_args[0][0], "course")

    def test_save_review_other_repo_error_is_a_form_error(self):
        form = self._save_with_error(ValueError("boom"))
        form.add_error.assert_called_once_with(None, "boom")

    def test_resend_reports_failed_delivery(self):
        request = _request()
        result = email_verification.ResendResult(sent=True, delivered=False)
        with mock.patch.object(email_verification, "resend_code", return_value=result), \
                mock.patch.object(views, "_email_delivery_failed") as failed:
            response = views._handle_resend(request, mock.Mock(email="a@example.com"))
        failed.assert_called_once_with(request)
        self.assertEqual(response.status_code, 302)

    def test_verify_page_redirects_signed_in_user_home(self):
        self.client.force_login(User.objects.create_user("u@example.com", "u@example.com", "pass12345"))
        response = self.client.get(reverse("signup_verify"))
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)

    def test_redirect_to_review_without_professor_goes_home(self):
        fake_repo = mock.Mock()
        fake_repo.professor_by_id.return_value = None
        response = view_helpers._redirect_to_review(fake_repo, mock.Mock(id="r1", professor_id="p1"))
        self.assertEqual(response.url, reverse("home"))


class DjangoRepoEdgeTests(TestCase):
    def setUp(self):
        self.repo = DjangoRepository()
        self.school = self.repo.add_school("Тестовый вуз", "Бишкек")
        self.prof = self.repo.add_professor(self.school.id, "Иван", "Петров", "Математика", "доцент")
        self.data = {"course": "Алгебра", "overall": 5, "difficulty": 3, "would_take_again": True}

    def test_same_school_name_gets_unique_slug(self):
        other = self.repo.add_school("Тестовый вуз", "Ош")
        self.assertEqual(other.slug, f"{self.school.slug}-1")

    def test_too_long_comment_is_rejected(self):
        with self.assertRaises(ValueError):
            self.repo.add_review(self.prof.id, {**self.data, "comment": "a" * (MAX_COMMENT_LENGTH + 1)})

    def test_integrity_error_becomes_duplicate(self):
        with mock.patch.object(Review.objects, "create", side_effect=IntegrityError):
            with self.assertRaisesMessage(ValueError, "duplicate"):
                self.repo.add_review(self.prof.id, {**self.data, "comment": "ok"})

    def test_missing_lookups_return_none(self):
        missing = str(uuid.uuid4())
        self.assertIsNone(self.repo.school(missing))
        self.assertIsNone(self.repo.professor_any("no-such-slug"))
        self.assertIsNone(self.repo.professor_by_id(missing))

    def test_school_stats_without_professors_or_reviews(self):
        empty = self.repo.add_school("Пустой вуз", "Нарын")
        self.assertEqual(self.repo.school_stats(empty.id)["prof_count"], 0)
        stats = self.repo.school_stats(self.school.id)
        self.assertEqual((stats["prof_count"], stats["review_count"]), (1, 0))

    def test_anonymous_user_has_not_voted(self):
        self.assertFalse(self.repo.has_user_voted("any", None))


class MemoryRepoEdgeTests(TestCase):
    def test_defensive_branches(self):
        repo = InMemoryRepository()
        self.assertIsNone(repo.report("missing"))
        self.assertFalse(repo.has_user_voted("any", None))
        empty = repo.add_school("Пустой вуз", "Нарын")
        self.assertEqual(repo.school_stats(empty.id)["prof_count"], 0)


class SmallHelperTests(TestCase):
    def test_pagination_falls_back_on_bad_radius(self):
        page = mock.Mock(number=1)
        page.paginator.num_pages = 3
        self.assertEqual(pagination_pages(page, "wide"), [1, 2, 3])

    def test_ensure_length_rejects_too_long(self):
        with self.assertRaisesMessage(ValidationError, "long 3"):
            _ensure_length("abcdef", 1, 3, "short %(n)d", "long %(n)d")

    def test_professor_form_rejects_control_characters_only(self):
        form = ProfessorForm(data={
            "school": "s1", "first_name": "\x01\x02", "last_name": "Петров",
            "department": "Математика", "title": "доцент",
        }, schools=[mock.Mock(id="s1", name="Вуз")])
        self.assertFalse(form.is_valid())
        self.assertIn("first_name", form.errors)

    def test_seconds_until_resend_without_record(self):
        self.assertEqual(email_verification.seconds_until_resend(None), 0)

    def test_check_code_locks_after_too_many_attempts(self):
        user = User.objects.create_user("v@example.com", "v@example.com", "pass12345", is_active=False)
        email_verification.issue_code(user)
        EmailVerification.objects.filter(user=user).update(attempts=email_verification.max_attempts())
        self.assertEqual(email_verification.check_code(user, "000000"), email_verification.LOCKED)


class ModelAndAdminEdgeTests(TestCase):
    def test_model_slugs_and_str(self):
        school = School(name="Новый вуз", city="Бишкек")
        school.save()
        self.assertTrue(school.slug)
        self.assertEqual(str(Tag(name="строгий")), "строгий")
        first = Professor.objects.create(school=school, first_name="Анна", last_name="Ким",
                                         department="Физика", title="доцент")
        other = School.objects.create(name="Другой вуз", city="Ош")
        second = Professor.objects.create(school=other, first_name="Анна", last_name="Ким",
                                          department="Химия", title="доцент")
        self.assertEqual(second.slug, f"{first.slug}-1")
        self.assertIn("EmailVerification", str(EmailVerification(user_id=7)))

    def test_admin_bulk_actions(self):
        school = School.objects.create(name="Админ вуз", city="Бишкек")
        prof = Professor.objects.create(school=school, first_name="Б", last_name="В",
                                        department="Д", title="доцент", status="pending")
        ProfessorAdmin(Professor, admin.site).approve_selected(None, Professor.objects.all())
        prof.refresh_from_db()
        self.assertEqual(prof.status, "approved")
        user = User.objects.create_user("r@example.com")
        review = Review.objects.create(professor=prof, course="К", overall=4, difficulty=2,
                                       would_take_again=True, comment="ok")
        report = Report.objects.create(review=review, user=user)
        ReportAdmin(Report, admin.site).mark_reviewed(None, Report.objects.all())
        report.refresh_from_db()
        self.assertEqual(report.status, Report.STATUS_REVIEWED)


class ContactAndNameValidationTests(TestCase):
    def _review(self, comment):
        from .forms import ReviewForm
        form = ReviewForm()
        data = {"course": "Алгебра", "term": "", "overall": "5", "difficulty": "3",
                "would_take_again": "yes", "grade": "", "tags": [], "comment": comment}
        return ReviewForm(data=data)

    def test_comment_with_contacts_is_rejected(self):
        for comment in ("Пишите мне на qa@mail.ru, всё расскажу подробно",
                        "Звоните +996 555 123 456, расскажу про экзамен",
                        "Все ответы лежат на сайте answers.kg, заходите",
                        "Ссылка https://example.org на конспекты лекций"):
            with self.subTest(comment=comment):
                form = self._review(comment)
                self.assertFalse(form.is_valid())
                self.assertIn("comment", form.errors)

    def test_ordinary_comment_with_years_and_times_is_accepted(self):
        form = self._review("Учебный год 2025-2026, экзамен в 9:00, т.е. рано, но честно.")
        self.assertTrue(form.is_valid(), form.errors)

    def test_professor_names_must_be_letters(self):
        base = {"school": "s1", "department": "Математика", "title": "доцент"}
        schools = [mock.Mock(id="s1", name="Вуз")]
        for first, last, valid in (("Анна-Мария", "О’Нил", True), ("Иван3", "Петров", False),
                                   ("Иван", "http://x", False)):
            with self.subTest(first=first, last=last):
                form = ProfessorForm(data={**base, "first_name": first, "last_name": last}, schools=schools)
                self.assertEqual(form.is_valid(), valid, form.errors)


class LoginFormLabelTests(TestCase):
    def test_login_asks_for_email_not_username(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, 'type="email"')
        self.assertNotContains(response, "Имя пользователя")


class EmptySearchResetLinkTests(TestCase):
    def test_empty_search_shows_a_single_reset_link(self):
        response = self.client.get(reverse("home"), {"q": "zzqxнетакого"})
        self.assertEqual(response.content.decode().count("Сбросить поиск"), 1)
