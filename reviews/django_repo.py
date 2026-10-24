from collections import Counter
from statistics import mean
from django.db import IntegrityError, transaction
from django.db.models import Count, F
from django.utils.text import slugify

from .models import Professor, Review, School, Tag, Vote, Report
from .repository import _search_sort_key


def _tone(overall):
    return "good" if overall >= 4 else "mid" if overall >= 3 else "bad"


class DjangoRepository:
    """ORM-backed repository with the same API as InMemoryRepository."""

    # writes
    def add_school(self, name, city):
        slug = slugify(name, allow_unicode=True) or slugify(name) or name.lower().replace(" ", "-")
        # ensure unique
        base, i = slug, 1
        while School.objects.filter(slug=slug).exists():
            slug = f"{base}-{i}"
            i += 1
        s = School.objects.create(name=name, slug=slug, city=city)
        return self._school_to_dc(s)

    def add_professor(self, school_id, first, last, department, title, status="approved", user=None):
        school = School.objects.get(pk=school_id)
        if Professor.objects.filter(school=school, first_name__iexact=first.strip(), last_name__iexact=last.strip()).exclude(status="rejected").exists():
            # fallback case-insensitive python check for SQLite
            for p in Professor.objects.filter(school=school).exclude(status="rejected"):
                if p.full_name.lower() == f"{first} {last}".lower():
                    raise ValueError("duplicate professor")
            raise ValueError("duplicate professor")
        base = slugify(f"{first} {last}", allow_unicode=True) or slugify(f"{first} {last}") or f"{first}-{last}".lower()
        slug = base
        i = 1
        while Professor.objects.filter(slug=slug).exists():
            slug = f"{base}-{i}"
            i += 1
        p = Professor.objects.create(
            school=school, first_name=first.strip(), last_name=last.strip(),
            slug=slug, department=department, title=title, status=status, created_by=user,
        )
        return self._prof_to_dc(p)

    def add_review(self, professor_id, data, user=None, status=None):
        prof = Professor.objects.get(pk=professor_id)
        course = (data.get("course") or "").strip()
        if status is None:
            status = "pending" if user is not None else "approved"
        try:
            with transaction.atomic():
                if user is not None and course:
                    exists = Review.objects.filter(professor=prof, course__iexact=course, author=user).exists()
                    if exists:
                        raise ValueError("duplicate review")
                r = Review.objects.create(
                    professor=prof, course=course, term=data.get("term", ""),
                    overall=data["overall"], difficulty=data["difficulty"],
                    would_take_again=data["would_take_again"], grade=data.get("grade", ""),
                    comment=data["comment"], status=status, author=user,
                )
                for t in data.get("tags", []):
                    tag, _ = Tag.objects.get_or_create(name=str(t))
                    r.tags.add(tag)
        except IntegrityError:
            raise ValueError("duplicate review")
        return self._review_to_dc(r)

    def vote(self, review_id, helpful, user=None):
        with transaction.atomic():
            r = Review.objects.select_for_update().get(pk=review_id)
            if user is not None:
                _, created = Vote.objects.get_or_create(
                    review=r, user=user, defaults={"helpful": helpful}
                )
                if not created:
                    raise ValueError("already voted")
            if helpful:
                Review.objects.filter(pk=review_id).update(helpful=F("helpful") + 1)
            else:
                Review.objects.filter(pk=review_id).update(not_helpful=F("not_helpful") + 1)

    def report(self, review_id, user=None):
        with transaction.atomic():
            r = Review.objects.select_for_update().get(pk=review_id)
            if user is not None:
                _, created = Report.objects.get_or_create(review=r, user=user)
                if not created:
                    return
            Review.objects.filter(pk=review_id).update(reported=F("reported") + 1)

    def approve_review(self, review_id):
        Review.objects.filter(pk=review_id).update(status="approved")

    def approve_professor(self, professor_id):
        Professor.objects.filter(pk=professor_id).update(status="approved")

    # reads
    def schools(self):
        return [self._school_to_dc(s) for s in School.objects.all()]

    def cities(self):
        return sorted(School.objects.values_list("city", flat=True).distinct())

    def departments(self):
        return sorted(Professor.objects.filter(status="approved").values_list("department", flat=True).distinct())

    def school(self, school_id):
        try:
            return self._school_to_dc(School.objects.get(pk=school_id))
        except School.DoesNotExist:
            return None

    def school_by_slug(self, slug):
        try:
            return self._school_to_dc(School.objects.get(slug=slug))
        except School.DoesNotExist:
            return None

    def professor(self, slug):
        try:
            return self._prof_to_dc(Professor.objects.get(slug=slug, status="approved"))
        except Professor.DoesNotExist:
            return None

    def professor_any(self, slug):
        try:
            return self._prof_to_dc(Professor.objects.get(slug=slug))
        except Professor.DoesNotExist:
            return None

    def professor_by_id(self, professor_id):
        try:
            return self._prof_to_dc(Professor.objects.get(pk=professor_id))
        except Professor.DoesNotExist:
            return None

    def professors_for_school(self, school_id):
        return [self._prof_to_dc(p) for p in Professor.objects.filter(school_id=school_id, status="approved")]

    def review(self, review_id):
        try:
            return self._review_to_dc(Review.objects.get(pk=review_id))
        except Review.DoesNotExist:
            return None

    def reviews_for(self, professor_id, sort="newest", include_pending=False):
        qs = Review.objects.filter(professor_id=professor_id)
        if not include_pending:
            qs = qs.filter(status="approved")
        qs = qs.prefetch_related("tags")
        if sort == "helpful":
            # sort in python by helpful - not_helpful
            items = list(qs)
            items.sort(key=lambda r: (r.helpful - r.not_helpful, r.created_at), reverse=True)
            return [self._review_to_dc(r) for r in items]
        else:
            return [self._review_to_dc(r) for r in qs.order_by("-created_at")]

    def all_reviews(self, include_pending=False):
        qs = Review.objects.all().prefetch_related("tags")
        if not include_pending:
            qs = qs.filter(status="approved")
        return [self._review_to_dc(r) for r in qs]

    def stats(self, professor_id):
        qs = Review.objects.filter(professor_id=professor_id, status="approved")
        n = qs.count()
        dist = Counter(qs.values_list("overall", flat=True))
        distribution = [{"score": s, "count": dist[s], "pct": round(100 * dist[s] / n) if n else 0} for s in range(5, 0, -1)]
        if not n:
            return {"count": 0, "overall": 0, "difficulty": 0, "wta_pct": None, "tone": "none", "distribution": distribution, "top_tags": []}
        overall = round(mean(qs.values_list("overall", flat=True)), 1)
        diff = round(mean(qs.values_list("difficulty", flat=True)), 1)
        wta = round(100 * qs.filter(would_take_again=True).count() / n)
        # top tags
        tag_counts = Counter()
        for r in qs.prefetch_related("tags"):
            for t in r.tags.all():
                tag_counts[str(t.name)] += 1
        top_tags = [t for t, _ in tag_counts.most_common(3)]
        return {"count": n, "overall": overall, "difficulty": diff, "wta_pct": wta, "tone": _tone(overall), "distribution": distribution, "top_tags": top_tags}

    def school_stats(self, school_id):
        profs = Professor.objects.filter(school_id=school_id, status="approved")
        n = profs.count()
        if not n:
            return {"prof_count": 0, "review_count": 0, "avg_overall": 0}
        total = Review.objects.filter(professor__school_id=school_id, status="approved").count()
        if not total:
            return {"prof_count": n, "review_count": 0, "avg_overall": 0}
        avgs = []
        for p in profs:
            s = self.stats(str(p.pk))
            if s["count"]:
                avgs.append(s["overall"])
        avg = round(mean(avgs), 1) if avgs else 0
        return {"prof_count": n, "review_count": total, "avg_overall": avg}

    def search(self, q="", school_slug="", city="", department="", sort="rating"):
        qs = Professor.objects.filter(status="approved").select_related("school")
        if school_slug:
            qs = qs.filter(school__slug=school_slug)
        if city:
            qs = qs.filter(school__city=city)
        if department:
            qs = qs.filter(department=department)
        q = q.lower().strip()
        out = []
        for p in qs:
            # filter in python for case-insensitive unicode
            if q and q not in f"{p.full_name} {p.department}".lower():
                continue
            dc = self._prof_to_dc(p)
            school = self._school_to_dc(p.school)
            out.append({"prof": dc, "school": school, "stats": self.stats(str(p.pk))})
        out.sort(key=_search_sort_key(sort))
        return out

    def has_user_reviewed(self, professor_id, course, user):
        if user is None or not getattr(user, 'is_authenticated', False):
            return False
        return Review.objects.filter(professor_id=professor_id, course__iexact=course.strip(), author=user).exists()

    def has_user_voted(self, review_id, user):
        if user is None or not getattr(user, 'is_authenticated', False):
            return False
        return Vote.objects.filter(review_id=review_id, user=user).exists()

    # helpers: ORM object -> dataclass-like used by views/templates (duck typing)
    def _school_to_dc(self, s):
        from .repository import School as DCSchool
        return DCSchool(id=str(s.pk), name=s.name, slug=s.slug, city=s.city)

    def _prof_to_dc(self, p):
        from .repository import Professor as DCProf
        return DCProf(id=str(p.pk), school_id=str(p.school_id), first_name=p.first_name, last_name=p.last_name, slug=p.slug, department=p.department, title=p.title, status=p.status)

    def _review_to_dc(self, r):
        from .repository import Review as DCReview
        tags = [str(t.name) for t in r.tags.all()] if hasattr(r, 'tags') else []
        return DCReview(
            professor_id=str(r.professor_id), course=r.course, term=r.term,
            overall=r.overall, difficulty=r.difficulty, would_take_again=r.would_take_again,
            grade=r.grade, comment=r.comment, tags=tags,
            id=str(r.pk), helpful=r.helpful, not_helpful=r.not_helpful,
            created_at=r.created_at, status=r.status, author_id=r.author_id,
            reported=r.reported,
        )
