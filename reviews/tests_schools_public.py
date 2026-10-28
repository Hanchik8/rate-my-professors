from django.test import TestCase
from django.urls import reverse

from . import store as store_mod
from . import views as views_mod
from .repository import InMemoryRepository


class SchoolPagePublicTests(TestCase):
    def setUp(self):
        self._orig_repo = store_mod.repo
        self._orig_view_repo = views_mod.repo
        self.repo = InMemoryRepository()
        store_mod.repo = self.repo
        views_mod.repo = self.repo
        self.school = self.repo.add_school("Публичный университет", "Бишкек")

    def tearDown(self):
        store_mod.repo = self._orig_repo
        views_mod.repo = self._orig_view_repo

    def test_school_page_status_and_content_type(self):
        response = self.client.get(reverse("school_detail", args=[self.school.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response["Content-Type"])

    def test_school_page_displays_school_and_empty_state(self):
        response = self.client.get(reverse("school_detail", args=[self.school.slug]))

        self.assertContains(response, self.school.name)
        self.assertContains(response, self.school.city)
        self.assertContains(response, "Пока нет кафедр.")
        self.assertContains(response, "Пока нет преподавателей.")
        self.assertContains(response, reverse("add_professor"))

    def test_school_page_returns_404_for_unknown_school(self):
        response = self.client.get(reverse("school_detail", args=["unknown-school"]))

        self.assertEqual(response.status_code, 404)
