"""Data layer. Views talk only to a repository object, never to storage directly.

When PostgreSQL is connected, write a DjangoRepository with these same methods
(backed by models/ORM) and point reviews/store.py at it. Views stay untouched.
"""
import threading
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from statistics import mean

from django.utils.text import slugify
from django.utils.translation import get_language, gettext_lazy as _

from .geo import build_locations, city_name, filter_schools, region_for_city, region_kind, region_name

# Теги адаптированы под вузы Кыргызстана — без упоминаний коррупции
TAGS = [
    _("Строго оценивает"),
    _("Понятные критерии"),
    _("Интересные лекции"),
    _("Много домашних заданий"),
    _("Много тестов"),
    _("Групповые проекты"),
    _("Доступен вне занятий"),
    _("Даёт полезную обратную связь"),
    _("Важна посещаемость"),
    _("Вдохновляет"),
]
# Шкала, принятая в вузах КР (ECTS + зачёт)
GRADES = ["A", "B", "C", "D", "E", "FX", "F", _("Зачёт"), _("Незачёт"), _("Ещё не знаю")]


@dataclass
class School:
    id: str
    name: str
    slug: str
    city: str
    region: str = ""
    code: str = ""
    name_ky: str = ""
    name_en: str = ""
    short_name: str = ""
    kind: str = ""
    website: str = ""

    @property
    def display_name(self):
        """Name in the active UI language, falling back to the official Russian one."""
        lang = (get_language() or "ru")[:2]
        if lang == "ky" and self.name_ky:
            return self.name_ky
        if lang == "en" and self.name_en:
            return self.name_en
        return self.name

    @property
    def region_name(self):
        return region_name(self.region)

    @property
    def city_name(self):
        return city_name(self.city)

    @property
    def in_oblast(self):
        """False for Bishkek and Osh (cities of republican significance)."""
        return region_kind(self.region) == "oblast"


@dataclass
class Professor:
    id: str
    school_id: str
    first_name: str
    last_name: str
    slug: str
    department: str
    title: str
    status: str = "approved"  # pending | approved | rejected

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


@dataclass
class Review:
    professor_id: str
    course: str
    term: str
    overall: int
    difficulty: int
    would_take_again: bool
    grade: str
    comment: str
    tags: list
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    helpful: int = 0
    not_helpful: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    status: str = "approved"  # pending | approved | rejected
    author_id: int | None = None
    reported: int = 0


def _tone(overall):
    return "good" if overall >= 4 else "mid" if overall >= 3 else "bad"


def _norm(text):
    return " ".join((text or "").lower().replace("ё", "е").split())


class InMemoryRepository:
    """Demo/dev storage in process memory. Data is lost on restart and is not
    shared between gunicorn workers, so production uses DjangoRepository."""

    def __init__(self):
        self._lock = threading.Lock()
        self._schools, self._professors, self._reviews = {}, {}, {}
        # (review_id, user_id) -> "up"/"down"
        self._votes = {}
        # (professor_id, course_lower, user_id) uniqueness for review
        self._review_keys = set()

    # writes
    def add_school(self, name, city, region="", code="", slug="", **extra):
        slug = slug or code or slugify(name, allow_unicode=True) or slugify(name) or name.lower().replace(" ", "-")
        s = School(str(uuid.uuid4()), name, slug, city, region=region or region_for_city(city), code=code, **extra)
        self._schools[s.id] = s
        return s

    def add_professor(self, school_id, first, last, department, title, status="approved", user=None):
        with self._lock:
            return self._add_professor(school_id, first.strip(), last.strip(), department.strip(), title, status)

    def _add_professor(self, school_id, first, last, department, title, status):
        # защита от дубля ФИО+вуз (case-insensitive)
        for p in self._professors.values():
            if p.school_id == school_id and p.full_name.lower() == f"{first} {last}".lower() and p.status != "rejected":
                raise ValueError("duplicate professor")
        slug = slugify(f"{first} {last}", allow_unicode=True) or slugify(f"{first} {last}") or f"{first}-{last}".lower()
        # ensure unique slug
        base, i = slug, 1
        while any(p.slug == slug for p in self._professors.values()):
            slug = f"{base}-{i}"
            i += 1
        p = Professor(str(uuid.uuid4()), school_id, first, last, slug, department, title, status=status)
        self._professors[p.id] = p
        return p

    def add_review(self, professor_id, data, user=None, status=None):
        with self._lock:
            return self._add_review(professor_id, data, user, status)

    def _add_review(self, professor_id, data, user, status):
        # limit one review per professor+course per user
        course = data.get("course", "").strip()
        if user is not None and course:
            key = (professor_id, course.lower(), getattr(user, 'id', user))
            if key in self._review_keys:
                raise ValueError("duplicate review")
            self._review_keys.add(key)
        if status is None:
            # новые отзывы от залогиненных — pending, анонимные/seed — approved
            status = "pending" if user is not None else "approved"
        r = Review(
            professor_id=professor_id, course=course, term=data.get("term", ""),
            overall=data["overall"], difficulty=data["difficulty"],
            would_take_again=data["would_take_again"], grade=data.get("grade", ""),
            comment=data["comment"], tags=list(data.get("tags", [])),
            status=status, author_id=getattr(user, 'id', None) if user else None,
        )
        self._reviews[r.id] = r
        return r

    def vote(self, review_id, helpful, user=None):
        with self._lock:
            self._vote(review_id, helpful, user)

    def _vote(self, review_id, helpful, user):
        r = self._reviews[review_id]
        if user is not None:
            key = (review_id, getattr(user, 'id', user))
            if key in self._votes:
                raise ValueError("already voted")
            self._votes[key] = helpful
        if helpful:
            r.helpful += 1
        else:
            r.not_helpful += 1

    def report(self, review_id, user=None):
        with self._lock:
            r = self._reviews.get(review_id)
            if r is None:
                return
            if user is not None:
                key = ("report", review_id, getattr(user, "id", user))
                if key in self._votes:
                    return
                self._votes[key] = True
            r.reported += 1

    def approve_review(self, review_id):
        if review_id in self._reviews:
            self._reviews[review_id].status = "approved"

    def approve_professor(self, professor_id):
        if professor_id in self._professors:
            self._professors[professor_id].status = "approved"

    # reads
    def schools(self):
        return sorted(self._schools.values(), key=lambda s: s.name)

    def cities(self):
        return sorted({s.city for s in self._schools.values()})

    def locations(self):
        return build_locations(self._schools.values())

    def schools_in(self, region="", city=""):
        return filter_schools(self.schools(), region, city)

    def school(self, school_id):
        return self._schools.get(school_id)

    def school_by_slug(self, slug):
        return next((s for s in self._schools.values() if s.slug == slug), None)

    def professor(self, slug):
        return next((p for p in self._professors.values() if p.slug == slug and p.status == "approved"), None)

    def professor_any(self, slug):
        return next((p for p in self._professors.values() if p.slug == slug), None)

    def professor_by_id(self, professor_id):
        return self._professors.get(professor_id)

    def professors_for_school(self, school_id):
        return [p for p in self._professors.values() if p.school_id == school_id and p.status == "approved"]

    def review(self, review_id):
        return self._reviews.get(review_id)

    def reviews_for(self, professor_id, sort="newest", include_pending=False):
        rs = [r for r in self._reviews.values() if r.professor_id == professor_id and (include_pending or r.status == "approved")]
        key = (lambda r: r.helpful - r.not_helpful) if sort == "helpful" else (lambda r: r.created_at)
        return sorted(rs, key=key, reverse=True)

    def all_reviews(self, include_pending=False):
        if include_pending:
            return list(self._reviews.values())
        return [r for r in self._reviews.values() if r.status == "approved"]

    def stats(self, professor_id):
        rs = [r for r in self._reviews.values() if r.professor_id == professor_id and r.status == "approved"]
        n = len(rs)
        dist = Counter(r.overall for r in rs)
        distribution = [{"score": s, "count": dist[s], "pct": round(100 * dist[s] / n) if n else 0}
                        for s in range(5, 0, -1)]
        if not n:
            return {"count": 0, "overall": 0, "difficulty": 0, "wta_pct": None,
                    "tone": "none", "distribution": distribution, "top_tags": []}
        overall = round(mean(r.overall for r in rs), 1)
        tags = Counter(t for r in rs for t in r.tags)
        return {
            "count": n, "overall": overall,
            "difficulty": round(mean(r.difficulty for r in rs), 1),
            "wta_pct": round(100 * sum(r.would_take_again for r in rs) / n),
            "tone": _tone(overall), "distribution": distribution,
            "top_tags": [t for t, _ in tags.most_common(3)],
        }

    def school_stats(self, school_id):
        profs = self.professors_for_school(school_id)
        if not profs:
            return {"prof_count": 0, "review_count": 0, "avg_overall": 0}
        total_reviews = sum(self.stats(p.id)["count"] for p in profs)
        avg = round(mean([self.stats(p.id)["overall"] for p in profs if self.stats(p.id)["count"]]), 1) if total_reviews else 0
        return {"prof_count": len(profs), "review_count": total_reviews, "avg_overall": avg}

    def departments_for_school(self, school_id):
        return sorted({p.department for p in self.professors_for_school(school_id)})

    def search(self, q="", school_slug="", city="", region=""):
        words = _norm(q).split()[:5]
        out = []
        for p in self._professors.values():
            if p.status != "approved":
                continue
            school = self._schools[p.school_id]
            if school_slug and school.slug != school_slug:
                continue
            if city and school.city != city:
                continue
            if region and school.region != region:
                continue
            text = _norm(f"{p.full_name} {p.department}")
            if any(w not in text for w in words):
                continue
            out.append({"prof": p, "school": school, "stats": self.stats(p.id)})
        out.sort(key=lambda x: (-x["stats"]["overall"], x["prof"].last_name))
        return out

    def has_user_reviewed(self, professor_id, course, user):
        if user is None:
            return False
        key = (professor_id, course.lower().strip(), getattr(user, 'id', user))
        return key in self._review_keys

    def has_user_voted(self, review_id, user):
        if user is None:
            return False
        return (review_id, getattr(user, 'id', user)) in self._votes
