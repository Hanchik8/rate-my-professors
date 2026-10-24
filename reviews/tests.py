import re
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import translation
from django.utils.formats import localize

from .repository import InMemoryRepository
from .seed import seed
from .store import repo as global_repo
from .django_repo import DjangoRepository

TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_CSS = Path(__file__).parent / "static" / "reviews" / "style.css"


def _valid(overrides=None):
    d = {"course": "Алгоритмы", "term": "Осень 2025", "overall": "4", "difficulty": "3",
         "would_take_again": "yes", "grade": "A", "tags": ["Интересные лекции"],
         "comment": "Понятные лекции и честные экзамены, рекомендую."}
    if overrides:
        d.update(overrides)
    return d


def _repo_review(course="Алгоритмы", overall=5, difficulty=3, wta=True, grade="A",
                 tags=None, comment="Тестовый отзыв достаточной длины."):
    """Cleaned-data shape for repository.add_review (ints, not form strings)."""
    return {"course": course, "term": "Осень 2025", "overall": overall,
            "difficulty": difficulty, "would_take_again": wta, "grade": grade,
            "comment": comment, "tags": tags or ["Интересные лекции"]}


class MemorySmokeTests(TestCase):
    """Smoke against InMemoryRepository (no DB) via isolated repo."""
    def setUp(self):
        # use isolated in-memory repo for predictable slugs
        from reviews import store as store_mod
        self.repo = InMemoryRepository()
        seed(self.repo)
        self._orig = store_mod.repo
        store_mod.repo = self.repo
        # also patch views' repo reference
        import reviews.views as v
        self._orig_v = v.repo
        v.repo = self.repo

    def tearDown(self):
        from reviews import store as store_mod
        import reviews.views as v
        store_mod.repo = self._orig
        v.repo = self._orig_v

    def test_home_and_search(self):
        self.assertContains(self.client.get(reverse("home")), "Айбек")
        r = self.client.get(reverse("home"), {"q": "физика"})
        self.assertContains(r, "Волков")
        self.assertNotContains(r, "Айбек")

    def test_filter_city_and_school(self):
        # filter by city Osh should show only Osh prof
        r = self.client.get(reverse("home"), {"city": "Ош"})
        self.assertContains(r, "Бакыт")
        self.assertNotContains(r, "Айбек")
        # filter by school slug
        school = next(s for s in self.repo.schools() if "Ошский" in s.name)
        r2 = self.client.get(reverse("home"), {"school": school.slug})
        self.assertContains(r2, "Бакыт")

    def test_professor_page_and_404(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        self.assertContains(self.client.get(reverse("professor", args=[prof.slug])), "Алгоритмы")
        self.assertEqual(self.client.get(reverse("professor", args=["nobody"])).status_code, 404)

    def test_post_review_requires_login_and_pending(self):
        # anonymous redirected to login
        prof = self.repo.search("Айбек")[0]["prof"]
        r = self.client.post(reverse("review_new", args=[prof.slug]), _valid())
        self.assertIn(r.status_code, (302, 200))
        # login and post
        user = User.objects.create_user(username="tester@example.com", email="tester@example.com", password="pass12345")
        self.client.force_login(user)
        r2 = self.client.post(reverse("review_new", args=[prof.slug]), _valid())
        self.assertEqual(r2.status_code, 302)
        # pending, not visible yet
        self.assertEqual(len(self.repo.reviews_for(prof.id)), 3)  # seed has 3 for first prof

    def test_vote_requires_login_and_one_vote(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        review = self.repo.reviews_for(prof.id)[0]
        # anonymous redirected
        r = self.client.post(reverse("review_vote", args=[review.id]), {"vote": "up"})
        self.assertIn(r.status_code, (302, 200))
        user = User.objects.create_user(username="voter@example.com", email="voter@example.com", password="pass12345")
        self.client.force_login(user)
        before = review.helpful
        r2 = self.client.post(reverse("review_vote", args=[review.id]), {"vote": "up"})
        self.assertEqual(r2.status_code, 302)
        self.assertEqual(review.helpful, before + 1)
        # second vote by same user not counted twice
        r3 = self.client.post(reverse("review_vote", args=[review.id]), {"vote": "up"})
        self.assertEqual(r3.status_code, 302)
        self.assertEqual(review.helpful, before + 1)

    def test_course_not_uppercased_and_max_80(self):
        user = User.objects.create_user(username="c@example.com", email="c@example.com", password="pass12345")
        self.client.force_login(user)
        prof = self.repo.search("Айбек")[0]["prof"]
        # course with mixed case preserved (trim only)
        self.client.post(reverse("review_new", args=[prof.slug]), _valid({"course": "  Микроэкономика  "}))
        # fetch pending review
        pending = [r for r in self.repo.reviews_for(prof.id, include_pending=True) if r.course == "Микроэкономика"]
        self.assertTrue(pending)

    def test_grades_include_kg_scale(self):
        from .repository import GRADES
        for g in ["A", "E", "FX", "F", "Зачёт", "Незачёт", "Ещё не знаю"]:
            self.assertIn(g, [str(x) for x in GRADES])

    def test_tags_no_corruption(self):
        from .repository import TAGS
        joined = " ".join(str(t) for t in TAGS).lower()
        self.assertNotIn("взят", joined)
        self.assertNotIn("корруп", joined)

    def test_i18n_languages(self):
        for lang in ["ru", "ky", "en"]:
            r = self.client.get(reverse("home"), HTTP_ACCEPT_LANGUAGE=lang)
            self.assertEqual(r.status_code, 200)

    def test_rules_page(self):
        self.assertContains(self.client.get(reverse("rules")), "Правила")

    def test_school_page(self):
        school = self.repo.schools()[0]
        r = self.client.get(reverse("school_detail", args=[school.slug]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, school.name)

    def test_add_professor_requires_login_and_duplicate_check(self):
        school = self.repo.schools()[0]
        r = self.client.get(reverse("add_professor"))
        # login required
        self.assertIn(r.status_code, (302, 200))
        user = User.objects.create_user(username="addp@example.com", email="addp@example.com", password="pass12345")
        self.client.force_login(user)
        r2 = self.client.get(reverse("add_professor"))
        self.assertEqual(r2.status_code, 200)
        # add new prof
        data = {"school": str(school.id), "first_name": "Тест", "last_name": "Тестов", "department": "Кафедра теста", "title": "доцент"}
        r3 = self.client.post(reverse("add_professor"), data)
        self.assertEqual(r3.status_code, 302)
        # duplicate
        r4 = self.client.post(reverse("add_professor"), data)
        self.assertEqual(r4.status_code, 200)


# Django ORM backend — same smoke with DB
class DjangoSmokeTests(TestCase):
    def setUp(self):
        from reviews import store as store_mod
        import reviews.views as v
        self.repo = DjangoRepository()
        # seed via models helper
        from reviews.management.commands.seed_kg import Command as SeedCmd
        cmd = SeedCmd()
        cmd.handle(clear=True)
        # use DjangoRepository for views
        self._orig = store_mod.repo
        self._orig_v = v.repo
        store_mod.repo = self.repo
        v.repo = self.repo

    def tearDown(self):
        from reviews import store as store_mod
        import reviews.views as v
        store_mod.repo = self._orig
        v.repo = self._orig_v

    def test_home_shows_kg_data(self):
        self.assertContains(self.client.get(reverse("home")), "Айбек")

    def test_review_pending_not_visible(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        user = User.objects.create_user(username="django_tester@example.com", email="django_tester@example.com", password="pass12345")
        self.client.force_login(user)
        before = len(self.repo.reviews_for(prof.id))
        self.client.post(reverse("review_new", args=[prof.slug]), _valid())
        self.assertEqual(len(self.repo.reviews_for(prof.id)), before)
        self.assertEqual(len(self.repo.reviews_for(prof.id, include_pending=True)), before + 1)


# ---------------------------------------------------------------------------
# Repository contract: identical API assertions run against BOTH backends
# ---------------------------------------------------------------------------
class RepositoryContractMixin:
    def _make(self):
        raise NotImplementedError

    def setUp(self):
        super().setUp()
        self.repo = self._make()

    def _school(self, name="Тестовый университет", city="Бишкек"):
        return self.repo.add_school(name, city)

    def _prof(self, school_id, first="Иван", last="Петров"):
        return self.repo.add_professor(school_id, first, last, "Физика", "доцент")

    def _user(self, email):
        return User.objects.create_user(username=email, email=email, password="pass12345")

    def test_schools_cities_and_lookup(self):
        s = self._school()
        self.assertIn(s, self.repo.schools())
        self.assertIn("Бишкек", self.repo.cities())
        self.assertEqual(self.repo.school_by_slug(s.slug).id, s.id)
        self.assertEqual(self.repo.school(s.id).name, s.name)
        self.assertIsNone(self.repo.school_by_slug("does-not-exist"))

    def test_add_professor_and_reads(self):
        s = self._school()
        p = self._prof(s.id)
        self.assertEqual(self.repo.professor(p.slug).id, p.id)
        self.assertEqual(self.repo.professor_by_id(p.id).full_name, "Иван Петров")
        self.assertEqual(self.repo.professor_any(p.slug).id, p.id)
        self.assertEqual([x.id for x in self.repo.professors_for_school(s.id)], [p.id])

    def test_duplicate_professor_rejected(self):
        s = self._school()
        self._prof(s.id)
        with self.assertRaises(ValueError):
            self.repo.add_professor(s.id, "Иван", "Петров", "Математика", "профессор")
        # same ФИО in a different school is allowed
        s2 = self._school("Другой вуз", "Ош")
        self.repo.add_professor(s2.id, "Иван", "Петров", "Физика", "доцент")

    def test_search_filters(self):
        s = self._school()
        p = self._prof(s.id)
        self.assertEqual(self.repo.stats(p.id)["count"], 0)
        self.assertEqual([x["prof"].id for x in self.repo.search("петров")], [p.id])
        self.assertEqual(self.repo.search("неттакого"), [])
        self.assertEqual(self.repo.search("", city="Ош"), [])
        self.assertEqual(len(self.repo.search("", city="Бишкек")), 1)
        self.assertEqual(len(self.repo.search("", school_slug=s.slug)), 1)

    def test_add_review_pending_then_approve_and_stats(self):
        s = self._school()
        p = self._prof(s.id)
        u = self._user("contract_r1@example.com")
        r = self.repo.add_review(p.id, _repo_review(), user=u)
        self.assertEqual(r.status, "pending")
        self.assertEqual(self.repo.reviews_for(p.id), [])
        self.assertEqual(len(self.repo.reviews_for(p.id, include_pending=True)), 1)
        self.repo.approve_review(r.id)
        self.assertEqual(len(self.repo.reviews_for(p.id)), 1)
        st = self.repo.stats(p.id)
        self.assertEqual(st["count"], 1)
        self.assertEqual(st["overall"], 5.0)
        self.assertEqual(st["difficulty"], 3.0)
        self.assertEqual(st["wta_pct"], 100)
        self.assertEqual(st["tone"], "good")
        self.assertIn("Интересные лекции", st["top_tags"])

    def test_anonymous_review_auto_approved(self):
        s = self._school()
        p = self._prof(s.id)
        r = self.repo.add_review(p.id, _repo_review(), user=None)
        self.assertEqual(r.status, "approved")
        self.assertEqual(len(self.repo.reviews_for(p.id)), 1)

    def test_duplicate_review_rejected(self):
        s = self._school()
        p = self._prof(s.id)
        u = self._user("contract_r2@example.com")
        self.repo.add_review(p.id, _repo_review(), user=u)
        with self.assertRaises(ValueError):
            self.repo.add_review(p.id, _repo_review(), user=u)

    def test_has_user_reviewed(self):
        s = self._school()
        p = self._prof(s.id)
        u = self._user("contract_r3@example.com")
        # ASCII course: SQLite LIKE folds case only for ASCII (Cyrillic is case-sensitive)
        self.assertFalse(self.repo.has_user_reviewed(p.id, "Algorithms", u))
        self.assertFalse(self.repo.has_user_reviewed(p.id, "Algorithms", None))
        self.repo.add_review(p.id, _repo_review(course="Algorithms"), user=u)
        self.assertTrue(self.repo.has_user_reviewed(p.id, "algorithms", u))
        self.assertFalse(self.repo.has_user_reviewed(p.id, "Other", u))

    def test_vote_once_and_counts(self):
        s = self._school()
        p = self._prof(s.id)
        u = self._user("contract_v1@example.com")
        r = self.repo.add_review(p.id, _repo_review(), status="approved")
        self.assertFalse(self.repo.has_user_voted(r.id, u))
        self.repo.vote(r.id, helpful=True, user=u)
        self.assertTrue(self.repo.has_user_voted(r.id, u))
        self.assertEqual(self.repo.review(r.id).helpful, 1)
        with self.assertRaises(ValueError):
            self.repo.vote(r.id, helpful=True, user=u)
        u2 = self._user("contract_v2@example.com")
        self.repo.vote(r.id, helpful=False, user=u2)
        self.assertEqual(self.repo.review(r.id).not_helpful, 1)
        self.assertEqual(self.repo.review(r.id).helpful, 1)

    def test_reviews_for_helpful_sort(self):
        s = self._school()
        p = self._prof(s.id)
        u = self._user("contract_s1@example.com")
        r1 = self.repo.add_review(p.id, _repo_review(course="Курс 1"), status="approved")
        self.repo.add_review(p.id, _repo_review(course="Курс 2"), status="approved")
        self.repo.vote(r1.id, helpful=True, user=u)
        ordered = self.repo.reviews_for(p.id, sort="helpful")
        self.assertEqual(ordered[0].id, r1.id)

    def test_report_counted(self):
        s = self._school()
        p = self._prof(s.id)
        u = self._user("contract_rep@example.com")
        r = self.repo.add_review(p.id, _repo_review(), status="approved")
        self.repo.report(r.id, user=u)
        self.assertEqual(self.repo.review(r.id).reported, 1)

    def test_school_stats(self):
        s = self._school()
        p = self._prof(s.id)
        self.repo.add_review(p.id, _repo_review(), status="approved")
        st = self.repo.school_stats(s.id)
        self.assertEqual(st["prof_count"], 1)
        self.assertEqual(st["review_count"], 1)
        self.assertEqual(st["avg_overall"], 5.0)

    def test_all_reviews_visibility(self):
        s = self._school()
        p = self._prof(s.id)
        u = self._user("contract_all@example.com")
        self.repo.add_review(p.id, _repo_review(course="Одобренный"), status="approved")
        self.repo.add_review(p.id, _repo_review(course="На модерации"), user=u)
        self.assertEqual(len(self.repo.all_reviews()), 1)
        self.assertEqual(len(self.repo.all_reviews(include_pending=True)), 2)

    def test_pending_professor_hidden_until_approved(self):
        s = self._school()
        p = self.repo.add_professor(s.id, "Пётр", "Скрытый", "Физика", "доцент", status="pending")
        self.assertIsNone(self.repo.professor(p.slug))
        self.assertIsNotNone(self.repo.professor_any(p.slug))
        self.assertEqual(self.repo.search("Скрытый"), [])
        self.repo.approve_professor(p.id)
        self.assertIsNotNone(self.repo.professor(p.slug))
        self.assertEqual(len(self.repo.search("Скрытый")), 1)


class MemoryRepositoryContractTests(RepositoryContractMixin, TestCase):
    def _make(self):
        return InMemoryRepository()


class DjangoRepositoryContractTests(RepositoryContractMixin, TestCase):
    def _make(self):
        return DjangoRepository()


# ---------------------------------------------------------------------------
# View coverage against InMemoryRepository
# ---------------------------------------------------------------------------
class _MemoryRepoTestCase(TestCase):
    def setUp(self):
        from reviews import store as store_mod
        import reviews.views as v
        self.repo = InMemoryRepository()
        seed(self.repo)
        self._orig = store_mod.repo
        self._orig_v = v.repo
        store_mod.repo = self.repo
        v.repo = self.repo

    def tearDown(self):
        from reviews import store as store_mod
        import reviews.views as v
        store_mod.repo = self._orig
        v.repo = self._orig_v

    def login(self, email="viewer@example.com"):
        user = User.objects.create_user(username=email, email=email, password="pass12345")
        self.client.force_login(user)
        return user

    def prof(self, q="Айбек"):
        return self.repo.search(q)[0]["prof"]


class HomeViewTests(_MemoryRepoTestCase):
    def test_home_lists_seed(self):
        r = self.client.get(reverse("home"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Айбек")
        self.assertContains(r, "Волков")

    def test_home_no_results_message(self):
        r = self.client.get(reverse("home"), {"q": "неттакого"})
        self.assertContains(r, "Ничего не нашлось")

    def test_home_pagination(self):
        r = self.client.get(reverse("home"))
        self.assertIsNotNone(r.context["page_obj"])
        self.assertEqual(r.context["page_obj"].paginator.num_pages, 2)
        r2 = self.client.get(reverse("home"), {"page": 2})
        self.assertEqual(r2.status_code, 200)
        self.assertLessEqual(len(r2.context["results"]), 10)


class SchoolViewTests(_MemoryRepoTestCase):
    def test_school_detail_stats_and_departments(self):
        school = next(s for s in self.repo.schools() if "Ошский" in s.name)
        r = self.client.get(reverse("school_detail", args=[school.slug]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, school.name)
        self.assertEqual(r.context["stats"]["prof_count"], 1)
        self.assertContains(r, "Бакыт")

    def test_school_detail_404(self):
        self.assertEqual(self.client.get(reverse("school_detail", args=["nope"])).status_code, 404)


class ProfessorViewTests(_MemoryRepoTestCase):
    def test_professor_detail_stats_and_sort(self):
        prof = self.prof()
        r = self.client.get(reverse("professor", args=[prof.slug]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["sort"], "newest")
        self.assertEqual(r.context["stats"]["count"], 3)
        r2 = self.client.get(reverse("professor", args=[prof.slug]), {"sort": "helpful"})
        self.assertEqual(r2.context["sort"], "helpful")
        self.assertContains(r2, "Алгоритмы")

    def test_professor_pending_review_not_shown(self):
        prof = self.prof()
        u = self.login()
        self.repo.add_review(prof.id, _repo_review(course="Скрытый курс", comment="Скрытый комментарий достаточной длины."), user=u)
        r = self.client.get(reverse("professor", args=[prof.slug]))
        self.assertNotContains(r, "Скрытый комментарий достаточной длины.")


class ReviewFormViewTests(_MemoryRepoTestCase):
    def test_anonymous_get_redirects_to_login(self):
        r = self.client.get(reverse("review_new", args=[self.prof().slug]))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/accounts/login/", r.url)

    def test_authenticated_get_renders_form(self):
        self.login()
        r = self.client.get(reverse("review_new", args=[self.prof().slug]))
        self.assertEqual(r.status_code, 200)
        self.assertIn("form", r.context)
        self.assertContains(r, "Отправить на модерацию")

    def test_invalid_comment_rejected(self):
        self.login()
        prof = self.prof()
        before = len(self.repo.reviews_for(prof.id, include_pending=True))
        r = self.client.post(reverse("review_new", args=[prof.slug]), _valid({"comment": "коротко"}))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context["form"].is_valid())
        self.assertEqual(len(self.repo.reviews_for(prof.id, include_pending=True)), before)

    def test_too_many_tags_rejected(self):
        self.login()
        prof = self.prof()
        tags = ["Строго оценивает", "Понятные критерии", "Интересные лекции", "Много домашних заданий"]
        r = self.client.post(reverse("review_new", args=[prof.slug]), _valid({"tags": tags}))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["form"].errors.get("tags"))

    def test_success_redirects_and_is_pending(self):
        self.login()
        prof = self.prof()
        r = self.client.post(reverse("review_new", args=[prof.slug]), _valid())
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("professor", args=[prof.slug]))
        pending = [x for x in self.repo.reviews_for(prof.id, include_pending=True)
                   if x.course == "Алгоритмы" and x.status == "pending"]
        self.assertEqual(len(pending), 1)

    def test_duplicate_course_shows_error(self):
        self.login()
        prof = self.prof()
        url = reverse("review_new", args=[prof.slug])
        self.client.post(url, _valid())
        r = self.client.post(url, _valid())
        self.assertEqual(r.status_code, 200)
        self.assertIn("course", r.context["form"].errors)
        pending = [x for x in self.repo.reviews_for(prof.id, include_pending=True)
                   if x.course == "Алгоритмы"]
        self.assertEqual(len(pending), 1)


class ReviewActionViewTests(_MemoryRepoTestCase):
    def test_vote_404(self):
        self.login()
        r = self.client.post(reverse("review_vote", args=["nope"]), {"vote": "up"})
        self.assertEqual(r.status_code, 404)

    def test_vote_redirects_and_increments(self):
        prof = self.prof()
        review = self.repo.reviews_for(prof.id)[0]
        self.login()
        before = review.helpful
        r = self.client.post(reverse("review_vote", args=[review.id]), {"vote": "up"})
        self.assertEqual(r.status_code, 302)
        self.assertIn(f"#review-{review.id}", r.url)
        self.assertEqual(review.helpful, before + 1)

    def test_report_creates_report(self):
        prof = self.prof()
        review = self.repo.reviews_for(prof.id)[0]
        self.login()
        r = self.client.post(reverse("review_report", args=[review.id]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(review.reported, 1)

    def test_report_404(self):
        self.login()
        r = self.client.post(reverse("review_report", args=["nope"]))
        self.assertEqual(r.status_code, 404)


class AddProfessorViewTests(_MemoryRepoTestCase):
    def _data(self, school):
        return {"school": str(school.id), "first_name": "Тест", "last_name": "Тестов",
                "department": "Кафедра теста", "title": "доцент"}

    def test_anonymous_redirects_to_login(self):
        r = self.client.get(reverse("add_professor"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("/accounts/login/", r.url)

    def test_invalid_form_rejected(self):
        self.login()
        r = self.client.post(reverse("add_professor"), {})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.context["form"].errors)

    def test_creates_pending_and_hidden_until_approved(self):
        self.login()
        school = self.repo.schools()[0]
        r = self.client.post(reverse("add_professor"), self._data(school))
        self.assertEqual(r.status_code, 302)
        pending = [p for p in self.repo._professors.values() if p.status == "pending"]
        self.assertEqual(len(pending), 1)
        p = pending[0]
        self.assertIsNone(self.repo.professor(p.slug))
        self.assertEqual(self.repo.search("Тестов"), [])
        self.repo.approve_professor(p.id)
        self.assertIsNotNone(self.repo.professor(p.slug))
        self.assertEqual(len(self.repo.search("Тестов")), 1)


# ---------------------------------------------------------------------------
# Auth / signup views
# ---------------------------------------------------------------------------
class AuthViewTests(TestCase):
    def test_signup_creates_user_and_logs_in(self):
        r = self.client.post(reverse("signup"), {
            "email": "new@example.com", "password1": "pass12345", "password2": "pass12345"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("home"))
        self.assertTrue(User.objects.filter(username="new@example.com").exists())
        self.assertIn("_auth_user_id", self.client.session)

    def test_signup_duplicate_email(self):
        User.objects.create_user(username="dup@example.com", email="dup@example.com", password="pass12345")
        r = self.client.post(reverse("signup"), {
            "email": "dup@example.com", "password1": "pass12345", "password2": "pass12345"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("email", r.context["form"].errors)

    def test_signup_password_mismatch(self):
        r = self.client.post(reverse("signup"), {
            "email": "x@example.com", "password1": "pass12345", "password2": "different1"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(email="x@example.com").exists())

    def test_signup_short_password(self):
        r = self.client.post(reverse("signup"), {
            "email": "y@example.com", "password1": "short", "password2": "short"})
        self.assertEqual(r.status_code, 200)

    def test_authenticated_signup_redirects_home(self):
        user = User.objects.create_user(username="here@example.com", email="here@example.com", password="pass12345")
        self.client.force_login(user)
        r = self.client.get(reverse("signup"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("home"))


# ---------------------------------------------------------------------------
# View + moderation coverage against DjangoRepository (ORM)
# ---------------------------------------------------------------------------
class DjangoViewCoverageTests(TestCase):
    def setUp(self):
        from reviews import store as store_mod
        import reviews.views as v
        self.repo = DjangoRepository()
        from reviews.management.commands.seed_kg import Command as SeedCmd
        SeedCmd().handle(clear=True)
        self._orig = store_mod.repo
        self._orig_v = v.repo
        store_mod.repo = self.repo
        v.repo = self.repo

    def tearDown(self):
        from reviews import store as store_mod
        import reviews.views as v
        store_mod.repo = self._orig
        v.repo = self._orig_v

    def login(self, email="dview@example.com"):
        user = User.objects.create_user(username=email, email=email, password="pass12345")
        self.client.force_login(user)
        return user

    def test_home_school_professor_pages(self):
        self.assertContains(self.client.get(reverse("home")), "Айбек")
        school = self.repo.schools()[0]
        self.assertEqual(self.client.get(reverse("school_detail", args=[school.slug])).status_code, 200)
        prof = self.repo.search("Айбек")[0]["prof"]
        r = self.client.get(reverse("professor", args=[prof.slug]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["stats"]["count"], 3)

    def test_review_pending_then_approved_visible(self):
        from reviews.models import Review
        prof = self.repo.search("Айбек")[0]["prof"]
        comment = "Понятные лекции и честные экзамены, рекомендую."
        self.login()
        self.client.post(reverse("review_new", args=[prof.slug]), _valid())
        pending = Review.objects.get(status="pending")
        self.assertNotContains(self.client.get(reverse("professor", args=[prof.slug])), comment)
        self.repo.approve_review(str(pending.pk))
        self.assertEqual(Review.objects.get(pk=pending.pk).status, "approved")
        self.assertContains(self.client.get(reverse("professor", args=[prof.slug])), comment)

    def test_add_professor_pending_then_approved(self):
        from reviews.models import Professor
        school = self.repo.schools()[0]
        self.login()
        data = {"school": str(school.id), "first_name": "Тест", "last_name": "Модератов",
                "department": "Кафедра", "title": "доцент"}
        r = self.client.post(reverse("add_professor"), data)
        self.assertEqual(r.status_code, 302)
        p = Professor.objects.get(status="pending")
        self.assertIsNone(self.repo.professor(p.slug))
        self.assertEqual(self.repo.search("Модератов"), [])
        self.assertNotContains(self.client.get(reverse("home")), "Модератов")
        self.repo.approve_professor(str(p.pk))
        self.assertIsNotNone(self.repo.professor(p.slug))
        self.assertContains(self.client.get(reverse("home"), {"q": "Модератов"}), "Модератов")

    def test_review_vote_and_report_flow(self):
        from reviews.models import Report
        prof = self.repo.search("Айбек")[0]["prof"]
        review = self.repo.reviews_for(prof.id)[0]
        self.login()
        r = self.client.post(reverse("review_vote", args=[review.id]), {"vote": "up"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.repo.review(review.id).helpful, 1)
        self.client.post(reverse("review_report", args=[review.id]))
        self.assertEqual(Report.objects.filter(review_id=review.id).count(), 1)


# ---------------------------------------------------------------------------
# Security settings hardening
# ---------------------------------------------------------------------------
class SecuritySettingsTests(TestCase):
    def test_x_frame_options_deny(self):
        from django.conf import settings
        self.assertEqual(settings.X_FRAME_OPTIONS, "DENY")

    def test_password_validators_configured(self):
        from django.conf import settings
        names = [v["NAME"] for v in settings.AUTH_PASSWORD_VALIDATORS]
        self.assertIn("django.contrib.auth.password_validation.MinimumLengthValidator", names)
        self.assertIn("django.contrib.auth.password_validation.CommonPasswordValidator", names)
        self.assertIn("django.contrib.auth.password_validation.NumericPasswordValidator", names)
        self.assertIn(
            "django.contrib.auth.password_validation.UserAttributeSimilarityValidator", names
        )

    def test_security_switches_off_when_debug(self):
        from config import settings as site
        sec = site._security_settings(debug=True)
        self.assertFalse(sec["SECURE_SSL_REDIRECT"])
        self.assertEqual(sec["SECURE_HSTS_SECONDS"], 0)
        self.assertFalse(sec["SECURE_HSTS_INCLUDE_SUBDOMAINS"])
        self.assertFalse(sec["SECURE_HSTS_PRELOAD"])
        self.assertFalse(sec["SESSION_COOKIE_SECURE"])
        self.assertFalse(sec["CSRF_COOKIE_SECURE"])
        self.assertIsNone(sec["SECURE_PROXY_SSL_HEADER"])

    def test_security_switches_on_in_production(self):
        from config import settings as site
        sec = site._security_settings(debug=False)
        self.assertTrue(sec["SECURE_SSL_REDIRECT"])
        self.assertGreater(sec["SECURE_HSTS_SECONDS"], 0)
        self.assertTrue(sec["SECURE_HSTS_INCLUDE_SUBDOMAINS"])
        self.assertTrue(sec["SECURE_HSTS_PRELOAD"])
        self.assertTrue(sec["SESSION_COOKIE_SECURE"])
        self.assertTrue(sec["CSRF_COOKIE_SECURE"])
        self.assertEqual(sec["SECURE_PROXY_SSL_HEADER"], ("HTTP_X_FORWARDED_PROTO", "https"))

    def test_nosniff_always_enabled(self):
        from config import settings as site
        self.assertTrue(site._security_settings(debug=True)["SECURE_CONTENT_TYPE_NOSNIFF"])
        self.assertTrue(site._security_settings(debug=False)["SECURE_CONTENT_TYPE_NOSNIFF"])

    def test_default_secret_key_rejected_in_production(self):
        from django.core.exceptions import ImproperlyConfigured
        from config import settings as site
        with self.assertRaises(ImproperlyConfigured):
            site._validate_secret_key(site.DEFAULT_SECRET_KEY, debug=False)

    def test_custom_secret_key_accepted_in_production(self):
        from config import settings as site
        # must not raise
        site._validate_secret_key("a-strong-unique-production-key", debug=False)

    def test_default_secret_key_allowed_in_debug(self):
        from config import settings as site
        site._validate_secret_key(site.DEFAULT_SECRET_KEY, debug=True)

    def test_current_secure_values_match_import_debug_flag(self):
        from config import settings as site
        # Module-level switches are derived at import from the DEBUG env value
        # (Django later forces settings.DEBUG=False for the test run).
        self.assertEqual(site.SECURE_SSL_REDIRECT, not site.DEBUG)
        self.assertEqual(site.SESSION_COOKIE_SECURE, not site.DEBUG)
        self.assertEqual(site.CSRF_COOKIE_SECURE, not site.DEBUG)


# ---------------------------------------------------------------------------
# UX design: responsive layout, professor cards, rating stars, a11y
# ---------------------------------------------------------------------------
class DesignAssetsTests(TestCase):
    """Static design assets: no external CDNs, responsive + a11y primitives."""

    def _templates(self):
        return [p for p in TEMPLATES_DIR.rglob("*.html")]

    def test_templates_have_no_external_resources(self):
        for path in self._templates():
            with self.subTest(template=path.name):
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"https?://")

    def test_css_has_no_external_urls(self):
        css = STATIC_CSS.read_text(encoding="utf-8")
        self.assertNotRegex(css, r"url\(\s*['\"]?https?://")
        self.assertNotIn("@import", css)
        self.assertNotIn("fonts.googleapis", css)

    def test_css_is_responsive_and_motion_safe(self):
        css = STATIC_CSS.read_text(encoding="utf-8")
        self.assertIn("@media", css)
        self.assertIn("prefers-reduced-motion", css)
        self.assertIn(":focus-visible", css)
        self.assertIn("color-scheme", css)  # declared in base.html meta + tokens


class DesignContrastTests(TestCase):
    """WCAG 2.1 AA contrast checks for the CSS design tokens."""

    @classmethod
    def _tokens(cls):
        css = STATIC_CSS.read_text(encoding="utf-8")
        root = re.search(r":root\s*\{([^}]*)\}", css).group(1)
        return dict(re.findall(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})", root))

    @staticmethod
    def _luminance(hex_color):
        def channel(v):
            v = v / 255
            return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)

    @classmethod
    def _ratio(cls, fg, bg):
        l1, l2 = sorted((cls._luminance(fg), cls._luminance(bg)), reverse=True)
        return (l1 + 0.05) / (l2 + 0.05)

    def test_text_pairs_meet_aa_4_5(self):
        t = self._tokens()
        pairs = [
            ("ink", "bg"), ("ink", "surface"),
            ("muted", "bg"), ("muted", "surface"),
            ("accent", "surface"), ("accent", "bg"),
            ("good-ink", "good-bg"), ("mid-ink", "mid-bg"),
            ("bad-ink", "bad-bg"), ("none-ink", "none-bg"),
        ]
        for fg, bg in pairs:
            with self.subTest(pair=f"{fg} on {bg}"):
                self.assertGreaterEqual(self._ratio(t[fg], t[bg]), 4.5)

    def test_star_graphic_meets_3_to_1(self):
        t = self._tokens()
        self.assertGreaterEqual(self._ratio(t["star"], t["surface"]), 3.0)

    def test_white_text_on_accent_button_meets_aa(self):
        t = self._tokens()
        self.assertGreaterEqual(self._ratio("#ffffff", t["accent"]), 4.5)
        self.assertGreaterEqual(self._ratio("#ffffff", t["accent-strong"]), 4.5)


class HeaderLayoutTests(_MemoryRepoTestCase):
    """Modern header: skip link, burger toggle, i18n language switch."""

    def test_header_has_skip_link_and_target(self):
        r = self.client.get(reverse("home"))
        self.assertContains(r, 'class="skip-link"')
        self.assertContains(r, 'href="#main-content"')
        self.assertContains(r, 'id="main-content"')

    def test_header_has_burger_toggle(self):
        r = self.client.get(reverse("home"))
        self.assertContains(r, 'class="nav-toggle"')
        self.assertContains(r, 'aria-expanded="false"')
        self.assertContains(r, 'aria-controls="site-nav"')
        self.assertContains(r, 'id="site-nav"')
        self.assertContains(r, 'aria-label="Меню"')
        # inline toggle script (no external JS)
        self.assertContains(r, "nav-toggle")

    def test_header_keeps_language_switch(self):
        r = self.client.get(reverse("home"))
        self.assertContains(r, 'name="language"')
        self.assertContains(r, 'aria-label="Язык"')

    def test_header_logged_in_shows_logout(self):
        self.login()
        r = self.client.get(reverse("home"))
        self.assertContains(r, "Выйти")
        self.assertNotContains(r, ">Регистрация</a>")


class ProfessorCardsTests(_MemoryRepoTestCase):
    """Professor list renders as cards with star ratings."""

    def test_home_renders_cards_with_stars(self):
        r = self.client.get(reverse("home"))
        self.assertContains(r, 'class="card"')
        self.assertContains(r, 'class="card-name"')
        self.assertContains(r, "★★★★★")
        self.assertContains(r, 'class="s-fill"')

    def test_home_card_star_aria_label_matches_rating(self):
        r = self.client.get(reverse("home"))
        first = r.context["results"][0]["stats"]
        with translation.override("ru"):
            self.assertContains(r, f'aria-label="Рейтинг {localize(first["overall"])} из 5"')
        self.assertContains(r, 'class="s-fill" aria-hidden="true" style="width:')

    def test_home_card_without_reviews_shows_empty_stars(self):
        school = self.repo.schools()[0]
        p = self.repo.add_professor(school.id, "Тихон", "Безотзывов", "Физика", "доцент")
        r = self.client.get(reverse("home"), {"q": "Безотзывов"})
        self.assertContains(r, 'aria-label="Нет оценок"')
        self.assertNotContains(r, 'class="s-fill"')

    def test_school_page_renders_cards_with_stars(self):
        school = self.repo.schools()[0]
        r = self.client.get(reverse("school_detail", args=[school.slug]))
        self.assertContains(r, 'class="card"')
        self.assertContains(r, "★★★★★")

    def test_professor_page_shows_stars(self):
        prof = self.prof()
        stats = self.repo.stats(prof.id)
        r = self.client.get(reverse("professor", args=[prof.slug]))
        self.assertContains(r, "★★★★★")
        with translation.override("ru"):
            self.assertContains(r, f'aria-label="Рейтинг {localize(stats["overall"])} из 5"')

    def test_professor_page_without_reviews_shows_empty_stars(self):
        school = self.repo.schools()[0]
        p = self.repo.add_professor(school.id, "Тихон", "Безотзывов", "Физика", "доцент")
        r = self.client.get(reverse("professor", args=[p.slug]))
        self.assertContains(r, 'aria-label="Нет оценок"')
