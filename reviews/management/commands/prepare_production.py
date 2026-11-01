"""Wipe all demo / test content before launch.

    python manage.py prepare_production --yes

Deletes every review, vote and report, every professor (real ones are imported
afterwards with import_professors), and every non-staff user. Universities and
staff accounts stay. Without --yes it only prints what would be deleted.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from reviews.models import Professor, Report, Review, School, Vote


class Command(BaseCommand):
    help = "Очистить базу от демо-данных перед запуском продакшена."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Действительно удалить")
        parser.add_argument("--keep-users", action="store_true", help="Не удалять обычных пользователей")

    def handle(self, yes=False, keep_users=False, **opts):
        User = get_user_model()
        users = User.objects.filter(is_staff=False, is_superuser=False)
        counts = {"отзывы": Review.objects.count(), "голоса": Vote.objects.count(),
                  "жалобы": Report.objects.count(), "преподаватели": Professor.objects.count(),
                  "пользователи (не staff)": 0 if keep_users else users.count()}
        for k, v in counts.items():
            self.stdout.write(f"{k}: {v}")
        if not yes:
            self.stdout.write("Ничего не удалено. Запустите с --yes.")
            return
        with transaction.atomic():
            Report.objects.all().delete()
            Vote.objects.all().delete()
            Review.objects.all().delete()
            Professor.objects.all().delete()
            if not keep_users:
                users.delete()
        self.stdout.write(f"Готово. Вузов осталось: {School.objects.count()}, преподавателей: 0, отзывов: 0.")
