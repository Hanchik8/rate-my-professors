import re
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class AccessibilityRenderTests(TestCase):
    def test_base_template_renders_skip_link_and_labeled_icon_buttons(self):
        response = self.client.get(reverse("about"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="skip-link" href="#main-content"')
        self.assertContains(response, 'id="main-content" tabindex="-1"')
        self.assertContains(response, 'class="nav-toggle"')
        self.assertContains(response, 'aria-label="Меню"')
        self.assertContains(response, 'aria-hidden="true"')

    def test_rendered_pages_do_not_include_images_without_alt_text(self):
        for url_name in ("home", "about", "rules"):
            with self.subTest(page=url_name):
                response = self.client.get(reverse(url_name))
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                for image in re.findall(r"<img\b[^>]*>", html, flags=re.IGNORECASE):
                    self.assertRegex(image, r"\balt\s*=", msg=f"Image missing alt: {image}")

    def test_stylesheet_has_visible_keyboard_focus(self):
        stylesheet = (
            Path(__file__).parent / "static" / "reviews" / "style.css"
        ).read_text()

        self.assertIn(":focus-visible", stylesheet)
        self.assertRegex(stylesheet, r":focus-visible\s*\{[^}]*outline:\s*3px")

    def test_focus_visible_covers_links_buttons_and_search_fields(self):
        stylesheet = (
            Path(__file__).parent / "static" / "reviews" / "style.css"
        ).read_text()
        self.assertRegex(stylesheet, r"(?s):focus-visible\s*\{[^}]*outline:\s*3px")
        self.assertRegex(stylesheet, r"(?s):focus-visible\s*\{[^}]*outline:\s*3px")
        for selector in ("a", "button", "input", "select", "textarea"):
            self.assertIn(selector, stylesheet)

    def test_non_field_errors_are_announced_with_alert_role(self):
        User.objects.create_user(
            username="a11y@example.com",
            email="a11y@example.com",
            password="pass12345",
        )
        response = self.client.post(
            reverse("login"),
            {"username": "a11y@example.com", "password": "wrongpass1"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="errorlist nonfield"')
        self.assertContains(response, 'role="alert"')


class HomeAccessibilityTests(TestCase):
    """The rendered home page exposes the base template's a11y hooks."""

    def setUp(self):
        self.response = self.client.get(reverse("home"))
        self.html = self.response.content.decode()

    def test_home_declares_document_language(self):
        self.assertEqual(self.response.status_code, 200)
        self.assertContains(self.response, '<html lang="ru"')

    def test_home_has_skip_link_and_focusable_main_target(self):
        self.assertContains(
            self.response, 'class="skip-link" href="#main-content"'
        )
        self.assertContains(self.response, 'id="main-content" tabindex="-1"')

    def test_home_icon_button_and_navigation_have_accessible_names(self):
        self.assertContains(self.response, 'class="nav-toggle"')
        self.assertContains(self.response, 'aria-expanded="false"')
        self.assertContains(self.response, 'aria-controls="site-nav"')
        self.assertContains(self.response, 'aria-label="Меню"')
        self.assertContains(
            self.response,
            '<nav class="nav" id="site-nav" aria-label="Основная навигация">',
        )
        self.assertContains(self.response, 'aria-label="Язык"')

    def test_home_search_landmark_and_controls_are_labeled(self):
        self.assertContains(self.response, 'role="search"')
        for label in ("Поиск", "Город", "Вуз", "Кафедра", "Сортировка", "Найти"):
            with self.subTest(label=label):
                self.assertContains(self.response, f'aria-label="{label}"')

    def test_home_images_have_alt_text(self):
        for image in re.findall(r"<img\b[^>]*>", self.html, flags=re.IGNORECASE):
            self.assertRegex(image, r"\balt\s*=", msg=f"Image missing alt: {image}")

    def test_home_decorative_icons_are_hidden_from_assistive_tech(self):
        for icon in re.findall(r'<span class="(?:brand-mark|burger)"[^>]*>', self.html):
            with self.subTest(icon=icon):
                self.assertIn('aria-hidden="true"', icon)
