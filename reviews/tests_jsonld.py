"""Structured data on professor detail pages."""
import json
from dataclasses import replace

from django.test import TestCase
from django.urls import reverse

from .repository import InMemoryRepository


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
