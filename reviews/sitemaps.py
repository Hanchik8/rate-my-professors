"""Sitemap definitions backed by the active repository.

Using the repository API instead of the ORM directly keeps the sitemap working
with both storage backends (in-memory and Django ORM), just like the views.
"""
from django.contrib.sitemaps import Sitemap
from django.urls import reverse

from .store import get_repo


class HomeSitemap(Sitemap):
    changefreq = "daily"
    priority = 1.0

    def items(self):
        return ["home"]

    def location(self, item):
        return reverse("home")


class SchoolSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.8

    def items(self):
        return get_repo().schools()

    def location(self, school):
        return reverse("school_detail", args=[school.slug])


class ProfessorSitemap(Sitemap):
    changefreq = "weekly"
    priority = 0.6

    def items(self):
        return [row["prof"] for row in get_repo().search("")]

    def location(self, professor):
        return reverse("professor", args=[professor.slug])


sitemaps = {
    "home": HomeSitemap,
    "schools": SchoolSitemap,
    "professors": ProfessorSitemap,
}