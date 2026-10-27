import os
import subprocess
import sys
import threading
import unittest

from django.conf import settings
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.db import IntegrityError, connection, transaction
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from . import store
from .django_repo import DjangoRepository
from .models import Professor, Review, Vote
from .ratelimit import client_ip, parse_rate
from .repository import InMemoryRepository
from .seed import seed

IS_POSTGRES = connection.vendor == "postgresql"


def _valid(overrides=None):
    d = {"course": "Алгоритмы", "term": "Осень 2025", "overall": "4", "difficulty": "3",
         "would_take_again": "yes", "grade": "A", "tags": ["Интересные лекции"],
         "comment": "Понятные лекции и честные экзамены, рекомендую."}
    if overrides:
        d.update(overrides)
    return d


def _seed_django():
    from reviews.management.commands.seed_kg import Command as SeedCmd
    from io import StringIO
    SeedCmd(stdout=StringIO()).handle(clear=True)


class RepoSwapMixin:
    """Point the views at a fresh repository for each test."""
    backend = "memory"

    def setUp(self):
        super().setUp()
        cache.clear()
        if self.backend == "memory":
            self.repo = InMemoryRepository()
            seed(self.repo)
        else:
            self.repo = DjangoRepository()
            _seed_django()
        self._orig = store.repo
        store.repo = self.repo

    def tearDown(self):
        store.repo = self._orig
        cache.clear()
        super().tearDown()

    def make_user(self, email="user@example.com", password="Very-Strong-Pass-42"):
        return User.objects.create_user(username=email, email=email, password=password)


class MemorySmokeTests(RepoSwapMixin, TestCase):
    """Smoke against InMemoryRepository (no DB) via isolated repo."""

    def test_home_and_search(self):
        self.assertContains(self.client.get(reverse("home")), "Айбек")
        r = self.client.get(reverse("home"), {"q": "физика"})
        self.assertContains(r, "Волков")
        self.assertNotContains(r, "Айбек")

    def test_search_multiple_words_and_yo(self):
        r = self.client.get(reverse("home"), {"q": "токтогулов айбек"})
        self.assertContains(r, "Айбек")

    def test_filter_city_and_school(self):
        r = self.client.get(reverse("home"), {"city": "Ош"})
        self.assertContains(r, "Бакыт")
        self.assertNotContains(r, "Айбек")
        school = next(s for s in self.repo.schools() if s.code == "oshsu")
        r2 = self.client.get(reverse("home"), {"school": school.slug})
        self.assertContains(r2, "Бакыт")

    def test_professor_page_and_404(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        self.assertContains(self.client.get(reverse("professor", args=[prof.slug])), "Алгоритмы")
        r = self.client.get(reverse("professor", args=["nobody"]))
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, "404", status_code=404)

    def test_post_review_requires_login_and_pending(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        r = self.client.post(reverse("review_new", args=[prof.slug]), _valid())
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse("login"), r["Location"])
        self.client.force_login(self.make_user())
        r2 = self.client.post(reverse("review_new", args=[prof.slug]), _valid())
        self.assertEqual(r2.status_code, 302)
        self.assertEqual(len(self.repo.reviews_for(prof.id)), 3)  # pending is not shown

    def test_vote_requires_login_and_one_vote(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        review = self.repo.reviews_for(prof.id)[0]
        r = self.client.post(reverse("review_vote", args=[review.id]), {"vote": "up"})
        self.assertEqual(r.status_code, 302)
        self.client.force_login(self.make_user("voter@example.com"))
        before = review.helpful
        self.client.post(reverse("review_vote", args=[review.id]), {"vote": "up"})
        self.assertEqual(review.helpful, before + 1)
        self.client.post(reverse("review_vote", args=[review.id]), {"vote": "up"})
        self.assertEqual(review.helpful, before + 1)

    def test_course_not_uppercased_and_trimmed(self):
        self.client.force_login(self.make_user("c@example.com"))
        prof = self.repo.search("Айбек")[0]["prof"]
        self.client.post(reverse("review_new", args=[prof.slug]), _valid({"course": "  Микроэкономика  "}))
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

    def test_rules_page(self):
        self.assertContains(self.client.get(reverse("rules")), "Правила")

    def test_school_page(self):
        school = self.repo.schools()[0]
        r = self.client.get(reverse("school_detail", args=[school.slug]))
        self.assertContains(r, school.name)

    def test_add_professor_requires_login_and_duplicate_check(self):
        school = self.repo.schools()[0]
        self.assertEqual(self.client.get(reverse("add_professor")).status_code, 302)
        self.client.force_login(self.make_user("addp@example.com"))
        self.assertEqual(self.client.get(reverse("add_professor")).status_code, 200)
        data = {"school": str(school.id), "first_name": "Тест", "last_name": "Тестов",
                "department": "Кафедра теста", "title": "доцент"}
        self.assertEqual(self.client.post(reverse("add_professor"), data).status_code, 302)
        self.assertEqual(self.client.post(reverse("add_professor"), data).status_code, 200)  # duplicate

    def test_add_professor_rejects_bad_names(self):
        school = self.repo.schools()[0]
        self.client.force_login(self.make_user("names@example.com"))
        r = self.client.post(reverse("add_professor"), {"school": str(school.id), "first_name": "<script>",
                                                        "last_name": "Тестов1", "department": "x", "title": "доцент"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.repo.search("Тестов1")), 0)

    def test_review_comment_rejects_links_and_phones(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        self.client.force_login(self.make_user("links@example.com"))
        for bad in ["Пишите мне в телеграм t.me/someone, всё расскажу", "Звоните по номеру +996 555 123 456 вечером"]:
            r = self.client.post(reverse("review_new", args=[prof.slug]), _valid({"comment": bad, "course": bad[:10]}))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, "errorlist")

    def test_pagination_keeps_query(self):
        for i in range(25):
            self.repo.add_professor(self.repo.schools()[0].id, "Тест", f"Пагинация{i}", "Физика", "доцент")
        r = self.client.get(reverse("home"), {"q": "физика"})
        self.assertContains(r, "page=2")
        self.assertContains(r, "q=")
        r2 = self.client.get(reverse("home"), {"q": "физика", "page": "2"})
        self.assertEqual(r2.status_code, 200)
        r3 = self.client.get(reverse("home"), {"page": "abc"})
        self.assertEqual(r3.status_code, 200)

    def test_security_headers(self):
        r = self.client.get(reverse("home"))
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertIn("same-origin", r["Referrer-Policy"])

    def test_healthz_any_host(self):
        r = self.client.get("/healthz", HTTP_HOST="internal-healthcheck")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_robots(self):
        self.assertContains(self.client.get("/robots.txt"), "Disallow: /accounts/")


class I18nTests(RepoSwapMixin, TestCase):

    def test_locale_middleware_enabled(self):
        self.assertIn("django.middleware.locale.LocaleMiddleware", settings.MIDDLEWARE)

    def test_accept_language_header(self):
        r = self.client.get(reverse("home"), HTTP_ACCEPT_LANGUAGE="en")
        self.assertContains(r, 'lang="en"')
        self.assertContains(r, "Find out what a class is really like")

    def test_switch_language_via_form(self):
        for code, text in [("ky", "Табуу"), ("en", "Search"), ("ru", "Найти")]:
            r = self.client.post(reverse("set_language"), {"language": code, "next": "/"})
            self.assertEqual(r.status_code, 302)
            page = self.client.get(reverse("home"))
            self.assertContains(page, f'lang="{code}"')
            self.assertContains(page, text)

    def test_tags_translated(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        r = self.client.get(reverse("professor", args=[prof.slug]), HTTP_ACCEPT_LANGUAGE="en")
        self.assertNotContains(r, "Интересные лекции")


class DjangoSmokeTests(RepoSwapMixin, TestCase):
    backend = "django"

    def test_home_shows_kg_data(self):
        self.assertContains(self.client.get(reverse("home")), "Айбек")

    def test_search_case_insensitive_cyrillic(self):
        r = self.client.get(reverse("home"), {"q": "ФИЗИКА"})
        self.assertContains(r, "Волков")
        self.assertNotContains(r, "Айбек")

    def test_ratings_match_memory_repo(self):
        mem = InMemoryRepository()
        seed(mem)
        mem_stats = {x["prof"].full_name: x["stats"]["overall"] for x in mem.search()}
        db_stats = {x["prof"].full_name: x["stats"]["overall"] for x in self.repo.search()}
        self.assertEqual(mem_stats, db_stats)
        prof = self.repo.search("Айбек")[0]["prof"]
        mprof = mem.search("Айбек")[0]["prof"]
        s1, s2 = self.repo.stats(prof.id), mem.stats(mprof.id)
        for k in ("count", "overall", "difficulty", "wta_pct", "distribution"):
            self.assertEqual(s1[k], s2[k], k)
        self.assertEqual(len(s1["top_tags"]), len(s2["top_tags"]))  # ties may be ordered differently

    def test_review_pending_not_visible(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        self.client.force_login(self.make_user("django_tester@example.com"))
        before = len(self.repo.reviews_for(prof.id))
        self.client.post(reverse("review_new", args=[prof.slug]), _valid())
        self.assertEqual(len(self.repo.reviews_for(prof.id)), before)
        self.assertEqual(len(self.repo.reviews_for(prof.id, include_pending=True)), before + 1)

    def test_duplicate_review_blocked_case_insensitive(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        self.client.force_login(self.make_user("dup@example.com"))
        self.client.post(reverse("review_new", args=[prof.slug]), _valid({"course": "Алгоритмы"}))
        # SQLite cannot lower-case Cyrillic, PostgreSQL (production) can
        second = "алгоритмы " if IS_POSTGRES else "Алгоритмы "
        r = self.client.post(reverse("review_new", args=[prof.slug]), _valid({"course": second}))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Review.objects.filter(author__email="dup@example.com").count(), 1)

    def test_duplicate_review_blocked_by_database(self):
        prof = Professor.objects.get(first_name="Айбек")
        user = self.make_user("dbdup@example.com")
        kw = dict(professor=prof, author=user, overall=4, difficulty=3, would_take_again=True, comment="x" * 30)
        Review.objects.create(course="Физика", **kw)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Review.objects.create(course="Физика", **kw)

    def test_rating_range_enforced_by_database(self):
        prof = Professor.objects.get(first_name="Айбек")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Review.objects.create(professor=prof, course="X", overall=9, difficulty=3,
                                  would_take_again=True, comment="x" * 30)

    def test_duplicate_vote_blocked(self):
        review = Review.objects.filter(status="approved").first()
        self.client.force_login(self.make_user("v@example.com"))
        before, before_down = review.helpful, review.not_helpful
        self.client.post(reverse("review_vote", args=[review.id]), {"vote": "up"})
        self.client.post(reverse("review_vote", args=[review.id]), {"vote": "up"})
        self.client.post(reverse("review_vote", args=[review.id]), {"vote": "down"})
        review.refresh_from_db()
        self.assertEqual(review.helpful, before + 1)
        self.assertEqual(review.not_helpful, before_down)
        self.assertEqual(Vote.objects.filter(review=review).count(), 1)

    def test_vote_validation(self):
        review = Review.objects.filter(status="approved").first()
        self.client.force_login(self.make_user("vv@example.com"))
        self.assertEqual(self.client.get(reverse("review_vote", args=[review.id])).status_code, 405)
        self.assertEqual(self.client.post(reverse("review_vote", args=[review.id]), {"vote": "boom"}).status_code, 400)
        self.assertEqual(self.client.post(reverse("review_vote", args=["not-a-uuid"]), {"vote": "up"}).status_code, 404)

    def test_cannot_vote_or_report_pending_review(self):
        prof = Professor.objects.get(first_name="Айбек")
        pending = Review.objects.create(professor=prof, course="X", overall=4, difficulty=3, would_take_again=True,
                                        comment="x" * 30, status="pending")
        self.client.force_login(self.make_user("p@example.com"))
        self.assertEqual(self.client.post(reverse("review_vote", args=[pending.id]), {"vote": "up"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("review_report", args=[pending.id])).status_code, 404)

    def test_cannot_vote_own_review(self):
        prof = Professor.objects.get(first_name="Айбек")
        user = self.make_user("own@example.com")
        own = Review.objects.create(professor=prof, course="X", overall=4, difficulty=3, would_take_again=True,
                                    comment="x" * 30, status="approved", author=user)
        self.client.force_login(user)
        self.client.post(reverse("review_vote", args=[own.id]), {"vote": "up"})
        own.refresh_from_db()
        self.assertEqual(own.helpful, 0)

    def test_report_once_per_user(self):
        review = Review.objects.filter(status="approved").first()
        self.client.force_login(self.make_user("r@example.com"))
        self.client.post(reverse("review_report", args=[review.id]))
        self.client.post(reverse("review_report", args=[review.id]))
        review.refresh_from_db()
        self.assertEqual(review.reported, 1)

    def test_duplicate_professor_case_insensitive_in_db(self):
        prof = Professor.objects.get(first_name="Айбек")
        if not IS_POSTGRES:
            self.skipTest("SQLite lower() is ASCII-only; Cyrillic case folding is checked on PostgreSQL")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Professor.objects.create(school=prof.school, first_name="АЙБЕК", last_name=prof.last_name.lower(),
                                     department="X", title="доцент")

    def test_no_n_plus_one_on_lists(self):
        from reviews.management.commands.seed_fake import Command as Fake
        from io import StringIO
        Fake(stdout=StringIO()).handle(professors=200, reviews=1500, seed=1)
        cache.clear()
        with self.settings(READ_CACHE_SECONDS=0):
            with self.assertNumQueries(3):  # schools (also gives the city filter), count, one page with ratings
                r = self.client.get(reverse("home"))
            self.assertEqual(r.status_code, 200)
            school = Professor.objects.first().school
            with self.assertNumQueries(5):  # school, count, page, stats, departments
                self.client.get(reverse("school_detail", args=[school.slug]))
            prof = Professor.objects.filter(reviews__isnull=False).first()
            with self.assertNumQueries(8):  # prof, school, 3x stats, count, page, tags prefetch
                self.client.get(reverse("professor", args=[prof.slug]))

    def test_read_cache_used(self):
        with self.settings(READ_CACHE_SECONDS=60):
            self.client.get(reverse("home"))
            with self.assertNumQueries(0):
                self.client.get(reverse("home"))


@override_settings(RATELIMIT_ENABLED=True, RATELIMITS={**settings.RATELIMITS, "login": "3/m", "vote": "2/m"})
class RateLimitTests(RepoSwapMixin, TestCase):

    def test_parse_rate(self):
        self.assertEqual(parse_rate("10/m"), (10, 60))
        self.assertEqual(parse_rate("5/hour"), (5, 3600))

    def test_login_post_limited_with_429(self):
        url = reverse("login")
        for _ in range(3):
            self.assertEqual(self.client.post(url, {"username": "a@b.kg", "password": "wrong"}).status_code, 200)
        r = self.client.post(url, {"username": "a@b.kg", "password": "wrong"})
        self.assertEqual(r.status_code, 429)
        self.assertTrue(int(r["Retry-After"]) > 0)

    def test_get_never_limited(self):
        url = reverse("login")
        for _ in range(4):
            self.client.post(url, {"username": "a@b.kg", "password": "wrong"})
        for _ in range(20):
            self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)

    def test_limit_is_per_ip_not_per_account(self):
        url = reverse("login")
        for _ in range(4):
            self.client.post(url, {"username": "victim@b.kg", "password": "wrong"}, REMOTE_ADDR="10.0.0.1")
        # the real owner from another IP is not locked out
        self.make_user("victim@b.kg")
        r = self.client.post(url, {"username": "victim@b.kg", "password": "Very-Strong-Pass-42"}, REMOTE_ADDR="10.0.0.2")
        self.assertEqual(r.status_code, 302)

    def test_spoofed_forwarded_for_ignored_without_proxy(self):
        url = reverse("login")
        for i in range(4):
            r = self.client.post(url, {"username": "a@b.kg", "password": "x"}, HTTP_X_FORWARDED_FOR=f"1.2.3.{i}")
        self.assertEqual(r.status_code, 429)

    def test_vote_limited(self):
        reviews = self.repo.all_reviews()[:3]
        self.client.force_login(self.make_user("rl@example.com"))
        codes = [self.client.post(reverse("review_vote", args=[r.id]), {"vote": "up"}).status_code for r in reviews]
        self.assertEqual(codes, [302, 302, 429])


class ClientIpTests(TestCase):
    rf = RequestFactory()

    def ip(self, remote, xff=None, proxies=0):
        meta = {"REMOTE_ADDR": remote}
        if xff is not None:
            meta["HTTP_X_FORWARDED_FOR"] = xff
        with self.settings(TRUSTED_PROXY_COUNT=proxies):
            return client_ip(self.rf.get("/", **meta))

    def test_no_proxy_uses_remote_addr(self):
        self.assertEqual(self.ip("9.9.9.9", "1.1.1.1"), "9.9.9.9")

    def test_one_proxy_takes_rightmost(self):
        # client tried to fake 6.6.6.6, our proxy appended the real 5.5.5.5
        self.assertEqual(self.ip("172.18.0.2", "6.6.6.6, 5.5.5.5", proxies=1), "5.5.5.5")

    def test_two_proxies(self):
        self.assertEqual(self.ip("172.18.0.2", "6.6.6.6, 5.5.5.5, 10.0.0.7", proxies=2), "5.5.5.5")

    def test_garbage_falls_back(self):
        self.assertEqual(self.ip("172.18.0.2", "not-an-ip", proxies=1), "172.18.0.2")

    def test_clients_behind_proxy_are_different(self):
        self.assertNotEqual(self.ip("172.18.0.2", "5.5.5.5", 1), self.ip("172.18.0.2", "5.5.5.6", 1))

    def test_ipv6_grouped_by_64(self):
        self.assertEqual(self.ip("2001:db8::1"), self.ip("2001:db8::ffff"))


class AccountTests(RepoSwapMixin, TestCase):

    def test_signup_rejects_weak_passwords(self):
        for pwd in ["12345678", "password", "short1"]:
            r = self.client.post(reverse("signup"), {"email": "w@example.com", "password1": pwd, "password2": pwd})
            self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username="w@example.com").exists())

    def test_signup_login_case_insensitive_and_sends_verification(self):
        pwd = "Very-Strong-Pass-42"
        r = self.client.post(reverse("signup"), {"email": "New@Example.com", "password1": pwd, "password2": pwd})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(User.objects.filter(username="new@example.com").exists())
        self.assertEqual(len(mail.outbox), 1)
        self.client.logout()
        r = self.client.post(reverse("login"), {"username": "NEW@example.com", "password": pwd})
        self.assertEqual(r.status_code, 302)

    def test_signup_duplicate_email(self):
        self.make_user("dupe@example.com")
        pwd = "Very-Strong-Pass-42"
        r = self.client.post(reverse("signup"), {"email": "DUPE@example.com", "password1": pwd, "password2": pwd})
        self.assertEqual(r.status_code, 200)

    def _link(self):
        import re
        return re.search(r"https?://[^/]+(/accounts/verify/\S+/)", mail.outbox[-1].body).group(1)

    def test_verification_link_marks_verified_once(self):
        pwd = "Very-Strong-Pass-42"
        self.client.post(reverse("signup"), {"email": "ver@example.com", "password1": pwd, "password2": pwd})
        link = self._link()
        self.assertEqual(self.client.get(link).status_code, 200)
        user = User.objects.get(username="ver@example.com")
        self.assertTrue(user.profile.email_verified)
        self.assertEqual(self.client.get(link).status_code, 400)  # one-time

    def test_verification_does_not_unban(self):
        pwd = "Very-Strong-Pass-42"
        self.client.post(reverse("signup"), {"email": "ban@example.com", "password1": pwd, "password2": pwd})
        link = self._link()
        User.objects.filter(username="ban@example.com").update(is_active=False)  # moderator bans
        self.client.logout()
        self.client.get(link)
        user = User.objects.get(username="ban@example.com")
        self.assertFalse(user.is_active)
        r = self.client.post(reverse("login"), {"username": "ban@example.com", "password": pwd})
        self.assertEqual(r.status_code, 200)  # still cannot log in

    def test_bad_token(self):
        self.assertEqual(self.client.get(reverse("verify_email", args=["MQ", "bad-token"])).status_code, 400)

    @override_settings(REQUIRE_EMAIL_VERIFICATION=True)
    def test_unverified_cannot_post_when_required(self):
        prof = self.repo.search("Айбек")[0]["prof"]
        self.client.force_login(self.make_user("unv@example.com"))
        r = self.client.post(reverse("review_new", args=[prof.slug]), _valid())
        self.assertRedirects(r, reverse("verification_needed"), fetch_redirect_response=False)
        self.assertEqual(len(self.repo.reviews_for(prof.id, include_pending=True)), 3)
        # GET still works
        self.assertEqual(self.client.get(reverse("review_new", args=[prof.slug])).status_code, 200)


class SettingsGuardTests(unittest.TestCase):
    """Run settings in a separate process with a production-like environment."""
    STRONG = "x7Gq2pV9kLm4Zr8TbN1wYc6Hs3Jd5Fa0Qe9Ui2Op7As4Df1Gh8Jk3Lz6Xc5Vb0Nm"

    def run_settings(self, **env_vars):
        env = {k: v for k, v in os.environ.items()
               if k not in ("DEBUG", "SECRET_KEY", "ALLOWED_HOSTS", "TRUSTED_PROXY_COUNT")}
        env.update({"DJANGO_SETTINGS_MODULE": "config.settings", "DEBUG": "False"}, **env_vars)
        code = ("import django; django.setup(); from django.conf import settings as s; "
                "print(s.SECURE_SSL_REDIRECT, s.SESSION_COOKIE_SECURE, s.CSRF_COOKIE_SECURE, "
                "s.SECURE_HSTS_SECONDS > 0, getattr(s, 'SECURE_PROXY_SSL_HEADER', None) is not None)")
        return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                              cwd=settings.BASE_DIR)

    def test_weak_secret_key_refused(self):
        for key in ["", "dev-only-change-me", "change-me-in-production", "short", "django-insecure-" + "a" * 50]:
            p = self.run_settings(SECRET_KEY=key, ALLOWED_HOSTS="example.kg")
            self.assertNotEqual(p.returncode, 0, key)
            self.assertIn("SECRET_KEY", p.stderr)

    def test_allowed_hosts_required(self):
        p = self.run_settings(SECRET_KEY=self.STRONG, ALLOWED_HOSTS="")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("ALLOWED_HOSTS", p.stderr)

    def test_production_defaults_are_secure(self):
        p = self.run_settings(SECRET_KEY=self.STRONG, ALLOWED_HOSTS="example.kg")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.split(), ["True", "True", "True", "True", "False"])

    def test_proxy_header_only_with_trusted_proxy(self):
        p = self.run_settings(SECRET_KEY=self.STRONG, ALLOWED_HOSTS="example.kg", TRUSTED_PROXY_COUNT="1")
        self.assertEqual(p.stdout.split()[-1], "True")


@unittest.skipUnless(IS_POSTGRES, "real concurrency needs PostgreSQL")
class ConcurrencyTests(TransactionTestCase):
    """Many threads hit the same row at once; the database must keep the rules."""

    def setUp(self):
        _seed_django()
        self.repo = DjangoRepository()

    def _parallel(self, fn, n=8):
        barrier = threading.Barrier(n)
        results = []

        def worker():
            try:
                barrier.wait()
                results.append(fn())
            except Exception as e:  # noqa: BLE001
                results.append(e)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    def test_parallel_votes_count_once(self):
        review = Review.objects.filter(status="approved").first()
        before = review.helpful
        user = User.objects.create_user("race@example.com", "race@example.com", "Very-Strong-Pass-42")
        self._parallel(lambda: self.repo.vote(str(review.id), True, user=user))
        review.refresh_from_db()
        self.assertEqual(Vote.objects.filter(review=review, user=user).count(), 1)
        self.assertEqual(review.helpful, before + 1)

    def test_parallel_votes_of_many_users_not_lost(self):
        review = Review.objects.filter(status="approved").first()
        before = review.helpful
        users = [User.objects.create_user(f"u{i}@example.com", f"u{i}@example.com", "x") for i in range(8)]
        it = iter(users)
        lock = threading.Lock()

        def vote():
            with lock:
                u = next(it)
            self.repo.vote(str(review.id), True, user=u)
        self._parallel(vote)
        review.refresh_from_db()
        self.assertEqual(review.helpful, before + 8)  # F() update: no lost increments

    def test_parallel_duplicate_reviews(self):
        prof = Professor.objects.get(first_name="Айбек")
        user = User.objects.create_user("rev@example.com", "rev@example.com", "x")
        data = {"course": "Гонка", "overall": 4, "difficulty": 3, "would_take_again": True, "comment": "x" * 30}
        self._parallel(lambda: self.repo.add_review(str(prof.id), data, user=user))
        self.assertEqual(Review.objects.filter(author=user).count(), 1)


# ---------- regions, cities, universities ----------

class UniversitiesDataTests(unittest.TestCase):
    """data/universities_kg.json is the list every backend loads."""

    def test_file_is_complete_and_consistent(self):
        from .geo import CITY_REGION, REGION_CODES
        from .universities import load_universities
        unis = load_universities()
        self.assertGreaterEqual(len(unis), 70)
        codes = [u["code"] for u in unis]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(len({u["name"].lower() for u in unis}), len(unis))
        for u in unis:
            self.assertIn(u["region"], REGION_CODES, u["code"])
            self.assertEqual(CITY_REGION[u["city"]], u["region"], u["code"])
            self.assertIn(u["kind"], ("state", "private"))
            self.assertTrue(u["name_ky"] and u["name_en"], u["code"])
        regions = {u["region"] for u in unis}
        for code in ("bishkek", "osh-city", "batken", "jalal-abad", "issyk-kul", "naryn", "talas", "chuy"):
            self.assertIn(code, regions)
        for code in ("knu", "alatoo", "auca", "krsu", "manas", "nsu", "iksu", "talsu", "batsu", "jasu", "oshtu"):
            self.assertIn(code, codes)

    def test_seven_oblasts_and_two_cities(self):
        from .geo import REGIONS
        self.assertEqual(sum(1 for _c, _n, k in REGIONS if k == "oblast"), 7)
        self.assertEqual([c for c, _n, k in REGIONS if k == "city"], ["bishkek", "osh-city"])

    def test_parse_place(self):
        from .geo import parse_place
        self.assertEqual(parse_place("r:chuy"), ("chuy", ""))
        self.assertEqual(parse_place("Токмок"), ("", "Токмок"))
        self.assertEqual(parse_place("r:nowhere"), ("", ""))
        self.assertEqual(parse_place(""), ("", ""))


class LocationFilterMixin:
    """Same checks for both backends (memory and Django)."""

    def _options(self, html, value):
        return html.count(f'<option value="{value}"')

    def test_city_dropdown_has_no_duplicates(self):
        html = self.client.get(reverse("home")).content.decode()
        city_select = html[html.index('name="city"'):html.index('name="school"')]
        self.assertEqual(self._options(city_select, "Бишкек"), 1)
        self.assertEqual(self._options(city_select, "Ош"), 1)
        for city in ("Каракол", "Нарын", "Талас", "Баткен", "Жалал-Абад", "Токмок"):
            self.assertEqual(self._options(city_select, city), 1, city)

    def test_city_dropdown_grouped_by_region(self):
        html = self.client.get(reverse("home")).content.decode()
        for oblast in ("Баткенская", "Джалал-Абадская", "Иссык-Кульская", "Нарынская", "Ошская",
                       "Таласская", "Чуйская"):
            self.assertIn(f'<optgroup label="{oblast} область">', html)
        self.assertIn('<option value="r:chuy"', html)

    def test_repo_cities_distinct(self):
        cities = self.repo.cities()
        self.assertEqual(len(cities), len(set(cities)))
        self.assertIn("Каракол", cities)

    def test_city_narrows_schools_and_results(self):
        r = self.client.get(reverse("home"), {"city": "Ош"})
        html = r.content.decode()
        self.assertIn('<option value="oshsu" data-region="osh-city" data-city="Ош">', html)
        self.assertIn('<option value="knu" data-region="bishkek" data-city="Бишкек" hidden disabled>', html)
        self.assertContains(r, "Бакыт")
        self.assertNotContains(r, "Айбек")

    def test_region_filter(self):
        r = self.client.get(reverse("home"), {"city": "r:chuy"})
        html = r.content.decode()
        self.assertIn('<option value="r:chuy" selected>', html)
        self.assertIn('<option value="iuca" data-region="chuy" data-city="Токмок">', html)
        self.assertIn('data-city="Бишкек" hidden disabled', html)
        self.assertNotContains(r, "Айбек")  # no demo professors in Chuy oblast
        r2 = self.client.get(reverse("home"), {"region": "osh-city"})
        self.assertContains(r2, "Бакыт")
        self.assertNotContains(r2, "Айбек")

    def test_unknown_region_ignored(self):
        r = self.client.get(reverse("home"), {"city": "r:<script>"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Айбек")
        self.assertNotContains(r, "<script>")

    def test_school_outside_chosen_city_is_dropped(self):
        r = self.client.get(reverse("home"), {"city": "Ош", "school": "knu"})
        self.assertContains(r, "Бакыт")
        self.assertNotContains(r, 'value="knu" data-region="bishkek" data-city="Бишкек" hidden disabled selected')

    def test_labels_translated(self):
        en = self.client.get(reverse("home"), HTTP_ACCEPT_LANGUAGE="en")
        self.assertContains(en, '<optgroup label="Chuy Region">')
        self.assertContains(en, "Bishkek (")
        self.assertContains(en, "Kyrgyz National University named after J. Balasagyn")
        ky = self.client.get(reverse("home"), HTTP_ACCEPT_LANGUAGE="ky")
        self.assertContains(ky, '<optgroup label="Чүй облусу">')
        self.assertContains(ky, "Ж. Баласагын атындагы Кыргыз улуттук университети")
        # stored values stay Russian, so the filter keeps working in every language
        self.assertContains(ky, '<option value="Бишкек"')

    def test_school_page_shows_city_and_region(self):
        school = next(s for s in self.repo.schools() if s.code == "iksu")
        r = self.client.get(reverse("school_detail", args=[school.slug]))
        self.assertContains(r, "Каракол")
        self.assertContains(r, "Иссык-Кульская область")


class MemoryLocationTests(LocationFilterMixin, RepoSwapMixin, TestCase):
    backend = "memory"


class DjangoLocationTests(LocationFilterMixin, RepoSwapMixin, TestCase):
    backend = "django"

    def test_seed_kg_is_idempotent(self):
        from io import StringIO
        from reviews.management.commands.seed_kg import Command as SeedCmd
        from .models import School
        from .universities import load_universities
        n_schools, n_profs, n_reviews = School.objects.count(), Professor.objects.count(), Review.objects.count()
        self.assertEqual(n_schools, len(load_universities()))
        SeedCmd(stdout=StringIO()).handle()
        SeedCmd(stdout=StringIO()).handle()
        self.assertEqual((School.objects.count(), Professor.objects.count(), Review.objects.count()),
                         (n_schools, n_profs, n_reviews))
        self.assertEqual(School.objects.filter(region="").count(), 0)

    def test_seed_kg_adopts_old_rows_and_keeps_slug(self):
        from io import StringIO
        from reviews.management.commands.seed_kg import Command as SeedCmd
        from .models import School
        School.objects.all().delete()
        old = School.objects.create(name="Бишкекский гуманитарный университет им. К. Карасаева", city="Бишкек",
                                    slug="старый-слаг")
        SeedCmd(stdout=StringIO()).handle()
        old.refresh_from_db()
        self.assertEqual(old.code, "bgu")
        self.assertEqual(old.slug, "старый-слаг")
        self.assertEqual(old.name, "Бишкекский государственный университет им. К. Карасаева")
        self.assertEqual(old.region, "bishkek")
        self.assertEqual(School.objects.filter(code="bgu").count(), 1)

    def test_region_filled_from_city_on_save(self):
        from .models import School
        s = School.objects.create(name="Тестовый институт", city="Токмок", slug="test-inst")
        self.assertEqual(s.region, "chuy")


class SeedFakeTests(TestCase):

    def _run(self, **kw):
        from io import StringIO
        from reviews.management.commands.seed_fake import Command as Fake
        from reviews.management.commands.seed_kg import Command as SeedCmd
        SeedCmd(stdout=StringIO()).handle()
        opts = {"professors": 600, "reviews": 1200, "seed": 7}
        opts.update(kw)
        Fake(stdout=StringIO()).handle(**opts)

    def test_names_realistic_unique_and_spread(self):
        import re
        from reviews.management.commands.seed_fake import FEMALE, MALE, feminine_surname
        from .models import School
        self._run()
        fake = Professor.objects.filter(is_demo=True)
        self.assertEqual(fake.count(), 600)
        names = list(fake.values_list("first_name", "last_name"))
        self.assertEqual(len(names), len(set(names)))
        for first, last in names:
            self.assertIsNone(re.search(r"\d", first + last), (first, last))
            given = first.split()[0]
            self.assertIn(given, MALE + FEMALE)
            if given in FEMALE:
                self.assertFalse(last.endswith(("ов", "ев", "ин", "ский", "цкий")), (first, last))
                if len(first.split()) > 1:
                    self.assertTrue(first.endswith("овна"), first)
            else:
                self.assertFalse(last.endswith(("ова", "ева", "ина", "ская", "цкая")), (first, last))
                if len(first.split()) > 1:
                    self.assertTrue(first.endswith("ович"), first)
        self.assertEqual(feminine_surname("Жумалиев"), "Жумалиева")
        self.assertEqual(feminine_surname("Ковальский"), "Ковальская")
        self.assertEqual(feminine_surname("Ким"), "Ким")
        # every university gets fake professors
        self.assertEqual(School.objects.filter(professors__is_demo=True).distinct().count(), School.objects.count())

    def test_wipe_keeps_real_users_and_their_reviews(self):
        self._run()
        user = User.objects.create_user("real@example.com", "real@example.com", "x", is_staff=True,
                                        is_superuser=True)
        seed_prof = Professor.objects.get(first_name="Нурлан", last_name="Бекбоев")
        mine = Review.objects.create(professor=seed_prof, course="Мой курс", overall=4, difficulty=3,
                                     would_take_again=True, comment="x" * 30, status="pending", author=user)
        fake_prof = Professor.objects.filter(is_demo=True).first()
        on_fake = Review.objects.create(professor=fake_prof, course="Курс", overall=5, difficulty=2,
                                        would_take_again=True, comment="y" * 30, status="approved", author=user)
        added = Professor.objects.create(school=seed_prof.school, first_name="Свой", last_name="Преподаватель",
                                         department="X", title="доцент", status="pending", created_by=user)
        self._run(wipe=True, professors=100, reviews=100, seed=8)
        user.refresh_from_db()
        self.assertTrue(user.is_superuser and user.is_staff)
        self.assertTrue(Review.objects.filter(pk=mine.pk).exists())
        self.assertTrue(Review.objects.filter(pk=on_fake.pk).exists())
        self.assertTrue(Professor.objects.filter(pk=added.pk).exists())
        self.assertTrue(Professor.objects.filter(pk=seed_prof.pk).exists())
        # the old batch is gone except the professor a real user reviewed
        self.assertEqual(Professor.objects.filter(is_demo=True).count(), 100)
        self.assertTrue(Professor.objects.filter(pk=fake_prof.pk).exists())
