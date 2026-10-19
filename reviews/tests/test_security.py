import os
import re
import subprocess
import sys
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import IntegrityError
from django.test import TestCase, override_settings, TransactionTestCase
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes

from reviews.django_repo import DjangoRepository
from reviews.tokens import email_confirm_token


def _valid(overrides=None):
    d = {"course": "Алгоритмы", "term": "Осень 2025", "overall": "4", "difficulty": "3",
         "would_take_again": "yes", "grade": "A", "tags": ["Интересные лекции"],
         "comment": "Понятные лекции и честные экзамены рекомендую студентам."}
    if overrides:
        d.update(overrides)
    return d

def _make_confirmed_user(username, password="StrongPass123", email=None):
    email = email or username
    user = User.objects.create_user(username=username, email=email, password=password)
    from reviews.models import Profile
    Profile.objects.get_or_create(user=user, defaults={"email_confirmed": True})
    Profile.objects.filter(user=user).update(email_confirmed=True)
    user.is_active = True
    user.save()
    return user

# ------------------------------------------------------------------
# 1. i18n
# ------------------------------------------------------------------
class I18nTests(TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from django.core.management import call_command
            call_command("compilemessages", verbosity=0)
        except Exception:
            try:
                import polib
                base = Path(__file__).resolve().parent.parent.parent
                for lang in ["ky", "en", "ru"]:
                    po = base / "locale" / lang / "LC_MESSAGES" / "django.po"
                    mo = base / "locale" / lang / "LC_MESSAGES" / "django.mo"
                    if po.exists():
                        try:
                            pofile = polib.pofile(str(po))
                            pofile.save_as_mofile(str(mo))
                        except Exception:
                            pass
            except Exception:
                pass
        super().setUpClass()

    def test_ky_accept_language(self):
        r = self.client.get(reverse("home"), HTTP_ACCEPT_LANGUAGE="ky")
        self.assertEqual(r.status_code, 200)
        content = r.content.decode()
        self.assertTrue("Окутуучунун аты" in content or "Табуу" in content or "ЖОЖ" in content)

    def test_set_language_changes_html_lang(self):
        self.client.post("/i18n/setlang/", {"language": "en", "next": "/"}, follow=False)
        r2 = self.client.get(reverse("home"), HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(r2.status_code, 200)
        self.assertIn('lang="en"', r2.content.decode())

# ------------------------------------------------------------------
# 2. Rate limit
# ------------------------------------------------------------------
class RateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        from reviews import store as store_mod
        import reviews.views as v
        self.repo = DjangoRepository()
        from reviews.management.commands.seed_kg import Command as SeedCmd
        SeedCmd().handle(clear=True)
        self._orig = store_mod.repo
        self._orig_v = v.repo
        store_mod.repo = self.repo
        v.repo = self.repo
        self.prof = self.repo.search("Айбек")[0]["prof"]

    def tearDown(self):
        from reviews import store as store_mod
        import reviews.views as v
        store_mod.repo = self._orig
        v.repo = self._orig_v
        cache.clear()

    def test_get_signup_not_ratelimited(self):
        for i in range(10):
            r = self.client.get(reverse("signup"), REMOTE_ADDR="10.0.0.1")
            self.assertEqual(r.status_code, 200)

    def test_post_signup_6th_blocked(self):
        for i in range(5):
            r = self.client.post(reverse("signup"), {"email": f"r{i}@example.com", "password1": "StrongPass123aa", "password2": "StrongPass123aa"}, REMOTE_ADDR="10.0.0.2")
            self.assertNotEqual(r.status_code, 429)
        r = self.client.post(reverse("signup"), {"email": "r5@example.com", "password1": "StrongPass123aa", "password2": "StrongPass123aa"}, REMOTE_ADDR="10.0.0.2")
        self.assertEqual(r.status_code, 429)

    def test_review_6th_per_day_blocked(self):
        user = _make_confirmed_user("ratelimit_review@example.com")
        self.client.force_login(user)
        for i in range(5):
            data = _valid({"course": f"Course{i}"})
            r = self.client.post(reverse("review_new", args=[self.prof.slug]), data, REMOTE_ADDR="10.0.0.3")
            self.assertEqual(r.status_code, 302, f"review {i} failed: {r.status_code}")
        data = _valid({"course": "Course5"})
        r = self.client.post(reverse("review_new", args=[self.prof.slug]), data, REMOTE_ADDR="10.0.0.3")
        self.assertEqual(r.status_code, 429)

    def test_vote_61_blocked(self):
        cache.clear()
        user = _make_confirmed_user("voter61@example.com")
        self.client.force_login(user)
        from reviews.models import Professor as PModel, Review as RModel
        other = User.objects.create_user(username="other61@example.com", email="other61@example.com", password="StrongPass123")
        from reviews.models import Profile
        Profile.objects.get_or_create(user=other, defaults={"email_confirmed": True})
        review_ids = []
        for i in range(61):
            data = {"course": f"VCourse{i}", "term": "", "overall": 4, "difficulty": 3, "would_take_again": True, "grade": "", "comment": "хороший предмет" * 2, "tags": []}
            rv = self.repo.add_review(self.prof.id, data, user=None, status="approved")
            RModel.objects.filter(pk=rv.id).update(status="approved")
            review_ids.append(rv.id)
        for idx, rid in enumerate(review_ids[:60]):
            r = self.client.post(reverse("review_vote", args=[rid]), {"vote": "up"}, REMOTE_ADDR="10.0.0.4")
            self.assertNotEqual(r.status_code, 429, f"vote {idx} unexpectedly 429")
        r = self.client.post(reverse("review_vote", args=[review_ids[60]]), {"vote": "up"}, REMOTE_ADDR="10.0.0.4")
        self.assertEqual(r.status_code, 429)

# ------------------------------------------------------------------
# 3. Axes
# ------------------------------------------------------------------
class AxesTests(TestCase):
    def test_pair_lockout_not_overbroad(self):
        cache.clear()
        victim = User.objects.create_user(username="victim", email="victim@example.com", password="StrongPass123")
        for i in range(6):
            self.client.post(reverse("login"), {"username": "victim", "password": "wrong"}, REMOTE_ADDR=f"10.0.1.{i}")
        r = self.client.post(reverse("login"), {"username": "victim", "password": "StrongPass123"}, REMOTE_ADDR="10.0.1.99")
        self.assertEqual(r.status_code, 302)

    def test_same_ip_blocked_after_6(self):
        cache.clear()
        User.objects.create_user(username="victim2", email="victim2@example.com", password="StrongPass123")
        for i in range(6):
            self.client.post(reverse("login"), {"username": "victim2", "password": "wrong"}, REMOTE_ADDR="10.0.2.1")
        r = self.client.post(reverse("login"), {"username": "victim2", "password": "StrongPass123"}, REMOTE_ADDR="10.0.2.1")
        self.assertNotEqual(r.status_code, 302)

class LoginRatelimitTests(TestCase):
    def test_login_ratelimit_30_per_hour(self):
        cache.clear()
        for i in range(30):
            r = self.client.post(reverse("login"), {"username": f"user{i}", "password": "wrong"}, REMOTE_ADDR="10.0.3.1")
            self.assertNotEqual(r.status_code, 429, f"login {i} blocked early")
        r = self.client.post(reverse("login"), {"username": "user30", "password": "wrong"}, REMOTE_ADDR="10.0.3.1")
        self.assertEqual(r.status_code, 429)

# ------------------------------------------------------------------
# 4. client_ip
# ------------------------------------------------------------------
class ClientIpTests(TestCase):
    def test_n0_ignores_xff(self):
        from reviews.net import client_ip
        from django.test import RequestFactory
        rf = RequestFactory()
        req = rf.get("/", REMOTE_ADDR="1.1.1.1", HTTP_X_FORWARDED_FOR="9.9.9.9, 2.2.2.2")
        os.environ.pop("TRUSTED_PROXY_COUNT", None)
        os.environ["TRUSTED_PROXY_COUNT"] = "0"
        try:
            self.assertEqual(client_ip(req), "1.1.1.1")
        finally:
            del os.environ["TRUSTED_PROXY_COUNT"]

    def test_n1_different_xff_different_counters(self):
        cache.clear()
        os.environ["TRUSTED_PROXY_COUNT"] = "1"
        try:
            cache.clear()
            for i in range(5):
                r = self.client.post(reverse("signup"), {"email": f"cip{i}@example.com", "password1": "StrongPass123aa", "password2": "StrongPass123aa"},
                                     REMOTE_ADDR="10.0.0.10", HTTP_X_FORWARDED_FOR="1.1.1.1")
                self.assertNotEqual(r.status_code, 429)
            r = self.client.post(reverse("signup"), {"email": "cip5@example.com", "password1": "StrongPass123aa", "password2": "StrongPass123aa"},
                                 REMOTE_ADDR="10.0.0.10", HTTP_X_FORWARDED_FOR="1.1.1.1")
            self.assertEqual(r.status_code, 429)
            r = self.client.post(reverse("signup"), {"email": "cip6@example.com", "password1": "StrongPass123aa", "password2": "StrongPass123aa"},
                                 REMOTE_ADDR="10.0.0.10", HTTP_X_FORWARDED_FOR="2.2.2.2")
            self.assertNotEqual(r.status_code, 429)
        finally:
            cache.clear()
            if "TRUSTED_PROXY_COUNT" in os.environ:
                del os.environ["TRUSTED_PROXY_COUNT"]

# ------------------------------------------------------------------
# 5. One-time email confirm
# ------------------------------------------------------------------
class EmailConfirmTests(TestCase):
    def test_one_time_link_after_ban(self):
        user = User.objects.create_user(username="onetest@example.com", email="onetest@example.com", password="StrongPass123", is_active=False)
        from reviews.models import Profile
        Profile.objects.get_or_create(user=user, defaults={"email_confirmed": False})
        token = email_confirm_token.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        r = self.client.get(reverse("confirm_email", args=[uid, token]))
        self.assertEqual(r.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        user.is_active = False
        user.save()
        r2 = self.client.get(reverse("confirm_email", args=[uid, token]))
        user.refresh_from_db()
        self.assertFalse(user.is_active)

# ------------------------------------------------------------------
# 6. Search N+1
# ------------------------------------------------------------------
class SearchPerformanceTests(TransactionTestCase):
    def _setup_profs(self, n):
        from reviews.models import School, Professor, Review
        School.objects.all().delete()
        Professor.objects.all().delete()
        school = School.objects.create(name="Test School", slug="test-school", city="Бишкек")
        for i in range(n):
            prof = Professor.objects.create(school=school, first_name="A", last_name=f"ZName{i:04d}", slug=f"a-zname-{i}", department="Dept", title="доцент", status="approved")
            Review.objects.create(professor=prof, course="Algo", overall=5 if i == n-1 else 3, difficulty=3, would_take_again=True, comment="ok ok ok ok ok ok ok ok", status="approved")
        return school

    def setUp(self):
        from reviews import store as store_mod
        import reviews.views as v
        self.repo = DjangoRepository()
        self._orig = store_mod.repo
        self._orig_v = v.repo
        store_mod.repo = self.repo
        v.repo = self.repo

    def tearDown(self):
        from reviews import store as store_mod
        import reviews.views as v
        store_mod.repo = self._orig
        v.repo = self._orig_v

    def test_query_count_stable(self):
        cache.clear()
        self._setup_profs(5)
        from django.test.utils import CaptureQueriesContext
        from django.db import connection as conn
        with CaptureQueriesContext(conn) as ctx5:
            r = self.client.get(reverse("home"))
            self.assertEqual(r.status_code, 200)
        q5 = len(ctx5.captured_queries)
        self._setup_profs(30)
        with CaptureQueriesContext(conn) as ctx30:
            r = self.client.get(reverse("home"))
            self.assertEqual(r.status_code, 200)
        q30 = len(ctx30.captured_queries)
        self.assertEqual(q5, q30, f"queries grew: 5->{q5}, 30->{q30}")

    def test_best_rating_first_even_last_alphabetically(self):
        self._setup_profs(250)
        r = self.client.get(reverse("home"))
        self.assertEqual(r.status_code, 200)
        content = r.content.decode()
        m = re.search(r"/professors/(a-zname-[^\"]+)/", content)
        self.assertIsNotNone(m, "no professor link found; got: " + content[:1500])
        self.assertEqual(m.group(1), "a-zname-249")

# ------------------------------------------------------------------
# 7. CSP
# ------------------------------------------------------------------
class CspInlineTests(TestCase):
    def setUp(self):
        from reviews.management.commands.seed_kg import Command as SeedCmd
        SeedCmd().handle(clear=True)

    def test_no_inline_style_or_script(self):
        urls = [reverse("home"), reverse("school_list"), reverse("rules"), reverse("privacy"), reverse("signup"), reverse("login")]
        from reviews.models import School, Professor
        prof = Professor.objects.filter(status="approved").first()
        school = School.objects.first()
        if prof:
            urls.append(reverse("professor", args=[prof.slug]))
            urls.append(reverse("review_new", args=[prof.slug]))
        if school:
            urls.append(reverse("school_detail", args=[school.slug]))
        for url in urls:
            r = self.client.get(url)
            html = r.content.decode()
            self.assertNotIn("style=", html, f"style= found in {url}")
            self.assertNotIn("<script>", html.replace('<script src', ''))
            self.assertIsNone(re.search(r'\son[a-z]+\s*=', html, re.I), f"inline handler in {url}")

# ------------------------------------------------------------------
# 8. Fail-safe via subprocess
# ------------------------------------------------------------------
class FailSafeTests(TestCase):
    def _run(self, env):
        base = Path(__file__).resolve().parent.parent.parent
        full_env = os.environ.copy()
        full_env.update(env)
        return subprocess.run([sys.executable, "manage.py", "check"], cwd=str(base), env=full_env, capture_output=True, text=True, timeout=10)

    def test_missing_secret_key_fails(self):
        proc = self._run({"DEBUG": "False", "ALLOWED_HOSTS": "example.kg", "DATABASE_URL": "", "SECRET_KEY": ""})
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("SECRET_KEY", proc.stderr + proc.stdout)

    def test_wildcard_hosts_fails(self):
        proc = self._run({"DEBUG": "False", "SECRET_KEY": "a"*60, "ALLOWED_HOSTS": "*", "DATABASE_URL": ""})
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("ALLOWED_HOSTS", proc.stderr + proc.stdout)

    def test_memory_backend_fails(self):
        proc = self._run({"DEBUG": "False", "SECRET_KEY": "a"*60, "ALLOWED_HOSTS": "example.kg", "REPO_BACKEND": "memory", "DATABASE_URL": ""})
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("REPO_BACKEND", proc.stderr + proc.stdout)

    def test_full_prod_check_zero(self):
        proc = self._run({"DEBUG": "False", "SECRET_KEY": "a"*64, "ALLOWED_HOSTS": "example.kg", "REPO_BACKEND": "django", "DATABASE_URL": "postgres://proflens:proflens@localhost:5432/proflens", "ADMIN_URL": "admin-secret-xyz/"})
        self.assertEqual(proc.returncode, 0, f"stderr: {proc.stderr}")

# ------------------------------------------------------------------
# 9. Admin 2FA
# ------------------------------------------------------------------
class Admin2FATests(TestCase):
    def test_staff_without_device_no_access(self):
        User = get_user_model()
        admin = User.objects.create_user(username="admin1@example.com", email="admin1@example.com", password="StrongPass123", is_staff=True, is_superuser=True)
        self.client.force_login(admin)
        from django.conf import settings
        admin_url = "/" + settings.ADMIN_URL.strip("/") + "/"
        r = self.client.get(admin_url)
        self.assertNotEqual(r.status_code, 200)

    def test_staff_with_totp_access(self):
        from django_otp.plugins.otp_totp.models import TOTPDevice
        User = get_user_model()
        admin = User.objects.create_user(username="admin2@example.com", email="admin2@example.com", password="StrongPass123", is_staff=True, is_superuser=True)
        device = TOTPDevice.objects.create(user=admin, name="default", confirmed=True)
        self.client.force_login(admin)
        from django_otp import DEVICE_ID_SESSION_KEY
        session = self.client.session
        session[DEVICE_ID_SESSION_KEY] = device.persistent_id
        session.save()
        from django.conf import settings
        admin_url = "/" + settings.ADMIN_URL.strip("/") + "/"
        r = self.client.get(admin_url)
        self.assertEqual(r.status_code, 200)

# ------------------------------------------------------------------
# 10. Headers / password / constraints / content
# ------------------------------------------------------------------
class SecurityHeadersTests(TestCase):
    def test_headers_present(self):
        r = self.client.get(reverse("home"))
        self.assertEqual(r["X-Frame-Options"], "DENY")
        self.assertEqual(r["X-Content-Type-Options"], "nosniff")
        self.assertEqual(r["Referrer-Policy"], "same-origin")
        self.assertIn("Content-Security-Policy", r)
        csp = r["Content-Security-Policy"]
        self.assertIn("default-src 'self'", csp)
        self.assertNotIn("unsafe-inline", csp)

class PasswordValidationTests(TestCase):
    def test_weak_password_rejected(self):
        r = self.client.post(reverse("signup"), {"email": "weak2@example.com", "password1": "1234567890", "password2": "1234567890"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(email="weak2@example.com").exists())

class SignupBehaviorTests(TestCase):
    def test_signup_creates_inactive_and_sends_email(self):
        from django.core import mail
        r = self.client.post(reverse("signup"), {"email": "newuser2@example.com", "password1": "StrongPass123aa", "password2": "StrongPass123aa"})
        self.assertEqual(r.status_code, 200)
        user = User.objects.get(email="newuser2@example.com")
        self.assertFalse(user.is_active)
        self.assertEqual(len(mail.outbox), 1)

    def test_repeated_signup_same_message(self):
        r1 = self.client.post(reverse("signup"), {"email": "dup3@example.com", "password1": "StrongPass123aa", "password2": "StrongPass123aa"})
        content1 = r1.content.decode().lower()
        r2 = self.client.post(reverse("signup"), {"email": "dup3@example.com", "password1": "StrongPass123aa", "password2": "StrongPass123aa"})
        content2 = r2.content.decode().lower()
        self.assertEqual("проверьте почту" in content1, "проверьте почту" in content2)

class VoteReportPermissionTests(TestCase):
    def setUp(self):
        cache.clear()
        from reviews.management.commands.seed_kg import Command as SeedCmd
        SeedCmd().handle(clear=True)
        from reviews import store as store_mod
        import reviews.views as v
        self.repo = DjangoRepository()
        self._orig = store_mod.repo
        self._orig_v = v.repo
        store_mod.repo = self.repo
        v.repo = self.repo
        self.prof = self.repo.search("Айбек")[0]["prof"]
        author = _make_confirmed_user("author_perm@example.com")
        self.author = author
        data = _valid({"course": "PermCourse"})
        rv = self.repo.add_review(self.prof.id, data, user=author, status="pending")
        from reviews.models import Review as R
        R.objects.filter(pk=rv.id).update(status="pending")
        self.pending_id = rv.id
        data2 = _valid({"course": "OwnCourse", "comment": "свой отзыв для теста голосования достаточно длинный текст"})
        rv2 = self.repo.add_review(self.prof.id, data2, user=author, status="approved")
        R.objects.filter(pk=rv2.id).update(status="approved")
        self.own_approved_id = rv2.id

    def tearDown(self):
        from reviews import store as store_mod
        import reviews.views as v
        store_mod.repo = self._orig
        v.repo = self._orig_v

    def test_vote_pending_404(self):
        user = _make_confirmed_user("voter_pending@example.com")
        self.client.force_login(user)
        r = self.client.post(reverse("review_vote", args=[self.pending_id]), {"vote": "up"})
        self.assertEqual(r.status_code, 404)

    def test_report_pending_404(self):
        user = _make_confirmed_user("reporter_pending@example.com")
        self.client.force_login(user)
        r = self.client.post(reverse("review_report", args=[self.pending_id]))
        self.assertEqual(r.status_code, 404)

    def test_vote_own_403(self):
        self.client.force_login(self.author)
        r = self.client.post(reverse("review_vote", args=[self.own_approved_id]), {"vote": "up"})
        self.assertEqual(r.status_code, 403)

    def test_report_own_403(self):
        self.client.force_login(self.author)
        r = self.client.post(reverse("review_report", args=[self.own_approved_id]))
        self.assertEqual(r.status_code, 403)

    def test_double_vote_no_change(self):
        from reviews.models import Review as R
        user = _make_confirmed_user("doublevoter@example.com")
        self.client.force_login(user)
        r = self.client.post(reverse("review_vote", args=[self.own_approved_id]), {"vote": "up"})
        self.assertIn(r.status_code, (302, 200))
        helpful_before = R.objects.get(pk=self.own_approved_id).helpful
        r2 = self.client.post(reverse("review_vote", args=[self.own_approved_id]), {"vote": "up"})
        self.assertEqual(R.objects.get(pk=self.own_approved_id).helpful, helpful_before)

    def test_three_reports_pending(self):
        from reviews.models import Review as R
        review_id = self.own_approved_id
        R.objects.filter(pk=review_id).update(status="approved", reported=0)
        for i in range(3):
            u = _make_confirmed_user(f"reporter{i}@example.com")
            self.client.force_login(u)
            self.client.post(reverse("review_report", args=[review_id]))
        self.assertEqual(R.objects.get(pk=review_id).status, "pending")

class DbConstraintTests(TransactionTestCase):
    def test_duplicate_review_integrity_error(self):
        from reviews.models import Professor, Review, School
        School.objects.all().delete()
        school = School.objects.create(name="S", slug="s", city="Бишкек")
        prof = Professor.objects.create(school=school, first_name="A", last_name="B", slug="a-b", department="Dept", title="доцент")
        user = User.objects.create_user(username="dupuser", email="dup@example.com", password="StrongPass123")
        Review.objects.create(professor=prof, course="Algo", overall=4, difficulty=3, would_take_again=True, comment="ok ok ok ok ok ok", status="approved", author=user)
        with self.assertRaises(IntegrityError):
            Review.objects.create(professor=prof, course="algo", overall=4, difficulty=3, would_take_again=True, comment="ok ok", status="approved", author=user)

    def test_overall_out_of_range_integrity(self):
        from reviews.models import Professor, Review, School
        School.objects.all().delete()
        school = School.objects.create(name="S2", slug="s2", city="Бишкек")
        prof = Professor.objects.create(school=school, first_name="C", last_name="D", slug="c-d", department="Dept", title="доцент")
        with self.assertRaises(IntegrityError):
            r = Review(professor=prof, course="X", overall=6, difficulty=3, would_take_again=True, comment="x", status="approved")
            r.save()

class CommentValidationTests(TestCase):
    def setUp(self):
        cache.clear()
        from reviews.management.commands.seed_kg import Command as SeedCmd
        SeedCmd().handle(clear=True)
        from reviews import store as store_mod
        import reviews.views as v
        self.repo = DjangoRepository()
        self._orig = store_mod.repo
        self._orig_v = v.repo
        store_mod.repo = self.repo
        v.repo = self.repo
        self.prof = self.repo.search("Айбек")[0]["prof"]
        self.user = _make_confirmed_user("commenter@example.com")
        self.client.force_login(self.user)

    def tearDown(self):
        from reviews import store as store_mod
        import reviews.views as v
        store_mod.repo = self._orig
        v.repo = self._orig_v

    def test_link_rejected(self):
        data = _valid({"comment": "Смотрите https://example.com очень полезно"})
        r = self.client.post(reverse("review_new", args=[self.prof.slug]), data)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Ссылки")

    def test_email_rejected(self):
        data = _valid({"comment": "Пишите мне на test@example.com спасибо"})
        r = self.client.post(reverse("review_new", args=[self.prof.slug]), data)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Email")

    def test_phone_rejected(self):
        data = _valid({"comment": "Звоните +996 555 123 456 спасибо"})
        r = self.client.post(reverse("review_new", args=[self.prof.slug]), data)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "телефон")

    def test_numeric_grade_accepted(self):
        data = _valid({"course": "NumericCourse", "comment": "сдал на 85 баллов в 2024 хороший курс"})
        r = self.client.post(reverse("review_new", args=[self.prof.slug]), data)
        self.assertEqual(r.status_code, 302)

    def test_html_stripped(self):
        from reviews.models import Review as R
        data = _valid({"course": "HtmlCourse", "comment": "<b>жирный</b> текст <script>alert(1)</script> нормальный отзыв для теста"})
        r = self.client.post(reverse("review_new", args=[self.prof.slug]), data)
        self.assertEqual(r.status_code, 302)
        rev = R.objects.get(course="HtmlCourse")
        self.assertNotIn("<b>", rev.comment)
        self.assertNotIn("<script>", rev.comment)

class DeleteAccountTests(TestCase):
    def setUp(self):
        cache.clear()
        from reviews import store as store_mod
        import reviews.views as v
        self.repo = DjangoRepository()
        self._orig = store_mod.repo
        self._orig_v = v.repo
        store_mod.repo = self.repo
        v.repo = self.repo

    def tearDown(self):
        from reviews import store as store_mod
        import reviews.views as v
        store_mod.repo = self._orig
        v.repo = self._orig_v

    def test_delete_leaves_reviews_anonymous(self):
        from reviews.models import Review as R
        from reviews.management.commands.seed_kg import Command as SeedCmd
        SeedCmd().handle(clear=True)
        repo = self.repo
        prof = repo.search("Айбек")[0]["prof"]
        user = _make_confirmed_user("deleter@example.com")
        self.client.force_login(user)
        data = _valid({"course": "DelCourse"})
        self.client.post(reverse("review_new", args=[prof.slug]), data)
        rev = R.objects.get(course="DelCourse")
        self.assertEqual(rev.author_id, user.id)
        r = self.client.post(reverse("delete_account"))
        self.assertEqual(r.status_code, 302)
        rev.refresh_from_db()
        self.assertIsNone(rev.author)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())
