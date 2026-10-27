"""ORM-backed repository with the same API as InMemoryRepository.

Performance rules used here:
* lists are built with ONE query: ratings are computed by the database
  (annotate Avg/Count), never by calling stats() per professor (N+1);
* lists are lazy (LazyResults) so the Paginator only loads the current page;
* writes that can race (votes, reviews, reports) rely on unique constraints
  in the database plus atomic F() updates instead of "check, then write".
"""
import hashlib

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, F, FloatField, Q
from django.db.models.functions import Coalesce
from django.utils.text import slugify

from .geo import build_locations, filter_schools, region_for_city
from .models import Professor, Report, Review, School, Tag, Vote, normalize_search
from .repository import Professor as DCProf
from .repository import Review as DCReview
from .repository import School as DCSchool
from .repository import _tone

APPROVED = Q(reviews__status="approved")


def _cached(key, builder):
    """Cache read-heavy results for READ_CACHE_SECONDS (0 = no cache)."""
    ttl = getattr(settings, "READ_CACHE_SECONDS", 0)
    if not ttl:
        return builder()
    key = "rd:" + hashlib.sha256(key.encode()).hexdigest()[:32]
    value = cache.get(key)
    if value is None:
        value = builder()
        cache.set(key, value, ttl)
    return value


class LazyResults:
    """A list-like wrapper around a queryset: len() is a COUNT query and
    slicing loads only that slice. Paginator works with it directly."""

    def __init__(self, queryset, convert, cache_prefix=None):
        self._qs = queryset
        self._convert = convert
        self._prefix = cache_prefix
        self._count = None

    def count(self):
        if self._count is None:
            if self._prefix:
                self._count = _cached(self._prefix + ":count", self._qs.count)
            else:
                self._count = self._qs.count()
        return self._count

    def __len__(self):
        return self.count()

    def __bool__(self):
        return self.count() > 0

    def _load(self, start, stop):
        return [self._convert(obj) for obj in self._qs[start:stop]]

    def __getitem__(self, item):
        if isinstance(item, slice):
            start, stop = item.start or 0, item.stop
            if stop is None:
                stop = self.count()
            if self._prefix:
                return _cached(f"{self._prefix}:{start}:{stop}", lambda: self._load(start, stop))
            return self._load(start, stop)
        return self._load(item, item + 1)[0]

    def __iter__(self):
        return iter(self[0:self.count()])


def _stats_from_row(count, overall, difficulty):
    if not count:
        return {"count": 0, "overall": 0, "difficulty": 0, "tone": "none"}
    overall = round(overall, 1)
    return {"count": count, "overall": overall, "difficulty": round(difficulty, 1), "tone": _tone(overall)}


class DjangoRepository:

    # ---------- writes ----------
    def add_school(self, name, city, region="", code="", slug="", **extra):
        slug = slug or code or slugify(name, allow_unicode=True) or slugify(name) or name.lower().replace(" ", "-")
        base, i = slug, 1
        while School.objects.filter(slug=slug).exists():
            slug = f"{base}-{i}"
            i += 1
        return self._school_to_dc(School.objects.create(
            name=name, slug=slug, city=city, region=region or region_for_city(city), code=code or None, **extra))

    def add_professor(self, school_id, first, last, department, title, status="approved", user=None):
        first, last = first.strip(), last.strip()
        school = School.objects.get(pk=school_id)
        dup = Professor.objects.filter(
            school=school, first_name__iexact=first, last_name__iexact=last,
        ).exclude(status="rejected")
        if dup.exists():
            raise ValueError("duplicate professor")
        base = slugify(f"{first} {last}", allow_unicode=True) or slugify(f"{first} {last}") or "professor"
        for attempt in range(20):
            slug = base if attempt == 0 else f"{base}-{attempt}"
            if Professor.objects.filter(slug=slug).exists():
                continue
            try:
                with transaction.atomic():
                    p = Professor.objects.create(
                        school=school, first_name=first, last_name=last, slug=slug,
                        department=department.strip(), title=title, status=status, created_by=user,
                    )
                return self._prof_to_dc(p)
            except IntegrityError:
                # someone created the same professor or took the slug a moment ago
                if dup.exists():
                    raise ValueError("duplicate professor")
        raise ValueError("could not allocate slug")

    def add_review(self, professor_id, data, user=None, status=None):
        course = (data.get("course") or "").strip()
        if status is None:
            status = "pending" if user is not None else "approved"
        if user is not None and Review.objects.filter(
            professor_id=professor_id, author=user, course__iexact=course,
        ).exists():
            raise ValueError("duplicate review")
        try:
            with transaction.atomic():
                r = Review.objects.create(
                    professor_id=professor_id, course=course, term=(data.get("term") or "").strip(),
                    overall=data["overall"], difficulty=data["difficulty"],
                    would_take_again=data["would_take_again"], grade=data.get("grade", ""),
                    comment=data["comment"], status=status, author=user,
                )
                tags = [Tag.objects.get_or_create(name=str(t))[0] for t in data.get("tags", [])]
                if tags:
                    r.tags.add(*tags)
        except IntegrityError:
            # unique constraint caught a parallel double submit
            raise ValueError("duplicate review")
        return self._review_to_dc(r)

    def vote(self, review_id, helpful, user=None):
        """One vote per user per review, enforced by the DB unique constraint."""
        with transaction.atomic():
            if user is not None:
                try:
                    with transaction.atomic():
                        Vote.objects.create(review_id=review_id, user=user, helpful=helpful)
                except IntegrityError:
                    raise ValueError("already voted")
            field = "helpful" if helpful else "not_helpful"
            Review.objects.filter(pk=review_id).update(**{field: F(field) + 1})

    def report(self, review_id, user=None):
        with transaction.atomic():
            if user is not None:
                try:
                    with transaction.atomic():
                        Report.objects.create(review_id=review_id, user=user)
                except IntegrityError:
                    return  # already reported by this user
            Review.objects.filter(pk=review_id).update(reported=F("reported") + 1)

    def approve_review(self, review_id):
        Review.objects.filter(pk=review_id).update(status="approved")

    def approve_professor(self, professor_id):
        Professor.objects.filter(pk=professor_id).update(status="approved")

    # ---------- reads ----------
    def schools(self):
        return _cached("schools:v2", lambda: [self._school_to_dc(s) for s in School.objects.all()])

    def cities(self):
        # order_by() drops Meta.ordering ("name"): otherwise DISTINCT runs over (city, name)
        # and every school brings its own copy of the city
        return _cached("cities", lambda: sorted(School.objects.order_by().values_list("city", flat=True).distinct()))

    def locations(self):
        # built from the cached school list; labels are translated per request, so not cached
        return build_locations(self.schools())

    def schools_in(self, region="", city=""):
        return filter_schools(self.schools(), region, city)

    def school(self, school_id):
        s = School.objects.filter(pk=school_id).first()
        return self._school_to_dc(s) if s else None

    def school_by_slug(self, slug):
        s = School.objects.filter(slug=slug).first()
        return self._school_to_dc(s) if s else None

    def professor(self, slug):
        p = Professor.objects.filter(slug=slug, status="approved").first()
        return self._prof_to_dc(p) if p else None

    def professor_any(self, slug):
        p = Professor.objects.filter(slug=slug).first()
        return self._prof_to_dc(p) if p else None

    def professor_by_id(self, professor_id):
        p = Professor.objects.filter(pk=professor_id).first()
        return self._prof_to_dc(p) if p else None

    def professors_for_school(self, school_id):
        return [self._prof_to_dc(p) for p in Professor.objects.filter(school_id=school_id, status="approved")]

    def review(self, review_id):
        try:
            r = Review.objects.filter(pk=review_id).first()
        except (ValidationError, ValueError):  # malformed UUID in the URL
            return None
        return self._review_to_dc(r) if r else None

    def reviews_for(self, professor_id, sort="newest", include_pending=False):
        qs = Review.objects.filter(professor_id=professor_id)
        if not include_pending:
            qs = qs.filter(status="approved")
        if sort == "helpful":
            qs = qs.annotate(score=F("helpful") - F("not_helpful")).order_by("-score", "-created_at")
        else:
            qs = qs.order_by("-created_at")
        # no result cache here: vote counts must update immediately
        return LazyResults(qs.prefetch_related("tags"), self._review_to_dc)

    def all_reviews(self, include_pending=False):
        qs = Review.objects.all().prefetch_related("tags")
        if not include_pending:
            qs = qs.filter(status="approved")
        return [self._review_to_dc(r) for r in qs]

    def stats(self, professor_id):
        return _cached(f"stats:{professor_id}", lambda: self._stats(professor_id))

    def _stats(self, professor_id):
        qs = Review.objects.filter(professor_id=professor_id, status="approved")
        agg = qs.aggregate(
            n=Count("id"), overall=Avg("overall"), difficulty=Avg("difficulty"),
            wta=Count("id", filter=Q(would_take_again=True)),
        )
        n = agg["n"]
        dist = dict(qs.values_list("overall").annotate(c=Count("id")).values_list("overall", "c"))
        distribution = [{"score": s, "count": dist.get(s, 0), "pct": round(100 * dist.get(s, 0) / n) if n else 0}
                        for s in range(5, 0, -1)]
        if not n:
            return {"count": 0, "overall": 0, "difficulty": 0, "wta_pct": None, "tone": "none",
                    "distribution": distribution, "top_tags": []}
        top_tags = list(
            Tag.objects.filter(review__professor_id=professor_id, review__status="approved")
            .annotate(c=Count("id")).order_by("-c", "name").values_list("name", flat=True)[:3]
        )
        overall = round(agg["overall"], 1)
        return {
            "count": n, "overall": overall, "difficulty": round(agg["difficulty"], 1),
            "wta_pct": round(100 * agg["wta"] / n), "tone": _tone(overall),
            "distribution": distribution, "top_tags": top_tags,
        }

    def school_stats(self, school_id):
        return _cached(f"school_stats:{school_id}", lambda: self._school_stats(school_id))

    def _school_stats(self, school_id):
        profs = Professor.objects.filter(school_id=school_id, status="approved")
        rows = list(profs.annotate(n=Count("reviews", filter=APPROVED), avg=Avg("reviews__overall", filter=APPROVED))
                    .values_list("n", "avg"))
        total = sum(n for n, _ in rows)
        avgs = [avg for n, avg in rows if n]
        return {
            "prof_count": len(rows),
            "review_count": total,
            "avg_overall": round(sum(round(a, 1) for a in avgs) / len(avgs), 1) if avgs else 0,
        }

    def departments_for_school(self, school_id):
        return _cached(f"departments:{school_id}", lambda: list(
            Professor.objects.filter(school_id=school_id, status="approved")
            .order_by("department").values_list("department", flat=True).distinct()
        ))

    def search(self, q="", school_slug="", city="", region=""):
        """Approved professors with ratings, best first. Returns a lazy list."""
        qs = Professor.objects.filter(status="approved").select_related("school")
        if school_slug:
            qs = qs.filter(school__slug=school_slug)
        if city:
            qs = qs.filter(school__city=city)
        if region:
            qs = qs.filter(school__region=region)
        q = normalize_search(q)
        for word in q.split()[:5]:
            qs = qs.filter(search_text__contains=word)
        qs = qs.annotate(
            n_reviews=Count("reviews", filter=APPROVED),
            avg_overall=Coalesce(Avg("reviews__overall", filter=APPROVED), 0.0, output_field=FloatField()),
            avg_difficulty=Avg("reviews__difficulty", filter=APPROVED),
        ).order_by("-avg_overall", "last_name", "first_name", "id")
        return LazyResults(qs, self._search_row, cache_prefix=f"search:{q}|{school_slug}|{city}|{region}")

    def _search_row(self, p):
        return {
            "prof": self._prof_to_dc(p),
            "school": self._school_to_dc(p.school),
            "stats": _stats_from_row(p.n_reviews, p.avg_overall, p.avg_difficulty),
        }

    def has_user_reviewed(self, professor_id, course, user):
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        return Review.objects.filter(professor_id=professor_id, course__iexact=course.strip(), author=user).exists()

    def has_user_voted(self, review_id, user):
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        return Vote.objects.filter(review_id=review_id, user=user).exists()

    # ---------- ORM object -> plain dataclass used by views/templates ----------
    @staticmethod
    def _school_to_dc(s):
        return DCSchool(id=str(s.pk), name=s.name, slug=s.slug, city=s.city, region=s.region, code=s.code or "",
                        name_ky=s.name_ky, name_en=s.name_en, short_name=s.short_name, kind=s.kind,
                        website=s.website)

    @staticmethod
    def _prof_to_dc(p):
        return DCProf(id=str(p.pk), school_id=str(p.school_id), first_name=p.first_name, last_name=p.last_name,
                      slug=p.slug, department=p.department, title=p.title, status=p.status)

    @staticmethod
    def _review_to_dc(r):
        return DCReview(
            professor_id=str(r.professor_id), course=r.course, term=r.term,
            overall=r.overall, difficulty=r.difficulty, would_take_again=r.would_take_again,
            grade=r.grade, comment=r.comment, tags=[str(t.name) for t in r.tags.all()],
            id=str(r.pk), helpful=r.helpful, not_helpful=r.not_helpful,
            created_at=r.created_at, status=r.status, author_id=r.author_id,
            reported=r.reported,
        )
