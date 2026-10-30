"""Render test for the home page's pagination include."""
import re
from html import unescape
from urllib.parse import parse_qs, urlsplit

from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase


class PaginationRenderTests(SimpleTestCase):
    def test_renders_window_edges_and_preserves_filters(self):
        page_obj = Paginator(list(range(250)), 10).get_page(5)
        request = RequestFactory().get("/", {
            "q": "смит",
            "department": "Физика",
            "sort": "reviews",
            "page": "5",
        })

        html = render_to_string(
            "reviews/_pagination.html",
            {"page_obj": page_obj, "request": request},
        )

        self.assertRegex(html, r'aria-current="page"[^>]*>5</span>')
        self.assertIn("…", html)
        for label in ("Первая", "Назад", "Вперёд", "Последняя"):
            self.assertIn(f">{label}</a>", html)

        match = re.search(r'href="([^"]*page=6[^"]*)"', html)
        self.assertIsNotNone(match)
        query = parse_qs(urlsplit(unescape(match.group(1))).query)
        self.assertEqual(query, {
            "q": ["смит"],
            "department": ["Физика"],
            "sort": ["reviews"],
            "page": ["6"],
        })
