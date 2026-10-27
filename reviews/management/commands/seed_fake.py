"""Generate many fake professors and reviews (for load tests / UI checks).

    python manage.py seed_kg
    python manage.py seed_fake --professors 3000 --reviews 30000

Names are random combinations; do not run on a real production database.
"""
import random
import uuid

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from reviews.models import Professor, Review, School, Tag, normalize_search
from reviews.repository import GRADES, TAGS
from reviews.seed import SCHOOLS

FIRST = ["Айбек", "Азамат", "Нурлан", "Эрмек", "Бакыт", "Дмитрий", "Тимур", "Руслан", "Улан", "Марат",
         "Айжан", "Гульнара", "Чолпон", "Елена", "Ольга", "Светлана", "Динара", "Асель", "Мээрим", "Жылдыз"]
LAST = ["Токтогулов", "Исаков", "Касымов", "Маматов", "Бекбоев", "Асанов", "Садыков", "Жумалиев", "Абдыкадыров",
        "Осмонов", "Сыдыков", "Турдубаев", "Петров", "Смирнов", "Ким", "Волков", "Орозбаев", "Эшимов"]
DEPTS = ["Информатика", "Математика", "Физика", "Экономика", "История", "Психология", "Лингвистика",
         "Биология", "Химия", "Право", "Международные отношения", "Менеджмент", "Медицина"]
TITLES = ["профессор", "доцент", "старший преподаватель", "преподаватель"]
COURSES = ["Алгоритмы", "Базы данных", "Математический анализ", "Общая физика", "Микроэкономика",
           "История Кыргызстана", "Английский язык", "Философия", "Органическая химия", "Статистика"]
COMMENTS = [
    "Объясняет понятно, на вопросы отвечает, критерии оценки честные и прозрачные.",
    "Много домашних заданий, но они действительно помогают понять материал курса.",
    "Лекции интересные, но на экзамене строго. Готовьтесь заранее и ходите на семинары.",
    "Сабактар кызыктуу өтөт, түшүндүрмөсү жеткиликтүү, баалоосу адилет.",
    "Читает по слайдам, критерии размыты, на экзамене были неожиданные вопросы.",
]


class Command(BaseCommand):
    help = "Сгенерировать тестовых преподавателей и отзывы (для нагрузочного теста)"

    def add_arguments(self, parser):
        parser.add_argument("--professors", type=int, default=3000)
        parser.add_argument("--reviews", type=int, default=30000)
        parser.add_argument("--seed", type=int, default=42)

    @transaction.atomic
    def handle(self, *args, **opts):
        rnd = random.Random(opts["seed"])
        schools = list(School.objects.all())
        if not schools:
            schools = [School.objects.create(name=n, city=c, slug=slugify(n, allow_unicode=True)) for n, c in SCHOOLS]
        tags = [Tag.objects.get_or_create(name=str(t))[0] for t in TAGS]

        profs = []
        taken = set(Professor.objects.values_list("slug", flat=True))
        for i in range(opts["professors"]):
            first, last, dept = rnd.choice(FIRST), rnd.choice(LAST), rnd.choice(DEPTS)
            last = f"{last}-{i}"  # unique per school (DB constraint)
            slug = slugify(f"{first} {last}", allow_unicode=True)
            while slug in taken:
                slug += "-x"
            taken.add(slug)
            profs.append(Professor(
                id=uuid.uuid4(), school=rnd.choice(schools), first_name=first, last_name=last, slug=slug,
                department=dept, title=rnd.choice(TITLES), status="approved",
                search_text=normalize_search(f"{first} {last} {dept}"),
            ))
        Professor.objects.bulk_create(profs, batch_size=1000)

        reviews, links = [], []
        TagLink = Review.tags.through
        for _ in range(opts["reviews"]):
            r = Review(
                id=uuid.uuid4(), professor=rnd.choice(profs), course=rnd.choice(COURSES),
                term=rnd.choice(["Осень 2024", "Весна 2025", "Осень 2025"]),
                overall=rnd.randint(1, 5), difficulty=rnd.randint(1, 5), would_take_again=rnd.random() > .3,
                grade=str(rnd.choice(GRADES[:7])), comment=rnd.choice(COMMENTS), status="approved",
                helpful=rnd.randint(0, 30), not_helpful=rnd.randint(0, 10),
            )
            reviews.append(r)
            for t in rnd.sample(tags, rnd.randint(0, 3)):
                links.append(TagLink(review_id=r.id, tag_id=t.id))
        Review.objects.bulk_create(reviews, batch_size=2000)
        TagLink.objects.bulk_create(links, batch_size=5000)
        self.stdout.write(self.style.SUCCESS(f"Создано: {len(profs)} преподавателей, {len(reviews)} отзывов"))
