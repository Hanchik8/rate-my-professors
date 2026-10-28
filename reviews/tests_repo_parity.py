"""Behavioral parity checks for the in-memory and ORM repositories."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from .django_repo import DjangoRepository
from .repository import InMemoryRepository


class RepositoryParityMixin:
    def make_repo(self):
        raise NotImplementedError

    def setUp(self):
        super().setUp()
        self.repo = self.make_repo()
        self.school = self.repo.add_school("Паритет университет", "Бишкек")
        self.other_school = self.repo.add_school("Другой университет", "Ош")
        self.high = self.repo.add_professor(
            self.school.id, "Анна", "Высокая", "Математика", "профессор"
        )
        self.low = self.repo.add_professor(
            self.school.id, "Борис", "Низкий", "Физика", "доцент"
        )
        self.extra = self.repo.add_professor(
            self.other_school.id, "Вера", "Средняя", "История", "доцент"
        )
        self.user = (get_user_model().objects.create_user(
            username="parity-user", password="irrelevant"
        ) if isinstance(self, DjangoRepositoryParityTests) else type("User", (), {"id": 901})())

    def test_review_vote_report_search_rating_and_page_limits(self):
        review = self.repo.add_review(self.high.id, {
            "course": "Алгебра", "term": "Осень", "overall": 5,
            "difficulty": 2, "would_take_again": True, "grade": "A",
            "comment": "Отличный курс", "tags": ["Понятные критерии"],
        }, user=self.user)
        self.assertEqual(review.status, "pending")
        self.repo.approve_review(review.id)
        self.repo.vote(review.id, True, user=self.user)
        self.repo.report(review.id, user=self.user, reason="spam")
        self.repo.report(review.id, user=self.user, reason="other")
        review = self.repo.review(review.id)
        self.assertEqual((review.status, review.helpful, review.not_helpful, review.reported),
                         ("approved", 1, 0, 1))

        self.repo.add_review(self.high.id, {
            "course": "Геометрия", "term": "Весна", "overall": 3,
            "difficulty": 4, "would_take_again": False, "grade": "B",
            "comment": "Непросто", "tags": [],
        })
        self.repo.add_review(self.low.id, {
            "course": "Механика", "term": "Осень", "overall": 4,
            "difficulty": 3, "would_take_again": True, "grade": "A",
            "comment": "Хорошо", "tags": [],
        })

        search = self.repo.search(q="высокая")
        self.assertEqual([row["prof"].full_name for row in search], ["Анна Высокая"])
        rows = self.repo.search(sort="rating")
        self.assertEqual([row["prof"].full_name for row in rows],
                         ["Анна Высокая", "Борис Низкий", "Вера Средняя"])
        self.assertEqual([row["stats"]["overall"] for row in rows], [4.0, 4.0, 0])
        self.assertEqual([row["stats"]["count"] for row in rows], [2, 1, 0])
        # Exercise the common page/limit contract on repository result sets.
        self.assertEqual([r["prof"].full_name for r in rows[:2]],
                         ["Анна Высокая", "Борис Низкий"])
        self.assertEqual([r["prof"].full_name for r in rows[2:4]], ["Вера Средняя"])
        self.assertEqual(len(rows[:1]), 1)

    def test_duplicate_professor_normalizes_case_and_whitespace(self):
        original = self.repo.add_professor(
            self.school.id, "Иван  Иванович", "Петров", "Физика", "доцент"
        )
        for first, last in (
            ("иван иванович", "ПЕТРОВ"),
            ("  ИВАН   ИВАНОВИЧ  ", "  петров  "),
            ("Иван Иванович", "Петров"),
        ):
            with self.subTest(first=first, last=last):
                with self.assertRaises(ValueError):
                    self.repo.add_professor(
                        self.school.id, first, last, "Математика", "профессор"
                    )
        allowed = self.repo.add_professor(
            self.other_school.id, "  иван  иванович ", " ПЕТРОВ ", "Физика", "доцент"
        )
        self.assertNotEqual(allowed.id, original.id)
        self.assertEqual(allowed.school_id, self.other_school.id)

    def test_add_professor_defaults_status_and_moderation_visibility(self):
        self.assertEqual(self.high.status, "approved")
        pending = self.repo.add_professor(
            self.school.id, "Павел", "Ожидающий", "Химия", "доцент", status="pending"
        )
        self.assertEqual(pending.status, "pending")
        self.assertIsNone(self.repo.professor(pending.slug))
        self.assertEqual(self.repo.professor_any(pending.slug).id, pending.id)
        self.assertEqual(self.repo.search("Ожидающий"), [])
        self.assertNotIn("Химия", self.repo.departments())
        self.assertEqual(
            {p.id for p in self.repo.professors_for_school(self.school.id)},
            {self.high.id, self.low.id},
        )

        self.repo.approve_professor(pending.id)
        self.assertEqual(self.repo.professor(pending.slug).id, pending.id)
        self.assertEqual(
            [row["prof"].id for row in self.repo.search("Ожидающий")], [pending.id]
        )
        self.assertIn("Химия", self.repo.departments())

    def test_add_professor_duplicate_pending_and_cross_school_slug(self):
        pending = self.repo.add_professor(
            self.school.id, "Игорь", "Скрытый", "Химия", "доцент", status="pending"
        )
        for first, last in (("Игорь", "Скрытый"), (" игорь ", " СКРЫТЫЙ ")):
            with self.subTest(first=first, last=last):
                with self.assertRaises(ValueError):
                    self.repo.add_professor(
                        self.school.id, first, last, "Физика", "профессор"
                    )

        allowed = self.repo.add_professor(
            self.other_school.id, "Игорь", "Скрытый", "Химия", "доцент"
        )
        self.assertNotEqual(allowed.id, pending.id)
        self.assertNotEqual(allowed.slug, pending.slug)
        self.assertEqual(allowed.school_id, self.other_school.id)

    def _approved_review(self, professor_id, course, user=None):
        review = self.repo.add_review(professor_id, {
            "course": course, "term": "Осень", "overall": 5,
            "difficulty": 2, "would_take_again": True, "grade": "A",
            "comment": "Отзыв для проверки голосования.", "tags": [],
        }, user=user)
        self.repo.approve_review(review.id)
        return self.repo.review(review.id)

    def test_vote_repeat_same_and_opposite_is_rejected(self):
        review = self._approved_review(self.high.id, "Голосование", user=self.user)
        self.assertFalse(self.repo.has_user_voted(review.id, self.user))
        self.repo.vote(review.id, True, user=self.user)
        self.assertTrue(self.repo.has_user_voted(review.id, self.user))
        self.assertEqual(self.repo.review(review.id).helpful, 1)

        with self.assertRaises(ValueError):
            self.repo.vote(review.id, True, user=self.user)
        with self.assertRaises(ValueError):
            self.repo.vote(review.id, False, user=self.user)

        after = self.repo.review(review.id)
        self.assertEqual((after.helpful, after.not_helpful), (1, 0))
        self.assertEqual(self.repo.reviews_for(self.high.id, sort="helpful")[0].id, review.id)

    def test_vote_on_own_review_preserves_author_and_counts_once(self):
        review = self._approved_review(self.low.id, "Свой курс", user=self.user)
        self.assertEqual(review.author_id, self.user.id)
        self.repo.vote(review.id, True, user=self.user)
        after = self.repo.review(review.id)
        self.assertEqual(
            (after.author_id, after.helpful, after.not_helpful),
            (self.user.id, 1, 0),
        )
        self.assertTrue(self.repo.has_user_voted(review.id, self.user))


class InMemoryRepositoryParityTests(RepositoryParityMixin, TestCase):
    def make_repo(self):
        return InMemoryRepository()


class DjangoRepositoryParityTests(RepositoryParityMixin, TestCase):
    def make_repo(self):
        return DjangoRepository()
