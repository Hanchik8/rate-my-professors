from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from .repository import InMemoryRepository
from .seed import seed
from .store import repo as global_repo
from .django_repo import DjangoRepository


def _valid(overrides=None):
    d = {"course": "Алгоритмы", "term": "Осень 2025", "overall": "4", "difficulty": "3",
         "would_take_again": "yes", "grade": "A", "tags": ["Интересные лекции"],
         "comment": "Понятные лекции и честные экзамены, рекомендую."}
    if overrides:
        d.update(overrides)
    return d


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

    def test_filter_department(self):
        # seeded Физика: Дмитрий Волков; Информатика: Айбек Токтогулов and Бакыт Маматов
        r = self.client.get(reverse("home"), {"department": "Физика"})
        self.assertContains(r, "Волков")
        self.assertNotContains(r, "Айбек")
        self.assertNotContains(r, "Бакыт")
        self.assertContains(r, 'name="department"')
        self.assertContains(r, 'selected>Физика')
        # case-insensitive + surrounding whitespace
        r_ci = self.client.get(reverse("home"), {"department": "  физика  "})
        self.assertContains(r_ci, "Волков")
        self.assertNotContains(r_ci, "Айбек")
        # empty department keeps existing unfiltered results
        r_all = self.client.get(reverse("home"), {"department": ""})
        self.assertContains(r_all, "Айбек")
        self.assertContains(r_all, "Волков")
        # pagination still present on the full list (12 seeded professors, 10 per page)
        self.assertContains(r_all, "Вперёд")
        # a narrow department list does not paginate
        self.assertNotContains(r, "Вперёд")
        # department combines with city
        r_city = self.client.get(reverse("home"), {"department": "Информатика", "city": "Ош"})
        self.assertContains(r_city, "Бакыт")
        self.assertNotContains(r_city, "Айбек")

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

    def test_filter_department(self):
        r = self.client.get(reverse("home"), {"department": "Физика"})
        self.assertContains(r, "Волков")
        self.assertNotContains(r, "Айбек")
        r_ci = self.client.get(reverse("home"), {"department": "физика"})
        self.assertContains(r_ci, "Волков")
        self.assertNotContains(r_ci, "Смирнова")
        r_all = self.client.get(reverse("home"), {"department": ""})
        self.assertContains(r_all, "Айбек")
        self.assertContains(r_all, "Волков")
        names = [row["prof"].last_name for row in self.repo.search(department="Информатика")]
        self.assertCountEqual(names, ["Токтогулов", "Маматов"])

    def test_review_pending_not_visible(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        user = User.objects.create_user(username="django_tester@example.com", email="django_tester@example.com", password="pass12345")
        self.client.force_login(user)
        before = len(self.repo.reviews_for(prof.id))
        self.client.post(reverse("review_new", args=[prof.slug]), _valid())
        self.assertEqual(len(self.repo.reviews_for(prof.id)), before)
        self.assertEqual(len(self.repo.reviews_for(prof.id, include_pending=True)), before + 1)
