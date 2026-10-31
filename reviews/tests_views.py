"""View-level tests: search edges, shared helpers and HTTP method security."""
from types import SimpleNamespace

from django import forms
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .django_repo import DjangoRepository
from .forms import ReviewForm
from .repository import InMemoryRepository
from .seed import seed
from .tests import _MemoryRepoTestCase, _repo_review, _valid
from .views import (
    SafeLogoutView,
    ThrottledLoginView,
    _auth_success_url,
    _is_author,
    _is_valid_post,
    _requested_next_url,
    _review_form_context,
)


# ---------------------------------------------------------------------------
# Search / filter / sort contract: identical assertions for BOTH backends
# ---------------------------------------------------------------------------
class SearchEdgeContractMixin:
    def _make(self):
        raise NotImplementedError

    def setUp(self):
        super().setUp()
        self.repo = self._make()
        self.s = self.repo.add_school("Тестовый университет", "Бишкек")
        self.p1 = self.repo.add_professor(self.s.id, "Иван", "Петров", "Физика", "доцент")
        self.p2 = self.repo.add_professor(self.s.id, "Пётр", "Сидоров", "Математика", "доцент")
        self.repo.add_review(self.p1.id, _repo_review(course="К1", overall=3), status="approved")
        self.repo.add_review(self.p1.id, _repo_review(course="К2", overall=3), status="approved")
        self.repo.add_review(self.p2.id, _repo_review(course="К3", overall=5), status="approved")

    def _ids(self, **kwargs):
        return [x["prof"].id for x in self.repo.search(**kwargs)]

    def test_whitespace_only_query_returns_everything(self):
        self.assertEqual(sorted(self._ids(q="   ")), sorted([self.p1.id, self.p2.id]))

    def test_empty_filters_return_everything(self):
        self.assertEqual(sorted(self._ids(q="", city="", school_slug="", department="")),
                         sorted([self.p1.id, self.p2.id]))

    def test_query_is_case_insensitive_and_matches_department(self):
        self.assertEqual(self._ids(q="петров"), [self.p1.id])
        self.assertEqual(self._ids(q="ПЕТРОВ"), [self.p1.id])
        # "Физика" is the department of p1, not part of the name
        self.assertEqual(self._ids(q="физика"), [self.p1.id])

    def test_department_filter_ignores_surrounding_whitespace(self):
        self.assertEqual(self._ids(department="  Физика  "), [self.p1.id])
        self.assertEqual(self._ids(department="Физика"), [self.p1.id])

    def test_unknown_filter_values_return_empty(self):
        self.assertEqual(self._ids(q="такого-нет"), [])
        self.assertEqual(self._ids(city="Атлантида"), [])
        self.assertEqual(self._ids(school_slug="no-such-school"), [])
        self.assertEqual(self._ids(department="Несуществующая"), [])

    def test_conflicting_filters_return_empty(self):
        # school belongs to Бишкек, so asking for another city must yield nothing
        self.assertEqual(self._ids(school_slug=self.s.slug, city="Ош"), [])

    def test_sort_invalid_falls_back_to_rating(self):
        top = self.repo.search("", sort="bogus")[0]
        self.assertEqual(top["prof"].id, self.p2.id)  # overall 5 > 3

    def test_sort_rating_orders_by_overall_desc(self):
        rated = self.repo.search("", sort="rating")
        self.assertEqual(rated[0]["prof"].id, self.p2.id)
        self.assertGreaterEqual(rated[0]["stats"]["overall"], rated[1]["stats"]["overall"])

    def test_sort_reviews_orders_by_count_desc(self):
        by_reviews = self.repo.search("", sort="reviews")
        self.assertEqual(by_reviews[0]["prof"].id, self.p1.id)  # 2 reviews > 1
        self.assertGreaterEqual(by_reviews[0]["stats"]["count"], by_reviews[1]["stats"]["count"])

    def test_pending_professor_never_leaks_through_filters(self):
        pending = self.repo.add_professor(self.s.id, "Скрытый", "Профессор", "Физика", "доцент",
                                          status="pending")
        self.assertNotIn(pending.id, self._ids())
        self.assertNotIn(pending.id, self._ids(department="Физика"))
        self.assertNotIn(pending.id, self._ids(city="Бишкек"))
        self.assertNotIn(pending.id, self._ids(q="Скрытый"))


class MemorySearchEdgeTests(SearchEdgeContractMixin, TestCase):
    def _make(self):
        return InMemoryRepository()


class DjangoSearchEdgeTests(SearchEdgeContractMixin, TestCase):
    def _make(self):
        return DjangoRepository()


# ---------------------------------------------------------------------------
# View-level search/filter/sort edge cases (seeded in-memory data)
# ---------------------------------------------------------------------------
class HomeSearchEdgeViewTests(_MemoryRepoTestCase):
    def test_whitespace_only_query_lists_everyone(self):
        r = self.client.get(reverse("home"), {"q": "   "})
        self.assertContains(r, "Айбек")
        self.assertContains(r, "Волков")

    def test_unknown_city_shows_empty_state(self):
        r = self.client.get(reverse("home"), {"city": "Атлантида"})
        self.assertContains(r, "Ничего не нашлось")

    def test_empty_filters_list_all(self):
        r = self.client.get(reverse("home"), {"q": "", "city": "", "school": "", "department": ""})
        self.assertContains(r, "Айбек")

    def test_page_out_of_range_returns_last_page(self):
        r = self.client.get(reverse("home"), {"page": "999"})
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(len(r.context["results"]), 10)

    def test_non_numeric_page_falls_back_to_first(self):
        r = self.client.get(reverse("home"), {"page": "abc"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["results"])

    def test_negative_page_falls_back_to_first(self):
        r = self.client.get(reverse("home"), {"page": "-3"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["results"])

    def test_combined_city_and_department_filter(self):
        r = self.client.get(reverse("home"), {"city": "Бишкек", "department": "Информатика"})
        self.assertContains(r, "Айбек")
        self.assertNotContains(r, "Бакыт")  # Ош

    def test_conflicting_school_and_city_is_empty(self):
        school = next(s for s in self.repo.schools() if "Ошский" in s.name)
        r = self.client.get(reverse("home"), {"school": school.slug, "city": "Бишкек"})
        self.assertContains(r, "Ничего не нашлось")

    def test_sort_by_reviews_ignores_invalid_and_keeps_rating(self):
        self.assertEqual(
            self.client.get(reverse("home"), {"sort": "nonsense"}).context["sort"], "rating"
        )


# ---------------------------------------------------------------------------
# Form validation edge cases: empty form, whitespace and enum choices
# (rating and length boundaries are covered in tests_reviews.py)
# ---------------------------------------------------------------------------
class ReviewFormValidationEdgeTests(TestCase):
    def test_empty_form_reports_required_fields(self):
        form = ReviewForm({})
        self.assertFalse(form.is_valid())
        for field in ("course", "overall", "difficulty", "would_take_again", "comment"):
            self.assertIn(field, form.errors)

    def test_whitespace_only_course_is_rejected(self):
        form = ReviewForm(_valid({"course": "   "}))
        self.assertFalse(form.is_valid())
        self.assertIn("course", form.errors)

    def test_boundary_lengths_are_accepted(self):
        form = ReviewForm(_valid({"course": "я" * 80, "term": "я" * 20, "comment": "я" * 1000}))
        self.assertTrue(form.is_valid(), form.errors)

    def test_invalid_enum_choices_are_rejected(self):
        for overrides in ({"grade": "Z"}, {"would_take_again": "maybe"}, {"tags": ["Нет такого тега"]}):
            with self.subTest(**overrides):
                form = ReviewForm(_valid(overrides))
                self.assertFalse(form.is_valid())
                self.assertIn(list(overrides)[0], form.errors)


class ProfessorFormValidationEdgeTests(TestCase):
    class _School:
        def __init__(self, id, name):
            self.id = id
            self.name = name

    def _form(self, data):
        from .forms import ProfessorForm
        return ProfessorForm(data, schools=[self._School("1", "Вуз")])

    def test_empty_form_reports_required_fields(self):
        form = self._form({})
        self.assertFalse(form.is_valid())
        for field in ("school", "first_name", "last_name", "department", "title"):
            self.assertIn(field, form.errors)

    def test_invalid_school_is_rejected(self):
        form = self._form({"school": "999", "first_name": "Иван", "last_name": "Петров",
                           "department": "Физика", "title": "доцент"})
        self.assertFalse(form.is_valid())
        self.assertIn("school", form.errors)

    def test_invalid_title_is_rejected(self):
        form = self._form({"school": "1", "first_name": "Иван", "last_name": "Петров",
                           "department": "Физика", "title": "ректор"})
        self.assertFalse(form.is_valid())
        self.assertIn("title", form.errors)

    def test_overlong_names_and_department_are_rejected(self):
        form = self._form({"school": "1", "first_name": "я" * 41, "last_name": "Петров",
                           "department": "Физика", "title": "доцент"})
        self.assertFalse(form.is_valid())
        self.assertIn("first_name", form.errors)
        form2 = self._form({"school": "1", "first_name": "Иван", "last_name": "Петров",
                            "department": "я" * 81, "title": "доцент"})
        self.assertFalse(form2.is_valid())
        self.assertIn("department", form2.errors)


class ReportFormValidationTests(TestCase):
    def test_reason_is_bounded_by_model_max_length(self):
        from .forms import ReportForm
        from .models import Report

        max_length = Report._meta.get_field("reason").max_length
        valid = ReportForm({"reason": "spam"})
        self.assertTrue(valid.is_valid(), valid.errors)

        oversized = ReportForm({"reason": "x" * (max_length + 1)})
        self.assertFalse(oversized.is_valid())
        self.assertIn("reason", oversized.errors)
        self.assertEqual(ReportForm().fields["reason"].widget.attrs["maxlength"], max_length)


# ---------------------------------------------------------------------------
# Shared helpers used by the HTTP views
# ---------------------------------------------------------------------------
class _SampleForm(forms.Form):
    name = forms.CharField()


class IsAuthorTests(SimpleTestCase):
    def test_matching_ids_are_compared_as_strings(self):
        review = SimpleNamespace(author_id=7)
        self.assertTrue(_is_author(review, SimpleNamespace(id="7")))

    def test_different_ids_are_not_the_author(self):
        review = SimpleNamespace(author_id=7)
        self.assertFalse(_is_author(review, SimpleNamespace(id=8)))

    def test_missing_author_is_never_the_author(self):
        review = SimpleNamespace(author_id=None)
        self.assertFalse(_is_author(review, SimpleNamespace(id=None)))
        self.assertFalse(_is_author(review, SimpleNamespace(id=7)))


class IsValidPostTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_get_request_is_not_a_valid_post(self):
        request = self.factory.get("/")
        self.assertFalse(_is_valid_post(request, _SampleForm()))

    def test_valid_post_is_accepted(self):
        request = self.factory.post("/", {"name": "ok"})
        self.assertTrue(_is_valid_post(request, _SampleForm(request.POST)))

    def test_invalid_post_is_rejected(self):
        request = self.factory.post("/", {})
        self.assertFalse(_is_valid_post(request, _SampleForm(request.POST)))


class RequestedNextUrlTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_post_next_takes_precedence_over_get_next(self):
        request = self.factory.post("/?next=/from-get", {"next": "/from-post"})

        self.assertEqual(_requested_next_url(request), "/from-post")

    def test_safe_get_next_is_used_when_post_next_is_missing(self):
        request = self.factory.get("/?next=/from-get")

        self.assertEqual(_requested_next_url(request), "/from-get")

    def test_external_next_is_rejected(self):
        request = self.factory.get("/?next=https://evil.example/")

        self.assertIsNone(_requested_next_url(request))


class AuthSuccessUrlTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(LOGIN_REDIRECT_URL="/after-login/")
    def test_login_uses_safe_next_or_login_default(self):
        view = ThrottledLoginView()
        view.request = self.factory.get("/?next=/requested/")
        self.assertEqual(view.get_success_url(), "/requested/")
        view.request = self.factory.get("/?next=https://evil.example/")
        self.assertEqual(view.get_success_url(), "/after-login/")

    @override_settings(LOGOUT_REDIRECT_URL="/after-logout/")
    def test_logout_uses_its_configured_default(self):
        view = SafeLogoutView()
        view.request = self.factory.get("/")
        self.assertEqual(view.get_success_url(), "/after-logout/")

    @override_settings(LOGIN_REDIRECT_URL="/fallback/")
    def test_helper_resolves_the_configured_default(self):
        request = self.factory.get("/")
        self.assertEqual(_auth_success_url(request, settings.LOGIN_REDIRECT_URL), "/fallback/")


class ReviewFormContextTests(SimpleTestCase):
    def setUp(self):
        self.prof = SimpleNamespace(slug="prof")
        self.form = _SampleForm()

    def test_new_review_context_includes_account_urls(self):
        context = _review_form_context(self.prof, self.form)

        self.assertEqual(context["url"], reverse("rules"))
        self.assertEqual(context["login_url"], reverse("login"))
        self.assertEqual(context["signup_url"], reverse("signup"))
        self.assertNotIn("editing", context)

    def test_edit_review_context_marks_editing_and_omits_account_urls(self):
        context = _review_form_context(self.prof, self.form, editing=True)

        self.assertEqual(context["url"], reverse("rules"))
        self.assertTrue(context["editing"])
        self.assertNotIn("login_url", context)
        self.assertNotIn("signup_url", context)


# ---------------------------------------------------------------------------
# HTTP method restrictions and CSRF enforcement for state-changing views
# ---------------------------------------------------------------------------
class ViewMethodSecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        import reviews.views as views
        from reviews import store

        self.repo = InMemoryRepository()
        seed(self.repo)
        self._orig_repo = store.repo
        self._orig_view_repo = views.repo
        store.repo = self.repo
        views.repo = self.repo
        self.prof = self.repo.search("Айбек")[0]["prof"]
        self.review = self.repo.reviews_for(self.prof.id)[0]
        self.user = User.objects.create_user(
            username="methods@example.com",
            email="methods@example.com",
            password="pass12345",
        )

    def tearDown(self):
        import reviews.views as views
        from reviews import store

        store.repo = self._orig_repo
        views.repo = self._orig_view_repo

    def _owned_review(self):
        self.repo.add_review(
            self.prof.id,
            {
                "course": "Курс для проверки методов",
                "term": "Осень 2025",
                "overall": 4,
                "difficulty": 3,
                "would_take_again": True,
                "grade": "A",
                "tags": [],
                "comment": "Достаточно содержательный комментарий для проверки методов.",
            },
            user=self.user,
        )
        return self.repo.review(self.repo.reviews_for_user(self.user)[0]["review"].id)

    def test_post_only_views_reject_get(self):
        urls = [
            reverse("review_vote", args=[self.review.id]),
            reverse("review_report", args=[self.review.id]),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = Client().get(url)
                self.assertEqual(response.status_code, 405)

    def test_form_views_reject_unsupported_methods(self):
        owned_review = self._owned_review()
        self.client.force_login(self.user)
        urls = [
            reverse("review_new", args=[self.prof.slug]),
            reverse("review_edit", args=[owned_review.id]),
            reverse("review_delete", args=[owned_review.id]),
            reverse("add_professor"),
            reverse("signup"),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.put(url)
                self.assertEqual(response.status_code, 405)

    def test_state_changing_views_reject_missing_csrf_token(self):
        owned_review = self._owned_review()
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        urls = [
            reverse("review_new", args=[self.prof.slug]),
            reverse("review_edit", args=[owned_review.id]),
            reverse("review_delete", args=[owned_review.id]),
            reverse("review_vote", args=[self.review.id]),
            reverse("review_report", args=[self.review.id]),
            reverse("add_professor"),
            reverse("signup"),
            reverse("login"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(client.post(url, {}).status_code, 403)