"""Health, error-page, metadata, structured-data, and sitemap checks."""
import json
from dataclasses import replace
from unittest import mock

from django.template import Context, Template
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from . import store as store_mod
from .django_repo import DjangoRepository
from .repository import InMemoryRepository
from .seed import seed


class HealthEndpointTests(TestCase):
    """GET /health/ — liveness probe for the container orchestrator."""

    def test_health_returns_200_json_ok(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(json.loads(response.content), {"status": "ok"})


@override_settings(DEBUG=False)
class Custom404PageTests(TestCase):
    """Custom 404.html is rendered (not Django's debug page) in every locale."""

    # (language code, expected translated heading from 404.html)
    CASES = [
        ("ru", "Страница не найдена"),
        ("ky", "Барак табылган жок"),
        ("en", "Page not found"),
    ]

    def _get_missing(self, lang):
        return self.client.get(
            "/no-such-page/", HTTP_ACCEPT_LANGUAGE=lang
        )

    def test_404_status_custom_template_and_content_per_language(self):
        for lang, heading in self.CASES:
            with self.subTest(language=lang):
                response = self._get_missing(lang)
                self.assertEqual(response.status_code, 404)
                self.assertTemplateUsed(response, "404.html")
                self.assertContains(response, heading, status_code=404)


@override_settings(DEBUG=False)
class ClientErrorResponseTests(TestCase):
    """Exercise the real request/response cycle with DEBUG disabled.

    ``raise_request_exception=False`` mirrors production: an unhandled view
    exception must become a rendered 500 response instead of propagating into
    the caller (which is what the default test client does).
    """

    def test_404_through_client_uses_custom_template_without_debug_details(self):
        response = self.client.get("/no-such-page/")
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertContains(response, "Страница не найдена", status_code=404)
        self.assertNotContains(response, "Traceback", status_code=404)

    def test_500_through_client_uses_custom_template(self):
        client = Client(raise_request_exception=False)
        with mock.patch(
            "reviews.views.get_or_set", side_effect=RuntimeError("boom")
        ):
            response = client.get(reverse("home"))
        self.assertEqual(response.status_code, 500)
        self.assertTemplateUsed(response, "500.html")
        self.assertContains(response, "Ошибка сервера", status_code=500)
        self.assertContains(response, "Вернуться на главную", status_code=500)

    def test_500_through_client_does_not_leak_exception_details(self):
        client = Client(raise_request_exception=False)
        with mock.patch(
            "reviews.views.get_or_set", side_effect=RuntimeError("secret-detail")
        ):
            response = client.get(reverse("home"))
        self.assertEqual(response.status_code, 500)
        self.assertNotContains(response, "secret-detail", status_code=500)
        self.assertNotContains(response, "Traceback", status_code=500)


class ErrorHandlerRenderTests(TestCase):
    """Rendered error handlers stay custom and the 500 page needs no context."""

    def test_handler404_renders_custom_template(self):
        from django.conf.urls import handler404
        from django.test import RequestFactory
        from django.utils import translation

        request = RequestFactory().get("/missing/", HTTP_ACCEPT_LANGUAGE="ru")
        with translation.override("ru"):
            response = handler404(request, Exception("missing"))
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Страница не найдена", status_code=404)
        self.assertContains(response, "Вернуться на главную", status_code=404)

    def test_handler500_renders_custom_template_without_db_queries(self):
        from django.conf.urls import handler500
        from django.db import connection
        from django.test import RequestFactory
        from django.test.utils import CaptureQueriesContext
        from django.utils import translation

        request = RequestFactory().get("/boom/")
        with translation.override("ru"), CaptureQueriesContext(connection) as queries:
            response = handler500(request)
        self.assertEqual(response.status_code, 500)
        self.assertContains(response, "Ошибка сервера", status_code=500)
        self.assertContains(response, "Что-то пошло не так", status_code=500)
        self.assertContains(response, "Вернуться на главную", status_code=500)
        self.assertEqual(len(queries), 0)


class ProjectErrorHandlerWiringTests(TestCase):
    """config.urls must explicitly wire the project's 404/500 handlers."""

    def test_urlconf_exposes_project_handlers(self):
        from config import urls
        from reviews import views

        self.assertIs(urls.handler404, views.handler404)
        self.assertIs(urls.handler500, views.handler500)

    def test_project_handler404_renders_custom_template(self):
        from django.test import RequestFactory
        from django.utils import translation

        from config.urls import handler404

        request = RequestFactory().get("/missing/", HTTP_ACCEPT_LANGUAGE="ru")
        with translation.override("ru"):
            response = handler404(request, Exception("missing"))
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Страница не найдена", status_code=404)
        self.assertContains(response, "Вернуться на главную", status_code=404)

    def test_project_handler404_works_without_exception_argument(self):
        from django.test import RequestFactory

        from config.urls import handler404

        response = handler404(RequestFactory().get("/missing/"))
        self.assertEqual(response.status_code, 404)

    def test_project_handler500_renders_custom_template_without_db_queries(self):
        from django.db import connection
        from django.test import RequestFactory
        from django.test.utils import CaptureQueriesContext
        from django.utils import translation

        from config.urls import handler500

        request = RequestFactory().get("/boom/")
        with translation.override("ru"), CaptureQueriesContext(connection) as queries:
            response = handler500(request)
        self.assertEqual(response.status_code, 500)
        self.assertContains(response, "Ошибка сервера", status_code=500)
        self.assertContains(response, "Что-то пошло не так", status_code=500)
        self.assertContains(response, "Вернуться на главную", status_code=500)
        self.assertEqual(len(queries), 0)


@override_settings(DEBUG=False)
class ErrorPageTests(TestCase):
    LANGUAGES = (
        ("ru", "Страница не найдена", "Ошибка сервера"),
        ("ky", "Барак табылган жок", "Сервер катасы"),
        ("en", "Page not found", "Server error"),
    )

    def test_404_page_uses_custom_template_and_active_language(self):
        for language, heading, _ in self.LANGUAGES:
            with self.subTest(language=language):
                response = self.client.get(
                    "/missing-error-page/", HTTP_ACCEPT_LANGUAGE=language
                )

                self.assertEqual(response.status_code, 404)
                self.assertTemplateUsed(response, "404.html")
                self.assertContains(response, heading, status_code=404)
                self.assertNotContains(response, "Traceback", status_code=404)

    def test_404_page_uses_language_from_request_header(self):
        for language, heading, _ in self.LANGUAGES:
            with self.subTest(language=language):
                response = self.client.get(
                    "/missing-error-page/", HTTP_ACCEPT_LANGUAGE=language
                )

                self.assertEqual(response.status_code, 404)
                self.assertTemplateUsed(response, "404.html")
                self.assertContains(response, heading, status_code=404)

    def test_500_page_uses_custom_template_and_active_language_without_leaks(self):
        for language, _, heading in self.LANGUAGES:
            with self.subTest(language=language), translation.override(language):
                # Exercise handler500 deterministically without depending on a
                # particular view failing or exposing exception details.
                from django.test import RequestFactory
                from config.urls import handler500

                request = RequestFactory().get("/error/")
                response = handler500(request)
                response.templates = [type("RenderedTemplate", (), {"name": "500.html"})()]

                self.assertEqual(response.status_code, 500)
                self.assertTemplateUsed(response, "500.html")
                self.assertContains(response, heading, status_code=500)
                self.assertNotContains(response, "Traceback", status_code=500)


DEFAULT_DESCRIPTION = (
    "ProfLens — отзывы о преподавателях вузов Кыргызстана: "
    "рейтинги, сложность курсов и советы студентов."
)

MEMORY_NOTICE = "Демо-данные сбрасываются при рестарте (memory-режим)."


class MetaTagsTestMixin:
    def setUp(self):
        import reviews.views as views

        self._orig_store_repo = store_mod.repo
        self._orig_views_repo = views.repo
        self.repo = InMemoryRepository()
        seed(self.repo)
        store_mod.repo = self.repo
        views.repo = self.repo

    def tearDown(self):
        import reviews.views as views

        store_mod.repo = self._orig_store_repo
        views.repo = self._orig_views_repo

    def html(self, url, **params):
        response = self.client.get(url, params)
        self.assertEqual(response.status_code, 200)
        return response.content.decode()


class HomeMetaTagsTests(MetaTagsTestMixin, TestCase):
    def test_default_meta_tags_are_rendered(self):
        html = self.html(reverse("home"))
        self.assertIn("<title>ProfLens</title>", html)
        self.assertIn(
            f'<meta name="description" content="{DEFAULT_DESCRIPTION}">', html
        )
        self.assertIn('<meta property="og:title" content="ProfLens">', html)
        self.assertIn(
            f'<meta property="og:description" content="{DEFAULT_DESCRIPTION}">', html
        )

    def test_meta_blocks_can_be_overridden(self):
        template = Template(
            '{% extends "reviews/base.html" %}'
            "{% block title %}Custom title{% endblock %}"
            "{% block description %}Custom description{% endblock %}"
            "{% block og_title %}Custom og title{% endblock %}"
            "{% block og_description %}Custom og description{% endblock %}"
        )
        html = template.render(Context({}))
        self.assertIn("<title>Custom title</title>", html)
        self.assertIn('<meta name="description" content="Custom description">', html)
        self.assertIn('<meta property="og:title" content="Custom og title">', html)
        self.assertIn(
            '<meta property="og:description" content="Custom og description">', html
        )


class ProfessorMetaTagsTests(MetaTagsTestMixin, TestCase):
    def test_professor_meta_tags_describe_the_professor(self):
        row = self.repo.search("")[0]
        prof = row["prof"]
        school = self.repo.school(prof.school_id)
        html = self.html(reverse("professor", args=[prof.slug]))

        title = f"{prof.full_name} — ProfLens"
        description = (
            f"Отзывы студентов о преподавателе {prof.full_name} "
            f"({prof.department}, {school.name}): рейтинг, сложность и советы."
        )
        self.assertIn(f"<title>{title}</title>", html)
        self.assertIn(f'<meta property="og:title" content="{title}">', html)
        self.assertIn(f'<meta name="description" content="{description}">', html)
        self.assertIn(f'<meta property="og:description" content="{description}">', html)


class SchoolMetaTagsTests(MetaTagsTestMixin, TestCase):
    def test_school_meta_tags_describe_the_school(self):
        school = self.repo.schools()[0]
        html = self.html(reverse("school_detail", args=[school.slug]))

        title = f"{school.name} — ProfLens"
        description = (
            f"Преподаватели и отзывы студентов вуза {school.name} "
            f"({school.city}): рейтинги, кафедры и советы."
        )
        self.assertIn(f"<title>{title}</title>", html)
        self.assertIn(f'<meta property="og:title" content="{title}">', html)
        self.assertIn(f'<meta name="description" content="{description}">', html)
        self.assertIn(f'<meta property="og:description" content="{description}">', html)


class FooterRepositoryModeTests(TestCase):
    def test_memory_repository_shows_notice(self):
        repo = InMemoryRepository()
        seed(repo)
        with mock.patch.object(store_mod, "repo", repo):
            response = self.client.get(reverse("home"))
        self.assertContains(response, MEMORY_NOTICE)

    def test_django_repository_hides_notice(self):
        with mock.patch.object(store_mod, "repo", DjangoRepository()):
            response = self.client.get(reverse("home"))
        self.assertNotContains(response, MEMORY_NOTICE)

    @override_settings(REPO_BACKEND="django")
    def test_django_backend_setting_hides_notice(self):
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, MEMORY_NOTICE)

    @override_settings(REPO_BACKEND="memory")
    def test_memory_backend_setting_shows_notice(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, MEMORY_NOTICE)


class ProfessorJsonLdTests(TestCase):
    def setUp(self):
        import reviews.views as views
        from reviews import store

        self.original_repo = views.repo
        self.original_store_repo = store.repo
        self.repo = InMemoryRepository()
        views.repo = store.repo = self.repo
        self.school = self.repo.add_school("Test University", "Bishkek")
        self.prof = self.repo.add_professor(
            self.school.id, "Ada", "Lovelace", "Mathematics", "professor"
        )

    def tearDown(self):
        import reviews.views as views
        from reviews import store

        views.repo = self.original_repo
        store.repo = self.original_store_repo

    def get_schema(self):
        response = self.client.get(reverse("professor", args=[self.prof.slug]))
        self.assertEqual(response.status_code, 200)
        marker = '<script type="application/ld+json">'
        self.assertIn(marker, response.content.decode())
        encoded = response.content.decode().split(marker, 1)[1].split("</script>", 1)[0]
        return response, json.loads(encoded)

    def test_schema_has_person_and_aggregate_rating(self):
        self.repo.add_review(self.prof.id, {
            "course": "Logic", "term": "Spring", "overall": 4,
            "difficulty": 3, "would_take_again": True, "grade": "A",
            "comment": "Excellent course", "tags": [],
        }, status="approved")

        _, schema = self.get_schema()

        self.assertEqual(schema["@type"], "Person")
        self.assertEqual(schema["name"], "Ada Lovelace")
        self.assertEqual(schema["aggregateRating"], {
            "@type": "AggregateRating", "ratingValue": 4.0, "reviewCount": 1,
        })

    def test_script_terminator_in_name_is_escaped(self):
        self.prof = replace(self.prof, first_name="</script>& <")
        self.repo._professors[self.prof.id] = self.prof
        _, schema = self.get_schema()

        self.assertEqual(schema["name"], "</script>& < Lovelace")
        response = self.client.get(reverse("professor", args=[self.prof.slug]))
        markup = response.content.decode()
        jsonld = markup.split('<script type="application/ld+json">', 1)[1].split("</script>", 1)[0]
        self.assertIn(r"\u003c/script\u003e\u0026 \u003c", jsonld)

    def test_empty_aggregate_is_omitted_without_reviews(self):
        _, schema = self.get_schema()

        self.assertNotIn("aggregateRating", schema)


class SitemapTestMixin:
    def make_repo(self):
        raise NotImplementedError

    def setUp(self):
        self._orig_repo = store_mod.repo
        store_mod.repo = self.make_repo()

    def tearDown(self):
        store_mod.repo = self._orig_repo

class InMemorySitemapTests(SitemapTestMixin, TestCase):
    def make_repo(self):
        repo = InMemoryRepository()
        seed(repo)
        return repo

    # robots.txt, sitemap index, and all section responses are exercised in
    # every locale by SitemapXmlI18nTests; this backend-specific class checks
    # the actual seeded URLs below.
    def test_seeded_schools_and_professors_appear_in_sitemaps(self):
        schools = self.client.get("/sitemap-schools.xml")
        professors = self.client.get("/sitemap-professors.xml")
        for school in store_mod.repo.schools():
            self.assertContains(schools, reverse("school_detail", args=[school.slug]))
        for row in store_mod.repo.search(""):
            self.assertContains(professors, reverse("professor", args=[row["prof"].slug]))


class DjangoSitemapTests(SitemapTestMixin, TestCase):
    def make_repo(self):
        repo = DjangoRepository()
        school = repo.add_school("Тестовый университет", "Бишкек")
        repo.add_professor(school.id, "Иван", "Петров", "Информатика", "доцент")
        return repo

    def test_django_backend_urls_appear_in_sitemaps(self):
        school = store_mod.repo.schools()[0]
        professor = store_mod.repo.search("")[0]["prof"]
        self.assertContains(self.client.get("/sitemap-schools.xml"), reverse("school_detail", args=[school.slug]))
        self.assertContains(self.client.get("/sitemap-professors.xml"), reverse("professor", args=[professor.slug]))


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
