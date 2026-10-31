"""Data layer. Views talk only to a repository object, never to storage directly.

When PostgreSQL is connected, write a DjangoRepository with these same methods
(backed by models/ORM) and point reviews/store.py at it. Views stay untouched.
"""
from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from statistics import mean
from typing import Any

from django.utils.text import slugify
from django.utils.translation import get_language, gettext_lazy as _

from .caching import invalidate_catalog_cache
from .geo import build_locations, city_name, filter_schools, region_for_city, region_kind, region_name
from .constants import MAX_COMMENT_LENGTH
from .sanitize import clean_text

# Теги адаптированы под вузы Кыргызстана — без упоминаний коррупции
TAGS: list[str] = [
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
GRADES: list[str] = ["A", "B", "C", "D", "E", "FX", "F", _("Зачёт"), _("Незачёт"), _("Ещё не знаю")]


@dataclass
class School:
    """Read-only school record shared by views and templates."""

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
    def display_name(self) -> str:
        """Name in the active UI language, falling back to the official Russian one."""
        lang = (get_language() or "ru")[:2]
        if lang == "ky" and self.name_ky:
            return self.name_ky
        if lang == "en" and self.name_en:
            return self.name_en
        return self.name

    @property
    def region_name(self) -> str:
        return region_name(self.region)

    @property
    def city_name(self) -> str:
        return city_name(self.city)

    @property
    def in_oblast(self) -> bool:
        """False for Bishkek and Osh (cities of republican significance)."""
        return region_kind(self.region) == "oblast"


@dataclass
class Professor:
    """Read-only professor record shared by views and templates."""

    id: str
    school_id: str
    first_name: str
    last_name: str
    slug: str
    department: str
    title: str
    status: str = "approved"  # pending | approved | rejected

    @property
    def full_name(self) -> str:
        """Return the professor's display name."""
        return f"{self.first_name} {self.last_name}"


@dataclass
class Review:
    """Read-only review record shared by views and templates."""

    professor_id: str
    course: str
    term: str
    overall: int
    difficulty: int
    would_take_again: bool
    grade: str
    comment: str
    tags: list[str]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    helpful: int = 0
    not_helpful: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    status: str = "approved"  # pending | approved | rejected
    author_id: int | None = None
    reported: int = 0


def normalize_person_name(first: str, last: str) -> str:
    """Return a case- and whitespace-insensitive key for a person's name."""
    return " ".join(f"{first} {last}".split()).casefold()


def normalize_search_text(value: str | None) -> str:
    """Normalize free-text search input, treating ``ё`` and ``е`` as equal."""
    return (value or "").casefold().replace("ё", "е").strip()


def search_terms(value: str | None) -> list[str]:
    """Split normalized search input into words that must all match (AND)."""
    return normalize_search_text(value).split()


_LATIN_TO_CYRILLIC = {
    "shch": "щ", "yo": "ё", "zh": "ж", "kh": "х", "ts": "ц",
    "ch": "ч", "sh": "ш", "yu": "ю", "ya": "я",
    "a": "а", "b": "б", "v": "в", "g": "г", "d": "д", "e": "е",
    "z": "з", "i": "и", "j": "ж", "k": "к", "l": "л", "m": "м",
    "n": "н", "o": "о", "p": "п", "r": "р", "s": "с", "t": "т",
    "u": "у", "f": "ф", "h": "х", "c": "к", "y": "ы", "x": "кс",
    "w": "в", "q": "к",
}


def transliterate_search_term(value: str) -> str:
    """Convert a Latin search token to a simple Cyrillic approximation."""
    value = value.casefold()
    result = []
    index = 0
    tokens = sorted(_LATIN_TO_CYRILLIC, key=len, reverse=True)
    while index < len(value):
        for token in tokens:
            if value.startswith(token, index):
                result.append(_LATIN_TO_CYRILLIC[token])
                index += len(token)
                break
        else:
            result.append(value[index])
            index += 1
    return "".join(result)


def search_terms_with_transliteration(value: str | None) -> list[str]:
    """Return original and Latin-to-Cyrillic alternatives for each term."""
    return [
        "|".join(dict.fromkeys((term, normalize_search_text(transliterate_search_term(term)))))
        for term in search_terms(value)
    ]


def _tone(overall: float) -> str:
    """Map an average overall score to the CSS tone token used by templates."""
    return "good" if overall >= 4 else "mid" if overall >= 3 else "bad"


def _search_sort_key(sort: str) -> Callable[[dict[str, Any]], tuple[Any, ...]]:
    """Sort key for professor search results: by rating (default) or review count."""
    if sort == "reviews":
        return lambda x: (-x["stats"]["count"], -x["stats"]["overall"], x["prof"].last_name)
    return lambda x: (-x["stats"]["overall"], x["prof"].last_name)


class InMemoryRepository:
    """Volatile repository used when no database backend is configured."""

    def __init__(self) -> None:
        self._schools: dict[str, School] = {}
        self._professors: dict[str, Professor] = {}
        self._reviews: dict[str, Review] = {}
        # (review_id, user_id) -> "up"/"down"
        self._votes: dict[tuple[str, Any], bool] = {}
        # (review_id, user_id) -> report reason; one report per user and review
        self._reports: dict[tuple[str, Any], str] = {}
        # (professor_id, course_lower, user_id) uniqueness for review
        self._review_keys: set[tuple[str, str, Any]] = set()

    # writes
    def add_school(self, name: str, city: str, region: str = "", code: str = "", slug: str = "", **extra: Any) -> School:
        """Create and store a school."""
        slug = slug or code or slugify(name, allow_unicode=True) or slugify(name) or name.lower().replace(" ", "-")
        s = School(str(uuid.uuid4()), name, slug, city, region=region or region_for_city(city), code=code, **extra)
        self._schools[s.id] = s
        invalidate_catalog_cache()
        return s

    def add_professor(
        self,
        school_id: str,
        first: str,
        last: str,
        department: str,
        title: str,
        status: str = "approved",
    ) -> Professor:
        """Create and store a professor, rejecting duplicates in the same school."""
        # защита от дубля ФИО+вуз (регистр и лишние пробелы не важны)
        if self.professor_by_name(school_id, first, last) is not None:
            raise ValueError("duplicate professor")
        slug = slugify(f"{first} {last}", allow_unicode=True) or slugify(f"{first} {last}") or f"{first}-{last}".lower()
        # ensure unique slug
        base, i = slug, 1
        while any(p.slug == slug for p in self._professors.values()):
            slug = f"{base}-{i}"
            i += 1
        p = Professor(str(uuid.uuid4()), school_id, first, last, slug, department, title, status=status)
        self._professors[p.id] = p
        invalidate_catalog_cache()
        return p

    def add_review(
        self,
        professor_id: str,
        data: Mapping[str, Any],
        user: Any = None,
        status: str | None = None,
    ) -> Review:
        """Create and store a review, enforcing per-user course uniqueness."""
        # limit one review per professor+course per user
        course = clean_text(data.get("course") or "")
        comment = clean_text(data.get("comment") or "")
        if len(comment) > MAX_COMMENT_LENGTH:
            raise ValueError("comment too long")
        if user is not None and course:
            key = (professor_id, course.lower(), getattr(user, 'id', user))
            if key in self._review_keys:
                raise ValueError("duplicate review")
            self._review_keys.add(key)
        if status is None:
            # новые отзывы от залогиненных — pending, анонимные/seed — approved
            status = "pending" if user is not None else "approved"
        r = Review(
            professor_id=professor_id, course=course, term=clean_text(data.get("term") or ""),
            overall=data["overall"], difficulty=data["difficulty"],
            would_take_again=data["would_take_again"], grade=data.get("grade", ""),
            comment=comment, tags=list(data.get("tags", [])),
            status=status, author_id=getattr(user, 'id', None) if user else None,
        )
        self._reviews[r.id] = r
        invalidate_catalog_cache()
        return r

    def vote(self, review_id: str, helpful: bool, user: Any = None) -> None:
        """Record a helpful/not-helpful vote, rejecting repeat votes by a user."""
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

    def report(self, review_id: str, user: Any = None, reason: str = "other") -> None:
        """Record one report per user and increment the review's counter."""
        r = self._reviews.get(review_id)
        if not r:
            return
        if user is not None:
            key = (review_id, getattr(user, "id", user))
            if key in self._reports:
                return
            self._reports[key] = reason
        r.reported += 1

    def approve_review(self, review_id: str) -> None:
        """Mark a review as approved when it exists."""
        if review_id in self._reviews:
            self._reviews[review_id].status = "approved"
            invalidate_catalog_cache()

    def update_review(self, review_id: str, data: Mapping[str, Any]) -> None:
        review = self._reviews[review_id]
        for key in ("course", "term", "comment"):
            setattr(review, key, clean_text(data.get(key) or ""))
        for key in ("overall", "difficulty", "would_take_again", "grade", "tags"):
            setattr(review, key, list(data.get(key, [])) if key == "tags" else data.get(key))
        review.status = "pending"
        invalidate_catalog_cache()

    def delete_review(self, review_id: str) -> None:
        review = self._reviews.pop(review_id)
        self._review_keys.discard((review.professor_id, review.course.lower(), review.author_id))
        invalidate_catalog_cache()

    def approve_professor(self, professor_id: str) -> None:
        """Mark a professor as approved when it exists."""
        if professor_id in self._professors:
            self._professors[professor_id].status = "approved"
            invalidate_catalog_cache()

    # reads
    def schools(self) -> list[School]:
        """Return all schools sorted by name."""
        return sorted(self._schools.values(), key=lambda s: s.name)

    def cities(self) -> list[str]:
        """Return the sorted set of school cities."""
        return sorted({s.city for s in self._schools.values()})

    def departments(self) -> list[str]:
        """Return the sorted set of departments for approved professors."""
        return sorted({p.department for p in self._professors.values() if p.status == "approved"})

    def locations(self) -> list[dict[str, Any]]:
        """Regions of Kyrgyzstan with the distinct cities that have schools."""
        return build_locations(self._schools.values())

    def schools_in(self, region: str = "", city: str = "") -> list[School]:
        """Schools located in a city, or anywhere in a region."""
        return filter_schools(self.schools(), region, city)

    def school(self, school_id: str) -> School | None:
        """Return a school by id, or ``None`` if it does not exist."""
        return self._schools.get(school_id)

    def school_by_slug(self, slug: str) -> School | None:
        """Return a school by slug, or ``None`` if it does not exist."""
        return next((s for s in self._schools.values() if s.slug == slug), None)

    def professor(self, slug: str) -> Professor | None:
        """Return an approved professor by slug, or ``None``."""
        return next((p for p in self._professors.values() if p.slug == slug and p.status == "approved"), None)

    def professor_any(self, slug: str) -> Professor | None:
        """Return a professor by slug regardless of moderation status."""
        return next((p for p in self._professors.values() if p.slug == slug), None)

    def professor_by_id(self, professor_id: str) -> Professor | None:
        """Return a professor by id, or ``None`` if it does not exist."""
        return self._professors.get(professor_id)

    def professor_by_name(self, school_id: str, first: str, last: str) -> Professor | None:
        """Return a non-rejected professor matching a normalized full name."""
        key = normalize_person_name(first, last)
        return next(
            (
                p for p in self._professors.values()
                if p.school_id == school_id
                and p.status != "rejected"
                and normalize_person_name(p.first_name, p.last_name) == key
            ),
            None,
        )

    def professors_for_school(self, school_id: str) -> list[Professor]:
        """Return approved professors belonging to a school."""
        return [p for p in self._professors.values() if p.school_id == school_id and p.status == "approved"]

    def review(self, review_id: str) -> Review | None:
        """Return a review by id, or ``None`` if it does not exist."""
        return self._reviews.get(review_id)

    def reviews_for(self, professor_id: str, sort: str = "new", include_pending: bool = False) -> list[Review]:
        """Return a professor's reviews, optionally including non-approved ones."""
        rs = [
            r for r in self._reviews.values()
            if r.professor_id == professor_id and (include_pending or r.status == "approved")
        ]
        keys = {
            "old": (lambda r: r.created_at, False),
            "high": (lambda r: r.overall, True),
            "low": (lambda r: r.overall, False),
            "helpful": (lambda r: r.helpful, True),
        }
        key, reverse = keys.get(sort, (lambda r: r.created_at, True))
        return sorted(rs, key=key, reverse=reverse)

    def all_reviews(self, include_pending: bool = False) -> list[Review]:
        """Return all reviews, optionally including non-approved ones."""
        if include_pending:
            return list(self._reviews.values())
        return [r for r in self._reviews.values() if r.status == "approved"]

    def reviews_for_user(self, user: Any) -> list[dict[str, Any]]:
        """Return a user's reviews with catalog data, regardless of status."""
        user_id = getattr(user, "id", user)
        reviews = sorted(
            (r for r in self._reviews.values() if r.author_id == user_id),
            key=lambda r: r.created_at,
            reverse=True,
        )
        rows = []
        for review in reviews:
            prof = self._professors[review.professor_id]
            rows.append({
                "review": review,
                "prof": prof,
                "school": self._schools[prof.school_id],
            })
        return rows

    def stats(self, professor_id: str) -> dict[str, Any]:
        """Return aggregate rating statistics for a professor."""
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

    def school_stats(self, school_id: str) -> dict[str, Any]:
        """Return aggregate rating statistics for a school."""
        profs = self.professors_for_school(school_id)
        if not profs:
            return {"prof_count": 0, "review_count": 0, "avg_overall": 0}
        # Compute each professor's stats once instead of three times per row.
        stats = [self.stats(p.id) for p in profs]
        total_reviews = sum(s["count"] for s in stats)
        rated = [s["overall"] for s in stats if s["count"]]
        avg = round(mean(rated), 1) if total_reviews else 0
        return {"prof_count": len(profs), "review_count": total_reviews, "avg_overall": avg}

    def search(
        self,
        q: str = "",
        school_slug: str = "",
        city: str = "",
        department: str = "",
        sort: str = "rating",
        region: str = "",
    ) -> list[dict[str, Any]]:
        """Search approved professors with optional filters and sorting."""
        terms = search_terms_with_transliteration(q)
        region = region.strip()
        school_slug = school_slug.strip()
        city = city.strip()
        department = department.strip()
        out = []
        for p in self._professors.values():
            if p.status != "approved":
                continue
            school = self._schools[p.school_id]
            if school_slug and school.slug != school_slug:
                continue
            if city and school.city != city:
                continue
            if region and (school.region or region_for_city(school.city)) != region:
                continue
            if department and p.department != department:
                continue
            haystack = normalize_search_text(f"{p.full_name} {p.department}")
            if terms and not all(any(variant in haystack for variant in term.split("|")) for term in terms):
                continue
            out.append({"prof": p, "school": school, "stats": self.stats(p.id)})
        out.sort(key=_search_sort_key(sort))
        return out

    def has_user_reviewed(self, professor_id: str, course: str, user: Any) -> bool:
        """Return whether a user already reviewed this course for a professor."""
        if user is None:
            return False
        key = (professor_id, course.lower().strip(), getattr(user, 'id', user))
        return key in self._review_keys

    def has_user_voted(self, review_id: str, user: Any) -> bool:
        """Return whether a user already voted on a review."""
        if user is None:
            return False
        return (review_id, getattr(user, 'id', user)) in self._votes
