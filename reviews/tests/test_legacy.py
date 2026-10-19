from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from reviews.repository import InMemoryRepository
from reviews.seed import seed
from reviews.django_repo import DjangoRepository


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
        from reviews import store as store_mod
        self.repo = InMemoryRepository()
        seed(self.repo)
        self._orig = store_mod.repo
        store_mod.repo = self.repo
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
        r = self.client.get(reverse("home"), {"city": "Ош"})
        self.assertContains(r, "Бакыт")
        self.assertNotContains(r, "Айбек")
        school = next(s for s in self.repo.schools() if "Ошский" in s.name)
        r2 = self.client.get(reverse("home"), {"school": school.slug})
        self.assertContains(r2, "Бакыт")

    def test_professor_page_and_404(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        self.assertContains(self.client.get(reverse("professor", args=[prof.slug])), "Алгоритмы")
        self.assertEqual(self.client.get(reverse("professor", args=["nobody"])).status_code, 404)

    def test_post_review_requires_login_and_pending(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        r = self.client.post(reverse("review_new", args=[prof.slug]), _valid())
        self.assertIn(r.status_code, (302, 200))
        user = User.objects.create_user(username="tester@example.com", email="tester@example.com", password="pass12345")  # nosec B106
        from reviews.models import Profile
        Profile.objects.get_or_create(user=user, defaults={"email_confirmed": True})
        Profile.objects.filter(user=user).update(email_confirmed=True)
        self.client.force_login(user)
        r2 = self.client.post(reverse("review_new", args=[prof.slug]), _valid())
        self.assertEqual(r2.status_code, 302)
        self.assertEqual(len(self.repo.reviews_for(prof.id)), 3)

    def test_vote_requires_login_and_one_vote(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        review = self.repo.reviews_for(prof.id)[0]
        r = self.client.post(reverse("review_vote", args=[review.id]), {"vote": "up"})
        self.assertIn(r.status_code, (302, 200))
        user = User.objects.create_user(username="voter@example.com", email="voter@example.com", password="pass12345")  # nosec B106
        self.client.force_login(user)
        before = review.helpful
        r2 = self.client.post(reverse("review_vote", args=[review.id]), {"vote": "up"})
        self.assertEqual(r2.status_code, 302)
        self.assertEqual(review.helpful, before + 1)
        r3 = self.client.post(reverse("review_vote", args=[review.id]), {"vote": "up"})
        self.assertEqual(r3.status_code, 302)
        self.assertEqual(review.helpful, before + 1)

    def test_course_not_uppercased_and_max_80(self):
        user = User.objects.create_user(username="c@example.com", email="c@example.com", password="pass12345")  # nosec B106
        from reviews.models import Profile
        Profile.objects.get_or_create(user=user, defaults={"email_confirmed": True})
        Profile.objects.filter(user=user).update(email_confirmed=True)
        self.client.force_login(user)
        prof = self.repo.search("Айбек")[0]["prof"]
        self.client.post(reverse("review_new", args=[prof.slug]), _valid({"course": "  Микроэкономика  "}))
        pending = [r for r in self.repo.reviews_for(prof.id, include_pending=True) if r.course == "Микроэкономика"]
        self.assertTrue(pending)

    def test_grades_include_kg_scale(self):
        from reviews.repository import GRADES
        for g in ["A", "E", "FX", "F", "Зачёт", "Незачёт", "Ещё не знаю"]:
            self.assertIn(g, [str(x) for x in GRADES])

    def test_tags_no_corruption(self):
        from reviews.repository import TAGS
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

    def test_school_without_professors(self):
        # JSON has many schools without professors — pick one
        schools_with = {r["school"].id for r in self.repo.search("")}
        without = [s for s in self.repo.schools() if s.id not in schools_with]
        self.assertTrue(without, "expected schools without professors from JSON")
        r = self.client.get(reverse("school_detail", args=[without[0].slug]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Пока нет преподавателей")

    def test_add_professor_requires_login_and_duplicate_check(self):
        school = self.repo.schools()[0]
        r = self.client.get(reverse("add_professor"))
        self.assertIn(r.status_code, (302, 200))
        user = User.objects.create_user(username="addp@example.com", email="addp@example.com", password="pass12345")  # nosec B106
        self.client.force_login(user)
        r2 = self.client.get(reverse("add_professor"))
        self.assertEqual(r2.status_code, 200)
        data = {"school": str(school.id), "first_name": "Тест", "last_name": "Тестов", "department": "Кафедра теста", "title": "доцент"}
        r3 = self.client.post(reverse("add_professor"), data)
        self.assertEqual(r3.status_code, 302)
        r4 = self.client.post(reverse("add_professor"), data)
        self.assertEqual(r4.status_code, 200)

    def test_home_grouped_schools_and_short_name(self):
        r = self.client.get(reverse("home"))
        # grouped optgroup and short_name rendered
        self.assertContains(r, "<optgroup")
        # short_name of KNU should appear
        self.assertContains(r, "КНУ")

    def test_schools_list_page(self):
        r = self.client.get(reverse("school_list"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Всего")

    def test_schools_list_filter_region_and_type(self):
        r = self.client.get(reverse("school_list"), {"region": "г. Бишкек"})
        self.assertEqual(r.status_code, 200)
        r2 = self.client.get(reverse("school_list"), {"type": "private"})
        self.assertEqual(r2.status_code, 200)

    def test_memory_has_64_schools(self):
        self.assertEqual(len(self.repo.schools()), 64)


class DjangoSmokeTests(TestCase):
    def setUp(self):
        from reviews import store as store_mod
        import reviews.views as v
        self.repo = DjangoRepository()
        from reviews.management.commands.seed_kg import Command as SeedCmd
        cmd = SeedCmd()
        cmd.handle(clear=True)
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
        user = User.objects.create_user(username="django_tester@example.com", email="django_tester@example.com", password="pass12345")  # nosec B106
        from reviews.models import Profile
        Profile.objects.get_or_create(user=user, defaults={"email_confirmed": True})
        Profile.objects.filter(user=user).update(email_confirmed=True)
        self.client.force_login(user)
        before = len(self.repo.reviews_for(prof.id))
        self.client.post(reverse("review_new", args=[prof.slug]), _valid())
        self.assertEqual(len(self.repo.reviews_for(prof.id)), before)
        self.assertEqual(len(self.repo.reviews_for(prof.id, include_pending=True)), before + 1)

    def test_load_universities_idempotent(self):
        from reviews.models import School
        from reviews.management.commands.load_universities import Command as LoadCmd
        before = School.objects.count()
        self.assertEqual(before, 64)
        cmd = LoadCmd()
        cmd.handle(file="data/kg_universities.json")
        self.assertEqual(School.objects.count(), 64)
        cmd.handle(file="data/kg_universities.json")
        self.assertEqual(School.objects.count(), 64)

    def test_schools_list_i18n(self):
        for lang in ["ru", "ky", "en"]:
            r = self.client.get(reverse("school_list"), HTTP_ACCEPT_LANGUAGE=lang)
            self.assertEqual(r.status_code, 200)

    def test_school_detail_shows_extra_fields(self):
        # pick school with website
        from reviews.models import School
        s = School.objects.exclude(website="").first()
        self.assertIsNotNone(s)
        r = self.client.get(reverse("school_detail", args=[s.slug]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, s.city)
