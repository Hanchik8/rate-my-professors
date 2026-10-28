from django.test import TestCase
from django.urls import reverse

from . import store as store_mod
from .django_repo import DjangoRepository
from .repository import InMemoryRepository
from .seed import seed


class SitemapTestMixin:
    def make_repo(self):
        raise NotImplementedError

    def setUp(self):
        self._orig_repo = store_mod.repo
        store_mod.repo = self.make_repo()

    def tearDown(self):
        store_mod.repo = self._orig_repo

    def test_robots_txt(self):
        response = self.client.get("/robots.txt")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response["Content-Type"])
        self.assertContains(response, "Sitemap:")
        self.assertContains(response, reverse("sitemap_index"))

    def test_sitemap_index(self):
        response = self.client.get(reverse("sitemap_index"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("xml", response["Content-Type"])
        for section in ("home", "schools", "professors"):
            self.assertContains(response, f"/sitemap-{section}.xml")

    def test_home_sitemap(self):
        response = self.client.get("/sitemap-home.xml")
        self.assertEqual(response.status_code, 200)
        self.assertIn("xml", response["Content-Type"])
        self.assertContains(response, reverse("home"))

    def test_schools_sitemap(self):
        response = self.client.get("/sitemap-schools.xml")
        self.assertEqual(response.status_code, 200)
        self.assertIn("xml", response["Content-Type"])
        for school in store_mod.repo.schools():
            self.assertContains(response, reverse("school_detail", args=[school.slug]))

    def test_professors_sitemap(self):
        response = self.client.get("/sitemap-professors.xml")
        self.assertEqual(response.status_code, 200)
        self.assertIn("xml", response["Content-Type"])
        for row in store_mod.repo.search(""):
            self.assertContains(response, reverse("professor", args=[row["prof"].slug]))


class InMemorySitemapTests(SitemapTestMixin, TestCase):
    def make_repo(self):
        repo = InMemoryRepository()
        seed(repo)
        return repo


class DjangoSitemapTests(SitemapTestMixin, TestCase):
    def make_repo(self):
        repo = DjangoRepository()
        school = repo.add_school("Тестовый университет", "Бишкек")
        repo.add_professor(school.id, "Иван", "Петров", "Информатика", "доцент")
        return repo


class EmptyRepositorySitemapTests(SitemapTestMixin, TestCase):
    def make_repo(self):
        return InMemoryRepository()

    def test_school_and_professor_sitemaps_are_empty(self):
        for section in ("schools", "professors"):
            with self.subTest(section=section):
                response = self.client.get(f"/sitemap-{section}.xml")
                self.assertEqual(response.status_code, 200)
                self.assertIn("xml", response["Content-Type"])
                self.assertNotContains(response, "<url>")

    def test_robots_txt_works_with_empty_repository(self):
        response = self.client.get(reverse("robots_txt"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "User-agent: *")
        self.assertContains(response, reverse("sitemap_index"))
