import re
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse


class AccessibilityRenderTests(TestCase):
    def test_base_template_renders_responsive_viewport(self):
        response = self.client.get(reverse("about"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<meta name="viewport" content="width=device-width, initial-scale=1">',
        )

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

    def test_stylesheet_prevents_narrow_viewport_overflow_and_sizes_mobile_targets(self):
        stylesheet = (
            Path(__file__).parent / "static" / "reviews" / "style.css"
        ).read_text()

        self.assertRegex(stylesheet, r"body\s*\{[^}]*overflow-wrap:\s*anywhere")
        self.assertRegex(stylesheet, r"\.nav-toggle[^}]*width:\s*2\.75rem")
        self.assertRegex(stylesheet, r"\.nav-toggle[^}]*height:\s*2\.75rem")
        self.assertIn(".message-close{min-width:2.75rem;min-height:2.75rem}", stylesheet)

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

    def test_home_navigation_marks_current_page(self):
        self.assertContains(
            self.response,
            '<a class="brand" href="/" aria-current="page">',
        )

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


TEMPLATES_DIR = Path(__file__).parent / "templates"


class TemplateSourceAccessibilityTests(TestCase):
    """Guard the template sources so new pages keep the same a11y contract."""

    def test_all_template_images_define_alt_text(self):
        for path in TEMPLATES_DIR.rglob("*.html"):
            html = path.read_text()
            for image in re.findall(r"<img\b[^>]*>", html, flags=re.IGNORECASE):
                with self.subTest(template=str(path), image=image):
                    self.assertRegex(image, r"\balt\s*=")

    def test_icon_only_controls_define_accessible_names(self):
        icon_controls = {
            "reviews/_back_to_top.html": ("back-to-top",),
            "reviews/base.html": ("nav-toggle", "message-close"),
            "reviews/professor.html": ("share-btn",),
        }
        for template, classes in icon_controls.items():
            html = (TEMPLATES_DIR / template).read_text()
            for class_name in classes:
                with self.subTest(template=template, control=class_name):
                    tags = [
                        tag for tag in re.findall(r"<[a-zA-Z][^>]*>", html)
                        if re.search(rf'class="[^"]*\b{re.escape(class_name)}\b', tag)
                    ]
                    self.assertTrue(tags, f"{class_name} control not found")
                    for tag in tags:
                        self.assertIn("aria-label", tag)


class ProfessorPageAccessibilityTests(TestCase):
    """The rendered professor page exposes labels on its icon/action buttons."""

    def setUp(self):
        from . import store as store_mod
        from . import views as views_mod
        from .repository import InMemoryRepository
        from .tests import _repo_review

        self._orig_repo = store_mod.repo
        self._orig_view_repo = views_mod.repo
        self.repo = InMemoryRepository()
        store_mod.repo = self.repo
        views_mod.repo = self.repo
        school = self.repo.add_school("Университет доступности", "Бишкек")
        self.prof = self.repo.add_professor(
            school.id, "Айбек", "Токтосунов", "Информатика", "доцент"
        )
        self.repo.add_review(self.prof.id, _repo_review(), status="approved")

    def tearDown(self):
        from . import store as store_mod
        from . import views as views_mod

        store_mod.repo = self._orig_repo
        views_mod.repo = self._orig_view_repo

    def test_professor_page_icon_buttons_have_aria_labels(self):
        response = self.client.get(reverse("professor", args=[self.prof.slug]))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        buttons = re.findall(r"<button\b[^>]*>", html, flags=re.IGNORECASE)
        self.assertTrue(buttons, "Professor page rendered no buttons")
        for button in buttons:
            with self.subTest(button=button):
                self.assertIn("aria-label", button)
        # Voting and share controls are labeled explicitly.
        self.assertContains(response, 'aria-label="Полезно: Алгоритмы (0)"')
        self.assertContains(response, 'aria-label="Бесполезно: Алгоритмы (0)"')
        self.assertContains(response, 'aria-label="Поделиться: Айбек Токтосунов"')


class SchoolPaginationAccessibilityTests(TestCase):
    def setUp(self):
        from . import store as store_mod
        from . import views as views_mod
        from .constants import PAGE_SIZE
        from .repository import InMemoryRepository

        self._orig_repo = store_mod.repo
        self._orig_view_repo = views_mod.repo
        self.repo = InMemoryRepository()
        store_mod.repo = self.repo
        views_mod.repo = self.repo
        self.school = self.repo.add_school("Университет доступности", "Бишкек")
        for index in range(PAGE_SIZE + 1):
            self.repo.add_professor(
                self.school.id,
                f"Имя{index}",
                f"Фамилия{index}",
                "Кафедра",
                "доцент",
            )

    def tearDown(self):
        from . import store as store_mod
        from . import views as views_mod

        store_mod.repo = self._orig_repo
        views_mod.repo = self._orig_view_repo

    def test_school_pagination_links_have_descriptive_labels(self):
        response = self.client.get(reverse("school_detail", args=[self.school.slug]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Страница 2 из 2"')
        self.assertContains(response, '<span aria-current="page">Страница 1 из 2</span>')

    def test_school_previous_page_link_is_labeled(self):
        response = self.client.get(
            reverse("school_detail", args=[self.school.slug]),
            {"page": 2},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Страница 1 из 2"')
        self.assertContains(response, '<span aria-current="page">Страница 2 из 2</span>')
