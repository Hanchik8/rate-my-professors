from django.core.management.base import BaseCommand
from django.db import transaction

from reviews.models import Professor, Review, School, Tag
from reviews.seed import PROFESSORS, REVIEWS, SCHOOLS
from reviews.universities import sync_to_db


class Command(BaseCommand):
    help = ("Заливает все вузы КР из data/universities_kg.json и демо-преподавателей из reviews/seed.py. "
            "Повторный запуск безопасен: вузы обновляются по code, демо-данные не дублируются.")

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true",
                            help="Удалить ВСЕ вузы, преподавателей и отзывы перед заливкой (только для разработки)")
        parser.add_argument("--universities", action="store_true",
                            help="Оставлено для совместимости: вузы теперь заливаются всегда")
        parser.add_argument("--no-demo", action="store_true", help="Только вузы, без демо-преподавателей")

    @transaction.atomic
    def handle(self, *args, **opts):
        if opts.get("clear"):
            Review.objects.all().delete()
            Professor.objects.all().delete()
            School.objects.all().delete()
            Tag.objects.all().delete()

        created, updated = sync_to_db()
        self.stdout.write(f"Вузы: создано {created}, обновлено {updated}, всего {School.objects.count()}.")
        if opts.get("no_demo"):
            return

        schools = {s.code: s for s in School.objects.filter(code__in=SCHOOLS)}
        profs, new_profs = [], 0
        for si, first, last, dept, title in PROFESSORS:
            school = schools[SCHOOLS[si]]
            p = Professor.objects.filter(school=school, first_name__iexact=first, last_name__iexact=last).first()
            if p is None:
                p = Professor.objects.create(school=school, first_name=first, last_name=last,
                                             department=dept, title=title, status="approved")
                new_profs += 1
            profs.append(p)

        new_reviews = 0
        for pi, course, term, overall, diff, wta, grade, comment, tags in REVIEWS:
            prof = profs[pi]
            if Review.objects.filter(professor=prof, author__isnull=True, course=course, term=term,
                                     comment=comment).exists():
                continue
            r = Review.objects.create(
                professor=prof, course=course, term=term, overall=overall, difficulty=diff,
                would_take_again=wta, grade=grade, comment=comment, status="approved",
            )
            r.tags.add(*[Tag.objects.get_or_create(name=t)[0] for t in tags])
            new_reviews += 1
        self.stdout.write(self.style.SUCCESS(
            f"Готово: демо-преподавателей добавлено {new_profs}, отзывов добавлено {new_reviews}."))
