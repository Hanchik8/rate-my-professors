from django.core.management.base import BaseCommand
from reviews.models import School, Professor, Tag, Review


class Command(BaseCommand):
    help = "Заливает вузы + демо-преподавателей в БД (idempotent для вузов)"

    def add_arguments(self, parser):
        parser.add_argument("--clear", action="store_true", help="Очистить существующие данные перед заливкой")
        parser.add_argument("--file", default="data/kg_universities.json", help="Путь к JSON с вузами")

    def handle(self, *args, **opts):
        if opts["clear"]:
            Review.objects.all().delete()
            Professor.objects.all().delete()
            School.objects.all().delete()
            Tag.objects.all().delete()

        # 1) вузы — idempotent
        from reviews.management.commands.load_universities import Command as LoadCmd
        load = LoadCmd()
        load.handle(file=opts.get("file") or "data/kg_universities.json")

        # 2) преподаватели/отзывы — только если их нет (или после --clear)
        if Professor.objects.exists() and not opts["clear"]:
            self.stdout.write(self.style.WARNING("Преподаватели уже есть. Используйте --clear для перезаливки."))
            self.stdout.write(self.style.SUCCESS(f"Вузов: {School.objects.count()}, преподавателей: {Professor.objects.count()}, отзывов: {Review.objects.count()}"))
            return

        from django.utils.text import slugify
        from reviews.seed import PROFESSORS_BY_SCHOOL, REVIEWS

        # map schools by short_name
        schools_by_short = {s.short_name: s for s in School.objects.all() if s.short_name}
        schools_by_name = {s.name: s for s in School.objects.all()}
        profs = []
        for short, first, last, dept, title in PROFESSORS_BY_SCHOOL:
            school = schools_by_short.get(short) or schools_by_name.get(short)
            if not school:
                for s in School.objects.all():
                    if short in s.name or short in (s.short_name or ""):
                        school = s
                        break
            if not school:
                school = School.objects.first()
            base = slugify(f"{first} {last}", allow_unicode=True) or slugify(f"{first} {last}")
            slug = base
            i = 1
            while Professor.objects.filter(slug=slug).exists():
                slug = f"{base}-{i}"
                i += 1
            p = Professor.objects.create(school=school, first_name=first, last_name=last, slug=slug, department=dept, title=title, status="approved")
            profs.append(p)

        for pi, course, term, overall, diff, wta, grade, comment, tags in REVIEWS:
            r = Review.objects.create(
                professor=profs[pi], course=course, term=term, overall=overall, difficulty=diff,
                would_take_again=wta, grade=grade, comment=comment, status="approved",
            )
            for t in tags:
                tag, _ = Tag.objects.get_or_create(name=t)
                r.tags.add(tag)

        self.stdout.write(self.style.SUCCESS(f"Готово: вузов {School.objects.count()}, преподавателей {len(profs)}, отзывов {len(REVIEWS)}."))
