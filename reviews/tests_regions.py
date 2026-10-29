"""Regions of Kyrgyzstan, the 75-university catalog and the region/city filter."""
from django.core.cache import cache
from django.db.migrations.executor import MigrationExecutor
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from . import geo
from .django_repo import DjangoRepository
from .models import School
from .repository import InMemoryRepository
from .seed import seed
from .universities import load_universities, sync_to_db


class _MemoryRepoCase(TestCase):
    def setUp(self):
        import reviews.views as v
        from reviews import store as store_mod

        cache.clear()
        self.repo = InMemoryRepository()
        seed(self.repo)
        self._orig, self._orig_v = store_mod.repo, v.repo
        store_mod.repo = v.repo = self.repo

    def tearDown(self):
        import reviews.views as v
        from reviews import store as store_mod

        store_mod.repo, v.repo = self._orig, self._orig_v
        cache.clear()


class GeoTests(TestCase):
    def test_parse_place(self):
        self.assertEqual(geo.parse_place("r:chuy"), ("chuy", ""))
        self.assertEqual(geo.parse_place("Токмок"), ("", "Токмок"))
        self.assertEqual(geo.parse_place("r:nowhere"), ("", ""))

    def test_city_region_mapping(self):
        self.assertEqual(geo.region_for_city("Бишкек"), "bishkek")
        self.assertEqual(geo.region_for_city("Каракол"), "issyk-kul")
        self.assertEqual(geo.region_for_city("Атлантида"), "")

    def test_build_locations_lists_every_region_once(self):
        repo = InMemoryRepository()
        seed(repo)
        locations = geo.build_locations(repo.schools())
        self.assertEqual([loc["code"] for loc in locations], geo.REGION_CODES)
        for loc in locations:
            names = [c["name"] for c in loc["cities"]]
            self.assertEqual(len(names), len(set(names)))


class UniversityCatalogTests(TestCase):
    def test_data_file_has_75_unique_institutions(self):
        universities = load_universities()
        self.assertEqual(len(universities), 75)
        self.assertEqual(len({u["code"] for u in universities}), 75)
        for u in universities:
            self.assertIn(u["region"], geo.REGION_CODES, u["code"])

    def test_memory_seed_contains_all_universities(self):
        repo = InMemoryRepository()
        seed(repo)
        self.assertEqual(len(repo.schools()), 75)

    def test_sync_to_db_is_idempotent(self):
        created, updated = sync_to_db()
        self.assertEqual((created, updated), (75, 0))
        self.assertEqual(sync_to_db(), (0, 0))
        self.assertEqual(School.objects.count(), 75)

    def test_school_region_is_filled_from_city(self):
        school = School.objects.create(name="Тестовый вуз", slug="test-vuz", city="Токмок")
        self.assertEqual(school.region, "chuy")


class RegionSearchTests(_MemoryRepoCase):
    def test_memory_search_by_region(self):
        results = self.repo.search("", region="osh-city")
        self.assertTrue(results)
        self.assertTrue(all(r["school"].region == "osh-city" for r in results))

    def test_django_search_by_region_matches_memory(self):
        from reviews.management.commands.seed_kg import Command

        Command().handle(clear=True)
        django_repo = DjangoRepository()
        names = sorted(r["prof"].full_name for r in django_repo.search("", region="osh-city"))
        expected = sorted(r["prof"].full_name for r in self.repo.search("", region="osh-city"))
        self.assertEqual(names, expected)
        self.assertTrue(names)

    def test_home_filters_by_whole_region(self):
        r = self.client.get(reverse("home"), {"city": "r:osh-city"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Бакыт")
        self.assertNotContains(r, "Айбек")
        self.assertContains(r, 'value="r:chuy"')

    def test_home_region_query_param_from_school_pages(self):
        r = self.client.get(reverse("home"), {"region": "osh-city"})
        self.assertContains(r, "Бакыт")
        self.assertNotContains(r, "Айбек")

    def test_home_school_select_is_grouped_by_region(self):
        r = self.client.get(reverse("home"))
        self.assertContains(r, "<optgroup", count=None)
        self.assertContains(r, 'data-region="bishkek"')

    def test_school_page_links_to_its_city(self):
        school = next(s for s in self.repo.schools() if s.code == "oshsu")
        r = self.client.get(reverse("school_detail", args=[school.slug]))
        self.assertContains(r, "?city=%D0%9E%D1%88")


class MigrationGraphTests(TestCase):
    def test_single_leaf_node(self):
        executor = MigrationExecutor(connection)
        leaves = [n for n in executor.loader.graph.leaf_nodes() if n[0] == "reviews"]
        self.assertEqual(len(leaves), 1)
