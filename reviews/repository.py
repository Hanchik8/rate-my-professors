"""Data layer. Views talk only to a repository object, never to storage directly.

When PostgreSQL is connected, write a DjangoRepository with these same methods
(backed by models/ORM) and point reviews/store.py at it. Views stay untouched.
"""
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from statistics import mean

from django.utils.text import slugify

TAGS = [
    "Tough grader", "Clear grading criteria", "Amazing lectures", "Lots of homework",
    "Test heavy", "Group projects", "Accessible outside class", "Gives good feedback",
    "Participation matters", "Inspirational",
]
GRADES = ["A", "B", "C", "D", "F", "Pass", "Fail", "Not sure yet"]


@dataclass
class School:
    id: str
    name: str
    slug: str
    city: str


@dataclass
class Professor:
    id: str
    school_id: str
    first_name: str
    last_name: str
    slug: str
    department: str
    title: str

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


def _tone(overall):
    return "good" if overall >= 4 else "mid" if overall >= 3 else "bad"


class InMemoryRepository:
    def __init__(self):
        self._schools, self._professors, self._reviews = {}, {}, {}

    # writes
    def add_school(self, name, city):
        s = School(str(uuid.uuid4()), name, slugify(name), city)
        self._schools[s.id] = s
        return s

    def add_professor(self, school_id, first, last, department, title):
        p = Professor(str(uuid.uuid4()), school_id, first, last,
                      slugify(f"{first} {last}"), department, title)
        self._professors[p.id] = p
        return p

    def add_review(self, professor_id, data):
        r = Review(
            professor_id=professor_id, course=data["course"], term=data.get("term", ""),
            overall=data["overall"], difficulty=data["difficulty"],
            would_take_again=data["would_take_again"], grade=data.get("grade", ""),
            comment=data["comment"], tags=list(data.get("tags", [])),
        )
        self._reviews[r.id] = r
        return r

    def vote(self, review_id, helpful):
        r = self._reviews[review_id]
        if helpful:
            r.helpful += 1
        else:
            r.not_helpful += 1

    # reads
    def schools(self):
        return sorted(self._schools.values(), key=lambda s: s.name)

    def school(self, school_id):
        return self._schools.get(school_id)

    def professor(self, slug):
        return next((p for p in self._professors.values() if p.slug == slug), None)

    def professor_by_id(self, professor_id):
        return self._professors.get(professor_id)

    def review(self, review_id):
        return self._reviews.get(review_id)

    def reviews_for(self, professor_id, sort="newest"):
        rs = [r for r in self._reviews.values() if r.professor_id == professor_id]
        key = (lambda r: r.helpful - r.not_helpful) if sort == "helpful" else (lambda r: r.created_at)
        return sorted(rs, key=key, reverse=True)

    def stats(self, professor_id):
        rs = [r for r in self._reviews.values() if r.professor_id == professor_id]
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

    def search(self, q="", school_slug=""):
        q = q.lower().strip()
        out = []
        for p in self._professors.values():
            school = self._schools[p.school_id]
            if school_slug and school.slug != school_slug:
                continue
            if q and q not in f"{p.full_name} {p.department}".lower():
                continue
            out.append({"prof": p, "school": school, "stats": self.stats(p.id)})
        out.sort(key=lambda x: (-x["stats"]["overall"], x["prof"].last_name))
        return out
