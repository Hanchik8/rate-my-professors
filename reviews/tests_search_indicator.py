"""Coverage for the search-results header and its reset link."""
import re
from html import unescape
from urllib.parse import parse_qs, urlsplit

from django.core.cache import cache
from django.urls import reverse

from .tests import _MemoryRepoTestCase


class SearchIndicatorTests(_MemoryRepoTestCase):
    def test_query_shows_header_and_reset_link_preserving_filters(self):
        cache.clear()
        response = self.client.get(
            "/", {"q": "Айбек", "city": "Бишкек", "sort": "reviews"}
        )
        total = len(response.context["results"])

        self.assertContains(response, f"Результаты по запросу «Айбек»: {total}")
        self.assertContains(response, ">Сбросить поиск</a>")

        html = response.content.decode()
        anchor = re.search(r'<a\b[^>]*class="reset-search"[^>]*>', html)
        self.assertIsNotNone(anchor)
        href = unescape(re.search(r'href="([^"]*)"', anchor.group(0)).group(1))
        target = urlsplit(href)
        query = parse_qs(target.query)

        self.assertEqual(target.path, reverse("home"))
        self.assertNotIn("q", query)
        self.assertEqual(query.get("city"), ["Бишкек"])
        self.assertEqual(query.get("sort"), ["reviews"])

        without_query = self.client.get("/")
        self.assertNotContains(without_query, "Результаты по запросу")
        self.assertNotContains(without_query, "Сбросить поиск")
        cache.clear()