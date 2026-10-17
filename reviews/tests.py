from django.test import SimpleTestCase
from django.urls import reverse

from .store import repo

VALID = {"course": "cs 101", "term": "Fall 2026", "overall": "4", "difficulty": "3",
         "would_take_again": "yes", "grade": "A", "tags": ["Amazing lectures"],
         "comment": "Clear lectures and fair exams, would recommend."}


class SmokeTests(SimpleTestCase):
    def test_home_and_search(self):
        self.assertContains(self.client.get(reverse("home")), "Maya Okafor")
        r = self.client.get(reverse("home"), {"q": "physics"})
        self.assertContains(r, "Luis Ferreira")
        self.assertNotContains(r, "Maya Okafor")

    def test_professor_page_and_404(self):
        self.assertContains(self.client.get(reverse("professor", args=["maya-okafor"])), "CS101")
        self.assertEqual(self.client.get(reverse("professor", args=["nobody"])).status_code, 404)

    def test_post_review(self):
        prof = repo.professor("grace-whitfield")
        before = repo.stats(prof.id)["count"]
        r = self.client.post(reverse("review_new", args=[prof.slug]), VALID)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(repo.stats(prof.id)["count"], before + 1)
        bad = self.client.post(reverse("review_new", args=[prof.slug]), {**VALID, "comment": "too short"})
        self.assertEqual(bad.status_code, 200)
        self.assertEqual(repo.stats(prof.id)["count"], before + 1)

    def test_vote(self):
        prof = repo.professor("tom-albrecht")
        review = repo.reviews_for(prof.id)[0]
        before = review.helpful
        r = self.client.post(reverse("review_vote", args=[review.id]), {"vote": "up"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(review.helpful, before + 1)
