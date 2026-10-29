"""HTTP view tests for voting and review ownership."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .repository import InMemoryRepository


class VoteAndProfileViewTests(TestCase):
    def setUp(self):
        import reviews.views as views
        from reviews import store

        self.repo = InMemoryRepository()
        self.original_store_repo = store.repo
        self.original_views_repo = views.repo
        store.repo = self.repo
        views.repo = self.repo

        school = self.repo.add_school("Тестовый университет", "Бишкек")
        self.prof = self.repo.add_professor(
            school.id, "Иван", "Петров", "Физика", "доцент"
        )
        self.owner = self._user("owner@example.com")
        self.review = self.repo.add_review(
            self.prof.id,
            {
                "course": "Физика",
                "term": "Осень 2026",
                "overall": 4,
                "difficulty": 3,
                "would_take_again": True,
                "grade": "A",
                "comment": "Комментарий для проверки доступа.",
                "tags": [],
            },
            user=self.owner,
            status="approved",
        )

    def tearDown(self):
        import reviews.views as views
        from reviews import store

        store.repo = self.original_store_repo
        views.repo = self.original_views_repo

    @staticmethod
    def _user(email):
        return User.objects.create_user(username=email, email=email, password="pass12345")

    def test_anonymous_vote_redirects_to_login_without_changing_counts(self):
        url = reverse("review_vote", args=[self.review.id])

        response = self.client.post(url, {"vote": "up"})

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)
        current = self.repo.review(self.review.id)
        self.assertEqual((current.helpful, current.not_helpful), (0, 0))

    def test_repeated_vote_does_not_increment_count_twice(self):
        voter = self._user("voter@example.com")
        self.client.force_login(voter)
        url = reverse("review_vote", args=[self.review.id])

        self.client.post(url, {"vote": "up"})
        response = self.client.post(url, {"vote": "up"}, follow=True)

        self.assertContains(response, "Вы уже голосовали за этот отзыв.")
        current = self.repo.review(self.review.id)
        self.assertEqual((current.helpful, current.not_helpful), (1, 0))

    def test_user_cannot_edit_or_delete_another_users_review(self):
        stranger = self._user("stranger@example.com")
        self.client.force_login(stranger)

        edit = self.client.get(reverse("review_edit", args=[self.review.id]))
        delete = self.client.post(reverse("review_delete", args=[self.review.id]))

        self.assertEqual(edit.status_code, 404)
        self.assertEqual(delete.status_code, 404)
        self.assertIsNotNone(self.repo.review(self.review.id))
