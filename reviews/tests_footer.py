from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from . import store
from .django_repo import DjangoRepository
from .repository import InMemoryRepository
from .seed import seed

MEMORY_NOTICE = "Демо-данные сбрасываются при рестарте (memory-режим)."


class FooterRepositoryModeTests(TestCase):
    def test_memory_repository_shows_notice(self):
        repo = InMemoryRepository()
        seed(repo)
        with mock.patch.object(store, "repo", repo):
            response = self.client.get(reverse("home"))
        self.assertContains(response, MEMORY_NOTICE)

    def test_django_repository_hides_notice(self):
        with mock.patch.object(store, "repo", DjangoRepository()):
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
