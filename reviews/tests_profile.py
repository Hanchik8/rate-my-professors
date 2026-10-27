"""Profile page access, ownership, moderation status and i18n tests."""
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .django_repo import DjangoRepository
from .repository import InMemoryRepository

PASSWORD = "pass12345"


def _review_data(course, comment):
    return {
        "course": course,
        "term": "Осень 2026",
        "overall": 4,
        "difficulty": 3,
        "would_take_again": True,
        "grade": "A",
        "comment": comment,
        "tags": ["Интересные лекции"],
    }


class ProfileViewTestMixin:
    def _make_repo(self):
        raise NotImplementedError

    def setUp(self):
        super().setUp()
        import reviews.views as views
        from reviews import store

        self.repo = self._make_repo()
        self._original_store_repo = store.repo
        self._original_view_repo = views.repo
        store.repo = self.repo
        views.repo = self.repo
        school = self.repo.add_school("Тестовый университет", "Бишкек")
        self.prof = self.repo.add_professor(
            school.id, "Иван", "Петров", "Физика", "доцент"
        )
        self.user = self._user("owner@example.com")

    def tearDown(self):
        import reviews.views as views
        from reviews import store

        store.repo = self._original_store_repo
        views.repo = self._original_view_repo
        super().tearDown()

    @staticmethod
    def _user(email):
        return User.objects.create_user(
            username=email, email=email, password=PASSWORD
        )

    def test_profile_requires_login(self):
        url = reverse("profile")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
        self.assertEqual(parse_qs(urlparse(response.url).query)["next"], [url])

    def test_menu_links_to_profile_only_for_authenticated_users(self):
        profile_url = reverse("profile")
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, f'href="{profile_url}"')

        self.client.force_login(self.user)
        response = self.client.get(reverse("home"))
        self.assertContains(response, f'href="{profile_url}"')
        self.assertContains(response, "Мой профиль")

    def test_profile_shows_only_own_reviews_with_every_status(self):
        other_user = self._user("other@example.com")
        for course, status in (
            ("Ожидающий предмет", "pending"),
            ("Опубликованный предмет", "approved"),
            ("Отклонённый предмет", "rejected"),
        ):
            self.repo.add_review(
                self.prof.id,
                _review_data(course, f"Комментарий: {course}"),
                user=self.user,
                status=status,
            )
        self.repo.add_review(
            self.prof.id,
            _review_data("Чужой предмет", "Комментарий другого пользователя"),
            user=other_user,
            status="approved",
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("profile"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "reviews/profile.html")
        self.assertEqual(len(response.context["reviews"]), 3)
        self.assertEqual(
            {row["review"].author_id for row in response.context["reviews"]},
            {self.user.id},
        )
        for text in (
            "Ожидающий предмет",
            "Опубликованный предмет",
            "Отклонённый предмет",
            "На проверке",
            "Опубликован",
            "Отклонён",
            "Иван Петров",
            "Тестовый университет",
        ):
            self.assertContains(response, text)
        self.assertNotContains(response, "Чужой предмет")
        self.assertNotContains(response, "Комментарий другого пользователя")

    def test_profile_has_empty_state(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("profile"))
        self.assertContains(response, "owner@example.com")
        self.assertContains(response, "Вы ещё не оставляли отзывов.")
        self.assertNotContains(response, 'class="review profile-review"')

    def test_profile_heading_and_status_are_translated(self):
        self.repo.add_review(
            self.prof.id,
            _review_data("Алгоритмы", "Отзыв для проверки перевода"),
            user=self.user,
            status="pending",
        )
        self.client.force_login(self.user)
        for language, heading, status in (
            ("ru", "Мой профиль", "На проверке"),
            ("ky", "Менин профилим", "Текшерилүүдө"),
            ("en", "My profile", "Under review"),
        ):
            with self.subTest(language=language):
                self.client.post(
                    reverse("set_language"),
                    {"language": language, "next": reverse("profile")},
                )
                response = self.client.get(reverse("profile"))
                self.assertContains(response, heading)
                self.assertContains(response, status)


class MemoryProfileViewTests(ProfileViewTestMixin, TestCase):
    def _make_repo(self):
        return InMemoryRepository()


class DjangoProfileViewTests(ProfileViewTestMixin, TestCase):
    def _make_repo(self):
        return DjangoRepository()
