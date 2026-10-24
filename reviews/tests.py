import re
from pathlib import Path

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import translation
from django.utils.formats import localize

from .django_repo import DjangoRepository
from .repository import InMemoryRepository
from .seed import seed

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
        import reviews.views as v
        from reviews import store as store_mod
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
        data = {
            "school": str(school.id), "first_name": "Тест", "last_name": "Тестов",
            "department": "Кафедра теста", "title": "доцент",
        }
        r3 = self.client.post(reverse("add_professor"), data)
        self.assertEqual(r3.status_code, 302)
        # duplicate
        r4 = self.client.post(reverse("add_professor"), data)
        self.assertEqual(r4.status_code, 200)


# Django ORM backend — same smoke with DB
class DjangoSmokeTests(TestCase):
    def setUp(self):
        import reviews.views as v
        from reviews import store as store_mod
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
        import reviews.views as v
        from reviews import store as store_mod
        store_mod.repo = self._orig
        v.repo = self._orig_v

    def test_home_shows_kg_data(self):
        self.assertContains(self.client.get(reverse("home")), "Айбек")

    def test_review_pending_not_visible(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        user = User.objects.create_user(
            username="django_tester@example.com",
            email="django_tester@example.com",
            password="pass12345",
        )
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

    def test_search_department_filter_and_sort(self):
        s = self._school()
        p1 = self.repo.add_professor(s.id, "Иван", "Петров", "Физика", "доцент")
        p2 = self.repo.add_professor(s.id, "Пётр", "Сидоров", "Математика", "доцент")
        self.repo.add_review(p1.id, _repo_review(course="К1", overall=4), status="approved")
        self.repo.add_review(p1.id, _repo_review(course="К2", overall=4), status="approved")
        self.repo.add_review(p2.id, _repo_review(course="К3", overall=5), status="approved")
        # department filter
        self.assertEqual([x["prof"].id for x in self.repo.search("", department="Физика")], [p1.id])
        self.assertEqual([x["prof"].id for x in self.repo.search("", department="Математика")], [p2.id])
        # sort by review count: p1 (2 reviews) comes first
        by_reviews = self.repo.search("", sort="reviews")
        self.assertEqual(by_reviews[0]["prof"].id, p1.id)
        # sort by rating: p2 (overall 5) comes first
        by_rating = self.repo.search("", sort="rating")
        self.assertEqual(by_rating[0]["prof"].id, p2.id)
        self.assertIn("Физика", self.repo.departments())

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
        import reviews.views as v
        from reviews import store as store_mod
        self.repo = InMemoryRepository()
        seed(self.repo)
        self._orig = store_mod.repo
        self._orig_v = v.repo
        store_mod.repo = self.repo
        v.repo = self.repo

    def tearDown(self):
        import reviews.views as v
        from reviews import store as store_mod
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

    def test_home_department_filter(self):
        r = self.client.get(reverse("home"), {"department": "Информатика"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Айбек")
        self.assertContains(r, "Бакыт")
        self.assertNotContains(r, "Волков")
        self.assertIn("Информатика", r.context["departments"])

    def test_home_sort_by_reviews(self):
        r = self.client.get(reverse("home"), {"sort": "reviews"})
        self.assertEqual(r.context["sort"], "reviews")
        self.assertEqual(r.context["results"][0]["prof"].full_name, "Айбек Токтогулов")
        self.assertGreaterEqual(r.context["results"][0]["stats"]["count"],
                                r.context["results"][1]["stats"]["count"])

    def test_home_sort_defaults_and_invalid(self):
        self.assertEqual(self.client.get(reverse("home")).context["sort"], "rating")
        self.assertEqual(self.client.get(reverse("home"), {"sort": "bogus"}).context["sort"], "rating")

    def test_home_renders_department_and_sort_controls(self):
        r = self.client.get(reverse("home"))
        self.assertContains(r, 'name="department"')
        self.assertContains(r, 'name="sort"')
        self.assertContains(r, "По рейтингу")
        self.assertContains(r, "По числу отзывов")


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
        self.repo.add_review(
            prof.id,
            _repo_review(course="Скрытый курс", comment="Скрытый комментарий достаточной длины."),
            user=u,
        )
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
        import reviews.views as v
        from reviews import store as store_mod
        self.repo = DjangoRepository()
        from reviews.management.commands.seed_kg import Command as SeedCmd
        SeedCmd().handle(clear=True)
        self._orig = store_mod.repo
        self._orig_v = v.repo
        store_mod.repo = self.repo
        v.repo = self.repo

    def tearDown(self):
        import reviews.views as v
        from reviews import store as store_mod
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

    def test_css_supports_dark_color_scheme(self):
        css = STATIC_CSS.read_text(encoding="utf-8")
        self.assertIn("prefers-color-scheme:dark", css.replace(" ", ""))
        self.assertIn("color-scheme:lightdark", css.replace(" ", ""))
        # Dark block must re-declare the core tokens, not rely on light values.
        dark = re.search(r"prefers-color-scheme\s*:\s*dark[^{]*\{\s*:root\s*\{([^}]*)\}", css)
        self.assertIsNotNone(dark)
        for token in ("--bg:", "--surface:", "--ink:", "--muted:", "--accent:"):
            self.assertIn(token, dark.group(1))

    def test_base_template_declares_light_and_dark_color_scheme(self):
        html = (TEMPLATES_DIR / "reviews" / "base.html").read_text(encoding="utf-8")
        self.assertIn('<meta name="color-scheme" content="light dark">', html)

    def test_focus_visible_style_is_prominent(self):
        css = STATIC_CSS.read_text(encoding="utf-8")
        rule = re.search(r":focus-visible\{([^}]*)\}", css)
        self.assertIsNotNone(rule)
        body = rule.group(1)
        # 3px+ solid outline plus a soft ring via box-shadow, driven by tokens.
        self.assertRegex(body, r"outline:3px solid var\(--focus\)")
        self.assertIn("box-shadow:0 0 0 5px var(--focus-ring)", body)

    def test_css_has_form_error_state_styles(self):
        css = STATIC_CSS.read_text(encoding="utf-8")
        self.assertIn(".form-actions", css)
        self.assertIn(".has-error", css)
        self.assertIn(".errorlist.nonfield", css)

    def test_css_empty_card_spans_full_grid(self):
        css = STATIC_CSS.read_text(encoding="utf-8")
        self.assertRegex(css, r"\.cards\s+\.empty\s*\{[^}]*grid-column")


class DesignContrastTests(TestCase):
    """WCAG 2.1 AA contrast checks for the CSS design tokens."""

    @classmethod
    def _tokens(cls):
        css = STATIC_CSS.read_text(encoding="utf-8")
        root = re.search(r":root\s*\{([^}]*)\}", css).group(1)
        return dict(re.findall(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})", root))

    @classmethod
    def _dark_tokens(cls):
        css = STATIC_CSS.read_text(encoding="utf-8")
        dark = re.search(
            r"prefers-color-scheme\s*:\s*dark[^{]*\{\s*:root\s*\{([^}]*)\}", css
        )
        assert dark, "dark theme block with :root tokens not found in style.css"
        return dict(re.findall(r"--([a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})", dark.group(1)))

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
        self.assertGreaterEqual(self._ratio(t["on-accent"], t["accent"]), 4.5)
        self.assertGreaterEqual(self._ratio(t["on-accent"], t["accent-strong"]), 4.5)

    # --- Dark theme (prefers-color-scheme: dark) ---

    def test_dark_theme_redeclares_all_core_tokens(self):
        light, dark = self._tokens(), self._dark_tokens()
        core = {"bg", "surface", "ink", "muted", "line", "accent", "accent-strong",
                "on-accent", "good-bg", "good-ink", "mid-bg", "mid-ink",
                "bad-bg", "bad-ink", "none-bg", "none-ink", "star", "star-empty",
                "focus"}
        self.assertTrue(core.issubset(dark.keys()))
        for name in core:
            with self.subTest(token=name):
                self.assertNotEqual(light[name], dark[name])

    def test_dark_text_pairs_meet_aa_4_5(self):
        t = self._dark_tokens()
        pairs = [
            ("ink", "bg"), ("ink", "surface"),
            ("muted", "bg"), ("muted", "surface"),
            ("accent", "surface"), ("accent", "bg"),
            ("good-ink", "good-bg"), ("mid-ink", "mid-bg"),
            ("bad-ink", "bad-bg"), ("none-ink", "none-bg"),
        ]
        for fg, bg in pairs:
            with self.subTest(pair=f"dark {fg} on {bg}"):
                self.assertGreaterEqual(self._ratio(t[fg], t[bg]), 4.5)

    def test_dark_star_graphic_meets_3_to_1(self):
        t = self._dark_tokens()
        self.assertGreaterEqual(self._ratio(t["star"], t["surface"]), 3.0)

    def test_dark_button_text_on_accent_meets_aa(self):
        t = self._dark_tokens()
        self.assertGreaterEqual(self._ratio(t["on-accent"], t["accent"]), 4.5)
        self.assertGreaterEqual(self._ratio(t["on-accent"], t["accent-strong"]), 4.5)

    def test_focus_ring_visible_on_page_backgrounds(self):
        # Focus indicator is a non-text UI component: WCAG 1.4.11 needs >= 3:1
        # against the colors it sits on, in both themes.
        for name, tokens in (("light", self._tokens()), ("dark", self._dark_tokens())):
            for surface in ("bg", "surface"):
                with self.subTest(theme=name, surface=surface):
                    self.assertGreaterEqual(
                        self._ratio(tokens["focus"], tokens[surface]), 3.0
                    )


class MobileLayoutDesignTests(TestCase):
    """Mobile layout guards: 360px-safe professor page and review cards."""

    @staticmethod
    def _media_block(css, query):
        """Return the body of `@media (max-width:query){...}` (nested rules)."""
        marker = f"@media (max-width:{query})"
        start = css.find(marker)
        assert start != -1, f"media query {marker} not found in style.css"
        i = css.index("{", start)
        depth = 0
        for j in range(i, len(css)):
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
                if depth == 0:
                    return css[i + 1:j]
        raise AssertionError(f"unbalanced braces after {marker}")

    def test_mobile_breakpoints_cover_360px_phones(self):
        css = STATIC_CSS.read_text(encoding="utf-8")
        # 26rem = 416px, so the small-phone block also matches 360px viewports.
        self.assertIn("@media (max-width:26rem)", css)
        self.assertIn("@media (max-width:50rem)", css)

    def test_review_cards_stack_single_column_on_phones(self):
        block = self._media_block(STATIC_CSS.read_text(encoding="utf-8"), "26rem")
        self.assertRegex(block, r"\.review\{[^}]*grid-template-columns:1fr")

    def test_professor_cards_single_column_on_narrow_screens(self):
        block = self._media_block(STATIC_CSS.read_text(encoding="utf-8"), "50rem")
        self.assertRegex(block, r"\.cards\{[^}]*grid-template-columns:1fr")

    def test_no_horizontal_scroll_guards(self):
        css = STATIC_CSS.read_text(encoding="utf-8")
        self.assertIn("overflow-x:clip", css)  # page-level safety net
        for selector in (".review", ".headline", ".card-body"):
            with self.subTest(selector=selector):
                rule = re.search(re.escape(selector) + r"\{([^}]*)\}", css)
                self.assertIsNotNone(rule)
                self.assertIn("overflow-wrap:break-word", rule.group(1))
        # Grid/flex children must be allowed to shrink below content width.
        self.assertIn(".review>div{min-width:0}", css)
        self.assertIn(".headline>div{min-width:0}", css)

    def test_pagination_and_vote_forms_wrap_on_mobile(self):
        css = STATIC_CSS.read_text(encoding="utf-8")
        for selector in (".pagination", ".votes", ".votes form"):
            with self.subTest(selector=selector):
                rule = re.search(re.escape(selector) + r"\{([^}]*)\}", css)
                self.assertIsNotNone(rule)
                self.assertIn("flex-wrap:wrap", rule.group(1))

    def test_form_controls_have_persistent_focus_border(self):
        css = STATIC_CSS.read_text(encoding="utf-8")
        rule = re.search(r"input:focus,select:focus,textarea:focus\{([^}]*)\}", css)
        self.assertIsNotNone(rule)
        self.assertIn("border-color:var(--focus)", rule.group(1))

    def test_focus_outline_fallback_without_focus_visible_support(self):
        css = STATIC_CSS.read_text(encoding="utf-8")
        fallback = re.search(
            r"@supports not selector\(:focus-visible\)\{\s*:focus\{([^}]*)\}", css
        )
        self.assertIsNotNone(fallback)
        self.assertIn("outline:3px solid var(--focus)", fallback.group(1))

    def test_choice_chips_promote_focus_ring_to_whole_label(self):
        css = STATIC_CSS.read_text(encoding="utf-8")
        rule = re.search(r"\.choices label:has\(input:focus-visible\)\{([^}]*)\}", css)
        self.assertIsNotNone(rule)
        self.assertIn("outline:3px solid var(--focus)", rule.group(1))


class ProfessorMobileMarkupTests(_MemoryRepoTestCase):
    """Professor page markup that the mobile CSS hooks onto (reviews, votes)."""

    def test_professor_page_renders_review_card_structure(self):
        prof = self.prof()
        r = self.client.get(reverse("professor", args=[prof.slug]))
        self.assertContains(r, 'class="headline"')
        self.assertContains(r, 'class="review" id="review-')
        self.assertContains(r, 'class="votes"')
        self.assertContains(r, 'class="facts-line"')

    def test_professor_page_uses_shared_stylesheet_and_viewport_meta(self):
        prof = self.prof()
        r = self.client.get(reverse("professor", args=[prof.slug]))
        self.assertContains(r, "reviews/style.css")
        self.assertContains(r, 'name="viewport" content="width=device-width, initial-scale=1"')


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
        self.repo.add_professor(school.id, "Тихон", "Безотзывов", "Физика", "доцент")
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


class FormStatesDesignTests(_MemoryRepoTestCase):
    """UX: unified form markup, visible error states (field + non-field)."""

    def test_review_form_uses_shared_field_markup_and_actions(self):
        self.login()
        r = self.client.get(reverse("review_new", args=[self.prof().slug]))
        self.assertContains(r, 'class="form-actions"')
        self.assertContains(r, 'class="cancel"')
        self.assertContains(r, 'class="req"')  # required marker on obligatory fields

    def test_review_form_marks_invalid_fields(self):
        self.login()
        prof = self.prof()
        r = self.client.post(reverse("review_new", args=[prof.slug]), _valid({"comment": "коротко"}))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "has-error")
        self.assertContains(r, "errorlist")

    def test_add_professor_duplicate_error_is_visible(self):
        # Non-field errors must render: duplicate-professor rejection
        # is attached via form.add_error(None, ...).
        self.login()
        school = self.repo.schools()[0]
        data = {"school": str(school.id), "first_name": "Тест", "last_name": "Тестов",
                "department": "Кафедра теста", "title": "доцент"}
        self.assertEqual(self.client.post(reverse("add_professor"), data).status_code, 302)
        r = self.client.post(reverse("add_professor"), data)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "уже есть в этом вузе")
        self.assertContains(r, "errorlist nonfield")

    def test_login_uses_unified_fields_and_shows_nonfield_error(self):
        r = self.client.get(reverse("login"))
        self.assertContains(r, 'class="field"')
        User.objects.create_user(username="u@example.com", email="u@example.com", password="pass12345")
        r2 = self.client.post(reverse("login"), {"username": "u@example.com", "password": "wrongpass1"})
        self.assertEqual(r2.status_code, 200)
        self.assertContains(r2, "errorlist nonfield")

    def test_signup_uses_unified_fields(self):
        r = self.client.get(reverse("signup"))
        self.assertContains(r, 'class="field"')
        self.assertContains(r, 'class="form-actions"')


class LanguageSwitchTests(TestCase):
    """POST /i18n/setlang/ changes the language the templates render in."""

    def _switch(self, code):
        return self.client.post(
            reverse("set_language"), {"language": code, "next": reverse("home")}
        )

    def test_default_language_is_russian(self):
        r = self.client.get(reverse("home"))
        self.assertContains(r, "Правила")
        self.assertContains(r, 'lang="ru"')

    def test_switch_to_english_then_back_to_russian(self):
        self.assertEqual(self._switch("en").status_code, 302)
        r = self.client.get(reverse("home"))
        self.assertContains(r, "Rules")
        self.assertContains(r, "Add professor")
        self.assertNotContains(r, "Правила")
        self.assertContains(r, 'lang="en"')
        # switch back
        self._switch("ru")
        r2 = self.client.get(reverse("home"))
        self.assertContains(r2, "Правила")
        self.assertNotContains(r2, "Rules")

    def test_switch_to_kyrgyz(self):
        self.assertEqual(self._switch("ky").status_code, 302)
        r = self.client.get(reverse("home"))
        self.assertContains(r, "Эрежелер")
        self.assertContains(r, "Окутуучу кошуу")
        self.assertContains(r, 'lang="ky"')

    def test_invalid_language_falls_back_to_default(self):
        self._switch("de")
        r = self.client.get(reverse("home"))
        self.assertContains(r, "Правила")

    def test_404_page_renders_in_selected_language(self):
        self._switch("en")
        r = self.client.get("/definitely-not-a-real-page/")
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, "Page not found", status_code=404)
        self.assertNotContains(r, "Страница не найдена", status_code=404)
        self._switch("ky")
        r2 = self.client.get("/definitely-not-a-real-page/")
        self.assertContains(r2, "Барак табылган жок", status_code=404)


class CatalogTranslationTests(TestCase):
    """Previously untranslated views/forms/error-page strings now resolve."""

    def test_error_page_strings(self):
        with translation.override("en"):
            self.assertEqual(translation.gettext("Страница не найдена"), "Page not found")
            self.assertEqual(translation.gettext("Ошибка сервера"), "Server error")
            self.assertEqual(translation.gettext("Вернуться на главную"), "Back to home")
        with translation.override("ky"):
            self.assertEqual(translation.gettext("Страница не найдена"), "Барак табылган жок")
            self.assertEqual(translation.gettext("Ошибка сервера"), "Сервер катасы")

    def test_form_length_validation_messages(self):
        with translation.override("en"):
            self.assertEqual(
                translation.gettext("Отзыв должен содержать не менее %(n)d символов.") % {"n": 5},
                "The review must contain at least 5 characters.",
            )
            self.assertEqual(
                translation.gettext("Отзыв должен содержать не более %(n)d символов.") % {"n": 900},
                "The review must not exceed 900 characters.",
            )

    def test_duplicate_review_message_uses_current_source_string(self):
        with translation.override("en"):
            self.assertEqual(
                translation.gettext("Вы уже оставляли отзыв по этому предмету у этого преподавателя."),
                "You have already left a review for this subject with this professor.",
            )

    def test_admin_action_labels_are_translated(self):
        with translation.override("en"):
            self.assertEqual(translation.gettext("ФИО"), "Full name")
            self.assertEqual(
                translation.gettext("Одобрить выбранных преподавателей"),
                "Approve selected professors",
            )
            self.assertEqual(
                translation.gettext("Отклонить выбранные отзывы"),
                "Reject selected reviews",
            )

    def test_view_not_found_messages_are_translated(self):
        with translation.override("ky"):
            self.assertEqual(translation.gettext("Professor not found"), "Окутуучу табылган жок")
            self.assertEqual(translation.gettext("School not found"), "ЖОЖ табылган жок")
            self.assertEqual(translation.gettext("Review not found"), "Сын-пикир табылган жок")


# ---------------------------------------------------------------------------
# Anti-duplication / anti-race: DB constraints + atomic votes
# ---------------------------------------------------------------------------
class ReviewDeduplicationTests(TestCase):
    """One review per (professor, course, user) and one vote per (review, user)."""

    def setUp(self):
        import reviews.views as v
        from reviews import store as store_mod
        self.repo = DjangoRepository()
        from reviews.management.commands.seed_kg import Command as SeedCmd
        SeedCmd().handle(clear=True)
        self._orig = store_mod.repo
        self._orig_v = v.repo
        store_mod.repo = self.repo
        v.repo = self.repo

    def tearDown(self):
        import reviews.views as v
        from reviews import store as store_mod
        store_mod.repo = self._orig
        v.repo = self._orig_v

    def _user(self, email):
        return User.objects.create_user(username=email, email=email, password="pass12345")

    def _prof(self):
        return self.repo.search("Айбек")[0]["prof"]

    def test_models_declare_named_unique_constraints(self):
        from .models import Report, Review, Vote
        self.assertIn("uniq_review_prof_author_course", {c.name for c in Review._meta.constraints})
        self.assertIn("uniq_vote_review_user", {c.name for c in Vote._meta.constraints})
        self.assertIn("uniq_report_review_user", {c.name for c in Report._meta.constraints})

    def test_duplicate_review_blocked_by_db_constraint(self):
        from django.db import IntegrityError, transaction

        from .models import Review
        prof = self._prof()
        u = self._user("dedup@example.com")
        self.repo.add_review(prof.id, _repo_review(course="Algorithms"), user=u)
        # Bypass repository guard: the DB constraint must reject the duplicate.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Review.objects.create(
                    professor_id=prof.id, course="algorithms", overall=4, difficulty=3,
                    would_take_again=True, comment="Достаточно длинный тестовый комментарий.",
                    status="pending", author=u,
                )

    def test_anonymous_reviews_are_not_constrained(self):
        from .models import Review
        prof = self._prof()
        Review.objects.create(
            professor_id=prof.id, course="Алгоритмы и структуры данных", overall=5, difficulty=3,
            would_take_again=True, comment="Анонимный отзыв.", status="approved", author=None,
        )
        self.assertGreaterEqual(
            Review.objects.filter(
                professor_id=prof.id, course="Алгоритмы и структуры данных", author__isnull=True
            ).count(),
            2,
        )

    def test_vote_is_unique_per_user_and_counted_once(self):
        from django.db import IntegrityError, transaction

        from .models import Vote
        prof = self._prof()
        review = self.repo.reviews_for(prof.id)[0]
        u = self._user("atomic_vote@example.com")
        self.repo.vote(review.id, helpful=True, user=u)
        self.assertEqual(self.repo.review(review.id).helpful, 1)
        with self.assertRaises(ValueError):
            self.repo.vote(review.id, helpful=True, user=u)
        self.assertEqual(self.repo.review(review.id).helpful, 1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Vote.objects.create(review_id=review.id, user=u, helpful=True)

    def test_duplicate_review_view_shows_message(self):
        from .models import Review
        prof = self._prof()
        u = self._user("dupview@example.com")
        self.client.force_login(u)
        url = reverse("review_new", args=[prof.slug])
        self.assertEqual(self.client.post(url, _valid()).status_code, 302)
        r = self.client.post(url, _valid())
        self.assertEqual(r.status_code, 200)
        self.assertIn("course", r.context["form"].errors)
        self.assertEqual(Review.objects.filter(professor_id=prof.id, course="Алгоритмы", author=u).count(), 1)


# ---------------------------------------------------------------------------
# Pagination of professor lists and review lists
# ---------------------------------------------------------------------------
class PaginationTests(_MemoryRepoTestCase):
    """Professor lists (school page) and review lists (professor page) paginate."""

    def test_school_page_paginates_professors(self):
        school = self.repo.schools()[0]
        for i in range(12):
            self.repo.add_professor(school.id, f"Пагин{i}", f"Тестов{i}", "Кафедра", "доцент")
        r = self.client.get(reverse("school_detail", args=[school.slug]))
        self.assertIsNotNone(r.context["page_obj"])
        self.assertEqual(r.context["page_obj"].paginator.num_pages, 2)
        self.assertLessEqual(len(r.context["results"]), 10)
        r2 = self.client.get(reverse("school_detail", args=[school.slug]), {"page": 2})
        self.assertEqual(r2.status_code, 200)
        self.assertLessEqual(len(r2.context["results"]), 10)

    def test_school_single_page_has_no_widget(self):
        school = next(s for s in self.repo.schools() if "Ошский" in s.name)
        r = self.client.get(reverse("school_detail", args=[school.slug]))
        self.assertIsNone(r.context["page_obj"])

    def test_professor_page_paginates_reviews(self):
        prof = self.prof()
        for i in range(12):
            self.repo.add_review(prof.id, _repo_review(course=f"Пагин{i}"), status="approved")
        r = self.client.get(reverse("professor", args=[prof.slug]))
        self.assertIsNotNone(r.context["page_obj"])
        self.assertEqual(r.context["page_obj"].paginator.num_pages, 2)
        self.assertLessEqual(len(r.context["reviews"]), 10)
        r2 = self.client.get(reverse("professor", args=[prof.slug]), {"page": 2})
        self.assertEqual(r2.status_code, 200)
        self.assertLessEqual(len(r2.context["reviews"]), 10)


# ---------------------------------------------------------------------------
# Performance: no N+1 queries in DjangoRepository list pages
# ---------------------------------------------------------------------------
class QueryEfficiencyTests(TestCase):
    """DjangoRepository uses select_related/prefetch_related/annotate.

    Each read path must run a constant number of queries regardless of how
    many professors/reviews exist.
    """

    def setUp(self):
        import reviews.views as v
        from reviews import store as store_mod
        self.repo = DjangoRepository()
        from reviews.management.commands.seed_kg import Command as SeedCmd
        SeedCmd().handle(clear=True)
        self._orig = store_mod.repo
        self._orig_v = v.repo
        store_mod.repo = self.repo
        v.repo = self.repo

    def tearDown(self):
        import reviews.views as v
        from reviews import store as store_mod
        store_mod.repo = self._orig
        v.repo = self._orig_v

    def _add_load(self, professors=8, reviews_each=3):
        school = self.repo.schools()[0]
        for i in range(professors):
            p = self.repo.add_professor(school.id, f"Нагруз{i}", f"Проф{i}", "Кафедра", "доцент")
            for j in range(reviews_each):
                self.repo.add_review(p.id, _repo_review(course=f"Курс {i}-{j}"), status="approved")

    def test_search_query_count_is_constant(self):
        with self.assertNumQueries(4):
            self.repo.search()
        self._add_load()
        with self.assertNumQueries(4):
            self.repo.search()

    def test_stats_query_count_is_constant(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        with self.assertNumQueries(3):
            self.repo.stats(prof.id)
        for i in range(10):
            self.repo.add_review(prof.id, _repo_review(course=f"Ещё {i}"), status="approved")
        with self.assertNumQueries(3):
            self.repo.stats(prof.id)

    def test_reviews_for_prefetches_tags(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        with self.assertNumQueries(2):
            self.repo.reviews_for(prof.id)
        for i in range(10):
            self.repo.add_review(prof.id, _repo_review(course=f"Тег {i}"), status="approved")
        with self.assertNumQueries(2):
            self.repo.reviews_for(prof.id)

    def test_professor_detail_reads_use_select_related(self):
        """Detail-page reads join school in one query (no per-professor lookup)."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        prof = self.repo.search("Айбек")[0]["prof"]
        for read in (
            lambda: self.repo.professor(prof.slug),
            lambda: self.repo.professor_any(prof.slug),
            lambda: self.repo.professor_by_id(prof.id),
        ):
            with self.assertNumQueries(1):
                read()
            with CaptureQueriesContext(connection) as ctx:
                read()
            self.assertEqual(len(ctx.captured_queries), 1)
            sql = ctx.captured_queries[0]["sql"].lower()
            self.assertIn("join", sql)
            self.assertIn("school", sql)

    def test_school_stats_query_count_is_constant(self):
        school = self.repo.schools()[0]
        with self.assertNumQueries(4):
            self.repo.school_stats(school.id)
        self._add_load()
        with self.assertNumQueries(4):
            self.repo.school_stats(school.id)

    def test_home_view_query_count_is_constant(self):
        self.client.get(reverse("home"))
        with self.assertNumQueries(7):
            self.client.get(reverse("home"))
        self._add_load()
        with self.assertNumQueries(7):
            self.client.get(reverse("home"))

    def test_professor_view_query_count_is_constant(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        self.client.get(reverse("professor", args=[prof.slug]))
        with self.assertNumQueries(7):
            self.client.get(reverse("professor", args=[prof.slug]))
        for i in range(12):
            self.repo.add_review(prof.id, _repo_review(course=f"Отзыв {i}"), status="approved")
        with self.assertNumQueries(7):
            self.client.get(reverse("professor", args=[prof.slug]))

    def test_school_view_query_count_is_constant(self):
        school = self.repo.schools()[0]
        self.client.get(reverse("school_detail", args=[school.slug]))
        with self.assertNumQueries(9):
            self.client.get(reverse("school_detail", args=[school.slug]))
        self._add_load()
        with self.assertNumQueries(9):
            self.client.get(reverse("school_detail", args=[school.slug]))


# ---------------------------------------------------------------------------
# Health endpoint and custom error pages
# ---------------------------------------------------------------------------
class HealthEndpointTests(TestCase):
    def test_health_returns_json_ok(self):
        r = self.client.get(reverse("health"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/json")
        self.assertJSONEqual(r.content, {"status": "ok"})


class ErrorPageTests(TestCase):
    def test_404_uses_custom_template(self):
        r = self.client.get("/definitely-not-a-real-page/")
        self.assertEqual(r.status_code, 404)
        self.assertTemplateUsed(r, "404.html")
        self.assertContains(r, "Страница не найдена", status_code=404)
        self.assertContains(r, "Вернуться на главную", status_code=404)

    def test_500_uses_custom_template(self):
        from django.test import RequestFactory
        from django.views.defaults import server_error
        request = RequestFactory().get("/boom/")
        r = server_error(request)
        self.assertEqual(r.status_code, 500)
        self.assertIn("Ошибка сервера", r.content.decode())

    def test_error_templates_extend_base(self):
        for name in ("404.html", "500.html"):
            with self.subTest(template=name):
                text = (TEMPLATES_DIR / name).read_text(encoding="utf-8")
                self.assertIn('extends "reviews/base.html"', text)


# ---------------------------------------------------------------------------
# Security: review-text sanitisation (control chars + length)
# ---------------------------------------------------------------------------
class TextSanitisationTests(TestCase):
    def test_clean_text_strips_control_chars_and_normalises_newlines(self):
        from .sanitize import clean_text
        dirty = "  Первая\x00 строка\x07\r\nВторая\tстрока\x1b  "
        cleaned = clean_text(dirty)
        self.assertEqual(cleaned, "Первая строка\nВторая\tстрока")
        self.assertFalse(any(ord(ch) < 32 and ch not in "\n\t" for ch in cleaned))

    def test_comment_field_length_matches_shared_constant(self):
        from .forms import ReviewForm
        from .sanitize import MAX_COMMENT_LENGTH, MIN_COMMENT_LENGTH
        field = ReviewForm().fields["comment"]
        self.assertEqual(field.max_length, MAX_COMMENT_LENGTH)
        self.assertEqual(field.min_length, MIN_COMMENT_LENGTH)

    def test_model_comment_has_max_length(self):
        from .models import Review
        from .sanitize import MAX_COMMENT_LENGTH
        self.assertEqual(Review._meta.get_field("comment").max_length, MAX_COMMENT_LENGTH)

    def test_form_strips_control_chars_from_comment(self):
        from .forms import ReviewForm
        data = _valid({"comment": "Хороший курс\x07 с примерами\x1b и практикой."})
        form = ReviewForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertNotIn("\x07", form.cleaned_data["comment"])
        self.assertNotIn("\x1b", form.cleaned_data["comment"])

    def test_form_rejects_null_byte(self):
        # Django's ProhibitNullCharactersValidator rejects NUL outright; that is
        # even stricter than stripping, so the payload must never reach storage.
        from .forms import ReviewForm
        form = ReviewForm(_valid({"comment": "Нормальный отзыв\x00 с нулевым байтом."}))
        self.assertFalse(form.is_valid())
        self.assertIn("comment", form.errors)

    def test_form_strips_control_chars_from_course_and_term(self):
        from .forms import ReviewForm
        form = ReviewForm(_valid({"course": "Ал\x07горитмы", "term": "Осен\x1bь 2025"}))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["course"], "Алгоритмы")
        self.assertEqual(form.cleaned_data["term"], "Осень 2025")

    def test_form_rejects_overlong_comment(self):
        from .forms import ReviewForm
        from .sanitize import MAX_COMMENT_LENGTH
        form = ReviewForm(_valid({"comment": "я" * (MAX_COMMENT_LENGTH + 1)}))
        self.assertFalse(form.is_valid())
        self.assertIn("comment", form.errors)

    def test_form_rejects_comment_too_short_after_cleaning(self):
        from .forms import ReviewForm
        from .sanitize import MIN_COMMENT_LENGTH
        # 19 visible chars + padding controls pass the raw min_length check
        form = ReviewForm(_valid({"comment": "х" * (MIN_COMMENT_LENGTH - 1) + "\x07\x07"}))
        self.assertFalse(form.is_valid())
        self.assertIn("comment", form.errors)

    def test_repository_strips_control_chars(self):
        repo = InMemoryRepository()
        school = repo.add_school("Тестовый вуз", "Бишкек")
        prof = repo.add_professor(school.id, "Иван", "Петров", "Физика", "доцент")
        review = repo.add_review(prof.id, _repo_review(comment="Курс с\x00 примерами и практикой."))
        self.assertNotIn("\x00", review.comment)

    def test_repository_rejects_overlong_comment(self):
        from .sanitize import MAX_COMMENT_LENGTH
        repo = InMemoryRepository()
        school = repo.add_school("Тестовый вуз", "Бишкек")
        prof = repo.add_professor(school.id, "Иван", "Петров", "Физика", "доцент")
        with self.assertRaises(ValueError):
            repo.add_review(
                prof.id,
                _repo_review(course="Другой курс", comment="я" * (MAX_COMMENT_LENGTH + 1)),
            )


# ---------------------------------------------------------------------------
# Security: XSS — user text must be HTML-escaped, never rendered raw
# ---------------------------------------------------------------------------
class ReviewEscapingTests(_MemoryRepoTestCase):
    def test_comment_is_html_escaped_on_professor_page(self):
        prof = self.prof()
        payload = '<script>alert("xss")</script> и ещё текст'
        self.repo.add_review(prof.id, _repo_review(comment=payload), status="approved")
        r = self.client.get(reverse("professor", args=[prof.slug]))
        self.assertNotContains(r, payload)
        self.assertContains(r, "&lt;script&gt;alert")

    def test_course_is_html_escaped_on_professor_page(self):
        prof = self.prof()
        self.repo.add_review(prof.id, _repo_review(course="<img src=x onerror=alert(1)>"), status="approved")
        r = self.client.get(reverse("professor", args=[prof.slug]))
        self.assertNotContains(r, "<img src=x onerror=alert(1)>")
        self.assertContains(r, "&lt;img")

    def test_search_query_is_html_escaped(self):
        payload = "<script>alert(1)</script>"
        r = self.client.get(reverse("home"), {"q": payload})
        self.assertNotContains(r, payload)


# ---------------------------------------------------------------------------
# Security: CSRF — state-changing endpoints require a valid token
# ---------------------------------------------------------------------------
class CSRFProtectionTests(_MemoryRepoTestCase):
    def _csrf_client_with_user(self, email="csrf@example.com"):
        user = User.objects.create_user(username=email, email=email, password="pass12345")
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        return client

    def test_vote_without_csrf_token_is_rejected(self):
        review = self.repo.reviews_for(self.prof().id)[0]
        client = self._csrf_client_with_user()
        r = client.post(reverse("review_vote", args=[review.id]), {"vote": "up"})
        self.assertEqual(r.status_code, 403)

    def test_report_without_csrf_token_is_rejected(self):
        review = self.repo.reviews_for(self.prof().id)[0]
        client = self._csrf_client_with_user()
        r = client.post(reverse("review_report", args=[review.id]))
        self.assertEqual(r.status_code, 403)

    def test_post_only_view_rejects_get(self):
        review = self.repo.reviews_for(self.prof().id)[0]
        self.login()
        r = self.client.get(reverse("review_vote", args=[review.id]))
        self.assertEqual(r.status_code, 405)

    def test_review_form_renders_csrf_token(self):
        self.login()
        r = self.client.get(reverse("review_new", args=[self.prof().slug]))
        self.assertContains(r, "csrfmiddlewaretoken")


# ---------------------------------------------------------------------------
# Security: open redirect — the `next` parameter must stay on this host
# ---------------------------------------------------------------------------
class OpenRedirectTests(TestCase):
    def _user(self):
        return User.objects.create_user(
            username="redir@example.com", email="redir@example.com", password="pass12345",
        )

    def test_login_rejects_absolute_external_next(self):
        self._user()
        r = self.client.post(reverse("login"), {
            "username": "redir@example.com", "password": "pass12345",
            "next": "https://evil.example.com/phishing",
        })
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("evil.example.com", r.url)
        self.assertEqual(r.url, reverse("home"))

    def test_login_rejects_protocol_relative_next(self):
        self._user()
        r = self.client.post(reverse("login"), {
            "username": "redir@example.com", "password": "pass12345",
            "next": "//evil.example.com/x",
        })
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("evil.example.com", r.url)

    def test_login_allows_same_host_next(self):
        self._user()
        r = self.client.post(reverse("login"), {
            "username": "redir@example.com", "password": "pass12345",
            "next": reverse("rules"),
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("rules"))

    def test_login_page_does_not_render_unsafe_next(self):
        r = self.client.get(reverse("login"), {"next": "https://evil.example.com"})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('value="https://evil.example.com"', r.content.decode())

    def test_set_language_rejects_external_next(self):
        r = self.client.post(reverse("set_language"), {
            "language": "en", "next": "https://evil.example.com/phishing",
        })
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("evil.example.com", r.url)

    def test_set_language_allows_same_host_next(self):
        r = self.client.post(reverse("set_language"), {
            "language": "en", "next": reverse("rules"),
        })
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("rules"), r.url)
