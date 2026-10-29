from django.core.management.base import BaseCommand
from reviews.models import Professor, Review


class Command(BaseCommand):
    help = "Проверяет целостность данных: осиротевшие записи и дубли профессоров"

    def handle(self, *args, **options):
        orphaned_professors = Professor.objects.filter(school__isnull=True).values_list("pk", flat=True)
        orphaned_reviews = Review.objects.filter(professor__isnull=True).values_list("pk", flat=True)

        self.stdout.write("Осиротевшие записи:")
        professor_ids = list(orphaned_professors)
        review_ids = list(orphaned_reviews)
        self.stdout.write(f"  Профессора без вуза: {len(professor_ids)}")
        for pk in professor_ids:
            self.stdout.write(f"    Professor {pk}")
        self.stdout.write(f"  Отзывы без профессора: {len(review_ids)}")
        for pk in review_ids:
            self.stdout.write(f"    Review {pk}")

        # Django has no portable normalized grouping alias; group names in Python
        # so case and surrounding whitespace differences are reported as duplicates.
        professors_by_name = {}
        for professor in Professor.objects.select_related("school").order_by("school_id", "pk"):
            name = (professor.first_name.strip().casefold(), professor.last_name.strip().casefold())
            professors_by_name.setdefault((professor.school_id, name), []).append(professor)

        duplicates = [group for group in professors_by_name.values() if len(group) > 1]
        self.stdout.write(f"Дубли профессоров: {len(duplicates)}")
        for group in duplicates:
            first = group[0]
            self.stdout.write(
                f"  {first.school.name}: {first.first_name.strip()} {first.last_name.strip()}"
            )
            for professor in group:
                self.stdout.write(f"    Professor {professor.pk}")
