"""Generate many fake professors and reviews (for load tests / UI checks).

    python manage.py seed_kg
    python manage.py seed_fake --professors 3000 --reviews 30000
    python manage.py seed_fake --wipe --professors 3000 --reviews 30000   # replace earlier fake data

Names are realistic and unique: a gender-consistent first name, a surname in the
matching form (Асанов / Асанова, Ильин / Ильина, Ким), and sometimes a patronymic
(Асанович / Асановна). Professors are spread evenly over all universities.
Everything created here is marked is_demo=True; --wipe deletes only that
(professors with real users' reviews are kept). Real users, their reviews and
professors added by users are never touched.
"""
import random
import uuid

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from reviews.models import Professor, Review, School, Tag, normalize_search
from reviews.repository import GRADES, TAGS
from reviews.universities import sync_to_db

# names are grouped so a person reads naturally: Kyrgyz first name + Kyrgyz surname + Kyrgyz father's name, etc.
NAME_GROUPS = {
    "kg": {
        "male": ["Айбек", "Азамат", "Нурлан", "Эрмек", "Бакыт", "Улан", "Марат", "Талант", "Бектур", "Канат",
                 "Мирлан", "Эрлан", "Нурбек", "Адилет", "Жоомарт", "Кубанычбек", "Мелис", "Самат", "Темирлан",
                 "Чынгыз", "Алмаз", "Бакытбек", "Данияр", "Медер", "Тилек", "Урмат", "Аскар", "Улукбек", "Эркин",
                 "Жыргалбек"],
        "female": ["Айжан", "Гульнара", "Чолпон", "Динара", "Асель", "Мээрим", "Жылдыз", "Айгерим", "Бермет",
                   "Назира", "Айнура", "Гульмира", "Жибек", "Каныкей", "Нургуль", "Салтанат", "Толгонай", "Айпери",
                   "Бактыгуль", "Жаңыл", "Зарина", "Калыйпа", "Нуриза", "Перизат", "Сезим", "Уулкан", "Чынара",
                   "Акылай", "Элнура", "Айзада"],
        "surnames": ["Токтогулов", "Исаков", "Касымов", "Маматов", "Бекбоев", "Асанов", "Садыков", "Жумалиев",
                     "Абдыкадыров", "Осмонов", "Сыдыков", "Турдубаев", "Орозбаев", "Эшимов", "Акматов", "Алымкулов",
                     "Байтереков", "Жээналиев", "Иманалиев", "Калыков", "Кадыров", "Мамбетов", "Мырзакматов",
                     "Нурматов", "Омурбеков", "Рысбеков", "Сатыбалдиев", "Султанов", "Табылдиев", "Төрөкулов",
                     "Үсөнов", "Шаршеев", "Абдраимов", "Бообеков", "Дүйшөнбиев", "Жолдошев", "Карыпбеков",
                     "Молдокматов", "Сагынбаев", "Чотуев", "Абдылдаев", "Бакиров", "Белеков", "Дооронбеков",
                     "Ибраимов", "Кенжебаев", "Куттубаев", "Мамытов", "Мукашев", "Сариев", "Сооронбаев", "Темиров",
                     "Токтоматов", "Тургунбаев", "Чыныбаев", "Эсенгулов", "Жамгырчиев", "Кулматов", "Абдиев",
                     "Бейшеналиев"],
        "fathers": ["Асан", "Усен", "Токтогул", "Бакыт", "Нурлан", "Сагын", "Жумабек", "Айтбек", "Мамат", "Эркин",
                    "Кадыр", "Осмон", "Садык", "Талант", "Медет", "Таалай", "Бообек", "Абдыраим"],
    },
    "ru": {
        "male": ["Дмитрий", "Сергей", "Андрей", "Алексей", "Владимир", "Николай", "Игорь", "Михаил", "Павел",
                 "Виктор", "Олег", "Евгений", "Денис", "Роман", "Константин", "Юрий", "Артём"],
        "female": ["Елена", "Ольга", "Светлана", "Татьяна", "Наталья", "Ирина", "Анна", "Мария", "Екатерина",
                   "Юлия", "Людмила", "Галина", "Марина", "Надежда", "Алина", "Вера", "Оксана"],
        "surnames": ["Петров", "Смирнов", "Волков", "Кузнецов", "Попов", "Соколов", "Лебедев", "Новиков",
                     "Морозов", "Павлов", "Ильин", "Никитин", "Фомин", "Карпенко", "Бондаренко", "Ковальский",
                     "Савицкий", "Ким", "Пак", "Цой", "Шевченко", "Белов", "Орлов"],
        "fathers": ["Иван", "Петр", "Александр", "Владимир", "Михаил", "Борис", "Виктор", "Олег", "Степан"],
    },
    "other": {
        "male": ["Ильдар", "Рустам", "Фарид", "Шамиль", "Анвар", "Тимур", "Руслан", "Эмиль"],
        "female": ["Камила", "Лейла", "Дильноза", "Гузель", "Сабина", "Эльвира", "Венера", "Мира"],
        "surnames": ["Юсупов", "Рахимов", "Каримов", "Хасанов", "Мусаев", "Ибрагимов", "Алиев", "Насыров"],
        "fathers": ["Рашид", "Ахмед", "Равиль", "Карим", "Анвар", "Фарид"],
    },
}
MALE = [n for g in NAME_GROUPS.values() for n in g["male"]]
FEMALE = [n for g in NAME_GROUPS.values() for n in g["female"]]

DEPTS_BY_PROFILE = {
    "medical": ["Терапия", "Хирургия", "Анатомия", "Фармакология", "Педиатрия", "Биохимия", "Стоматология"],
    "law": ["Уголовное право", "Гражданское право", "Конституционное право", "Международное право", "Криминалистика"],
    "arts": ["Живопись", "Музыкальное искусство", "Актёрское мастерство", "Дизайн", "История искусств"],
    "agri": ["Агрономия", "Ветеринария", "Зоотехния", "Агроэкономика", "Лесное хозяйство"],
    "tech": ["Информатика", "Программная инженерия", "Электроэнергетика", "Механика", "Строительство", "Физика",
             "Математика"],
    "general": ["Информатика", "Математика", "Физика", "Экономика", "История", "Психология", "Лингвистика",
                "Биология", "Химия", "Право", "Международные отношения", "Менеджмент", "Педагогика",
                "Кыргызский язык и литература", "Английский язык"],
}
COURSES_BY_PROFILE = {
    "medical": ["Анатомия человека", "Физиология", "Биохимия", "Фармакология", "Патология"],
    "law": ["Теория государства и права", "Уголовное право", "Гражданское право", "Римское право"],
    "arts": ["Рисунок", "Композиция", "История искусств", "Сольфеджио"],
    "agri": ["Почвоведение", "Растениеводство", "Анатомия животных", "Агрохимия"],
    "tech": ["Алгоритмы", "Базы данных", "Математический анализ", "Общая физика", "Сопротивление материалов"],
    "general": ["Алгоритмы", "Математический анализ", "Микроэкономика", "История Кыргызстана", "Английский язык",
                "Философия", "Статистика", "Кыргызский язык"],
}
TITLES = ["профессор", "доцент", "старший преподаватель", "преподаватель"]
COMMENTS = [
    "Объясняет понятно, на вопросы отвечает, критерии оценки честные и прозрачные.",
    "Много домашних заданий, но они действительно помогают понять материал курса.",
    "Лекции интересные, но на экзамене строго. Готовьтесь заранее и ходите на семинары.",
    "Сабактар кызыктуу өтөт, түшүндүрмөсү жеткиликтүү, баалоосу адилет.",
    "Читает по слайдам, критерии размыты, на экзамене были неожиданные вопросы.",
    "Всегда приходит подготовленным, разбирает ошибки, к концу семестра реально чувствуешь прогресс.",
    "Требования высокие, но понятные. Если работать в течение семестра, сдать можно.",
]
TERMS = ["Осень 2024", "Весна 2025", "Осень 2025", "Весна 2026"]


def feminine_surname(male):
    """Асанов -> Асанова, Жумалиев -> Жумалиева, Ильин -> Ильина, Ковальский -> Ковальская; Ким, Карпенко stay."""
    for end, fem in (("ский", "ская"), ("цкий", "цкая"), ("ов", "ова"), ("ев", "ева"), ("ёв", "ёва"),
                     ("ин", "ина"), ("ын", "ына")):
        if male.endswith(end):
            return male[: -len(end)] + fem
    return male


def patronymic(base, female):
    return base + ("овна" if female else "ович")


def school_profile(name):
    n = name.lower()
    if any(w in n for w in ("медицин", "стоматолог", "авиценна")):
        return "medical"
    if any(w in n for w in ("юридич", "мвд", "права,")):
        return "law"
    if any(w in n for w in ("искусств", "консерватор", "художеств", "культуры и")):
        return "arts"
    if "аграр" in n:
        return "agri"
    if any(w in n for w in ("техническ", "технолог", "строительств", "авиацион", "геолог", "информатик")):
        return "tech"
    return "general"


def name_pool(rnd):
    """Every (first, last, female, group) combination once, shuffled: unique names without suffixes."""
    pool = []
    for key, g in NAME_GROUPS.items():
        pool += [(f, s, False, key) for f in g["male"] for s in g["surnames"]]
        pool += [(f, feminine_surname(s), True, key) for f in g["female"] for s in g["surnames"]]
    rnd.shuffle(pool)
    return pool


class Command(BaseCommand):
    help = "Сгенерировать тестовых преподавателей и отзывы (для нагрузочного теста и демо)"

    def add_arguments(self, parser):
        parser.add_argument("--professors", type=int, default=3000)
        parser.add_argument("--reviews", type=int, default=30000)
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--wipe", action="store_true",
                            help="Сначала удалить ранее сгенерированные (is_demo) данные")
        parser.add_argument("--patronymic-share", type=float, default=0.4,
                            help="Доля имён с отчеством (0..1)")

    def wipe(self):
        demo = Professor.objects.filter(is_demo=True, created_by__isnull=True)
        # a professor someone really reviewed stays (it is no longer only fake data)
        keep = demo.filter(reviews__author__isnull=False).values_list("id", flat=True).distinct()
        keep_ids = set(keep)
        if keep_ids:
            Professor.objects.filter(id__in=keep_ids).update(is_demo=False)
        reviews_deleted, _ = Review.objects.filter(professor__in=demo.exclude(id__in=keep_ids),
                                                   author__isnull=True).delete()
        profs_deleted, _ = demo.exclude(id__in=keep_ids).delete()
        return profs_deleted, reviews_deleted, len(keep_ids)

    @transaction.atomic
    def handle(self, *args, **opts):
        rnd = random.Random(opts["seed"])
        if opts.get("wipe"):
            p, r, kept = self.wipe()
            self.stdout.write(f"Удалено демо-записей: {p} (преподаватели и связанные отзывы), сохранено с реальными отзывами: {kept}")
        if not School.objects.exists():
            sync_to_db()
        schools = list(School.objects.all())
        tags = [Tag.objects.get_or_create(name=str(t))[0] for t in TAGS]

        taken_names = {(f.lower(), l.lower()) for f, l in Professor.objects.values_list("first_name", "last_name")}
        taken_slugs = set(Professor.objects.values_list("slug", flat=True))
        pool = [x for x in name_pool(rnd) if (x[0].lower(), x[1].lower()) not in taken_names]
        n = min(opts["professors"], len(pool))
        if n < opts["professors"]:
            self.stdout.write(self.style.WARNING(f"Уникальных имён хватает только на {n} преподавателей"))

        # spread evenly: every university gets n // len(schools) or one more
        order = [schools[i % len(schools)] for i in range(n)]
        rnd.shuffle(order)
        profiles = {s.pk: school_profile(s.name) for s in schools}

        profs = []
        for (first, last, female, group), school in zip(pool[:n], order):
            if rnd.random() < opts.get("patronymic_share", 0.4):
                first = f"{first} {patronymic(rnd.choice(NAME_GROUPS[group]['fathers']), female)}"
            dept = rnd.choice(DEPTS_BY_PROFILE[profiles[school.pk]])
            base = slugify(f"{first} {last}", allow_unicode=True) or "professor"
            slug, i = base, 2
            while slug in taken_slugs:  # slugs only (URLs), names themselves stay clean
                slug, i = f"{base}-{i}", i + 1
            taken_slugs.add(slug)
            profs.append(Professor(
                id=uuid.uuid4(), school=school, first_name=first, last_name=last, slug=slug,
                department=dept, title=rnd.choice(TITLES), status="approved", is_demo=True,
                search_text=normalize_search(f"{first} {last} {dept}"),
            ))
        Professor.objects.bulk_create(profs, batch_size=1000)

        reviews, links = [], []
        TagLink = Review.tags.through
        for _ in range(opts["reviews"] if profs else 0):
            prof = rnd.choice(profs)
            r = Review(
                id=uuid.uuid4(), professor=prof, course=rnd.choice(COURSES_BY_PROFILE[profiles[prof.school_id]]),
                term=rnd.choice(TERMS),
                overall=rnd.randint(1, 5), difficulty=rnd.randint(1, 5), would_take_again=rnd.random() > .3,
                grade=str(rnd.choice(GRADES[:7])), comment=rnd.choice(COMMENTS), status="approved",
                helpful=rnd.randint(0, 30), not_helpful=rnd.randint(0, 10),
            )
            reviews.append(r)
            for t in rnd.sample(tags, rnd.randint(0, 3)):
                links.append(TagLink(review_id=r.id, tag_id=t.id))
        Review.objects.bulk_create(reviews, batch_size=2000)
        TagLink.objects.bulk_create(links, batch_size=5000)
        self.stdout.write(self.style.SUCCESS(
            f"Создано: {len(profs)} преподавателей в {len(schools)} вузах, {len(reviews)} отзывов"))
