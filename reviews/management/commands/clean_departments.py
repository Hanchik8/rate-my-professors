"""Apply the import's department normalization to professors already in the database."""
from django.core.management.base import BaseCommand
from django.db import transaction

from reviews.models import Professor

from .import_professors import _school_names, clean_department


class Command(BaseCommand):
    help = "Убирает служебные пометки и название вуза из поля «кафедра», чинит латиницу в кириллических словах."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, dry_run=False, **opts):
        changed = []
        for prof in Professor.objects.select_related("school").iterator():
            new = clean_department(prof.department, _school_names(prof.school))
            if new != prof.department:
                changed.append((prof, new))
        for prof, new in changed[:15]:
            self.stdout.write(f"{prof.department!r} -> {new!r}")
        if not dry_run and changed:
            with transaction.atomic():
                for prof, new in changed:
                    prof.department = new
                    prof.save(update_fields=["department"])
            try:
                from reviews.caching import invalidate_catalog_cache
                invalidate_catalog_cache()
            except Exception:  # cache helpers differ between branches
                pass
        self.stdout.write(f"{'Будет изменено' if dry_run else 'Изменено'}: {len(changed)}")
