from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, F, Q
from django.db.models.functions import Coalesce
from django.utils.text import slugify

from .models import Professor, Report, Review, School, Tag, Vote


def _tone(overall):
    return "good" if overall >= 4 else "mid" if overall >= 3 else "bad"


class DjangoRepository:
    def add_school(self, name, city, short_name="", region="", type="", website=""):
        slug = slugify(name, allow_unicode=True) or slugify(name) or name.lower().replace(" ", "-")
        base, i = slug, 1
        while School.objects.filter(slug=slug).exists():
            slug = f"{base}-{i}"
            i += 1
        s = School.objects.create(name=name, slug=slug, city=city, short_name=short_name, region=region, type=type, website=website)
        return self._school_to_dc(s)

    def add_professor(self, school_id, first, last, department, title, status="approved", user=None):
        school = School.objects.get(pk=school_id)
        if Professor.objects.filter(school=school, first_name__iexact=first.strip(), last_name__iexact=last.strip()).exclude(status="rejected").exists():
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
        from django.core.exceptions import ValidationError
        prof = Professor.objects.get(pk=professor_id)
        course = (data.get("course") or "").strip()
        if status is None:
            status = "pending" if user is not None else "approved"
        r = Review(
            professor=prof, course=course, term=data.get("term", ""),
            overall=data["overall"], difficulty=data["difficulty"],
            would_take_again=data["would_take_again"], grade=data.get("grade", ""),
            comment=data["comment"], status=status, author=user,
        )
        try:
            r.full_clean(exclude=["id", "professor", "author", "tags"])
        except ValidationError as e:
            raise ValueError(str(e))
        if user is not None and course:
            if Review.objects.filter(professor=prof, author=user).filter(course__iexact=course).exists():
                raise ValueError("duplicate review")
        r.save()
        for t in data.get("tags", []):
            tag, _ = Tag.objects.get_or_create(name=str(t))
            r.tags.add(tag)
        return self._review_to_dc(r)

    def vote(self, review_id, helpful, user=None):
        with transaction.atomic():
            r = Review.objects.select_for_update().get(pk=review_id)
            if user is not None:
                try:
                    Vote.objects.create(review=r, user=user, helpful=helpful)
                except IntegrityError:
                    raise ValueError("already voted")
            if helpful:
                Review.objects.filter(pk=review_id).update(helpful=F("helpful") + 1)
            else:
                Review.objects.filter(pk=review_id).update(not_helpful=F("not_helpful") + 1)

    def report(self, review_id, user=None):
        with transaction.atomic():
            r = Review.objects.select_for_update().get(pk=review_id)
            if user is not None:
                try:
                    Report.objects.create(review=r, user=user)
                except IntegrityError:
                    raise ValueError("already reported")
            new_reported = Report.objects.filter(review=r).count()
            upd = {"reported": new_reported}
            if new_reported >= 3 and r.status == "approved":
                upd["status"] = "pending"
            Review.objects.filter(pk=review_id).update(**upd)

    def approve_review(self, review_id):
        Review.objects.filter(pk=review_id).update(status="approved")

    def approve_professor(self, professor_id):
        Professor.objects.filter(pk=professor_id).update(status="approved")

    def update_school(self, school_id, **kwargs):
        try:
            allowed = {k: v for k, v in kwargs.items() if k in ["name", "short_name", "city", "region", "type", "website", "slug"]}
            if not allowed:
                return self.school(str(school_id))
            School.objects.filter(pk=school_id).update(**allowed)
            return self.school(str(school_id))
        except (ValueError, TypeError):
            return None

    def schools(self):
        return [self._school_to_dc(s) for s in School.objects.all()]

    def cities(self):
        return sorted(School.objects.values_list("city", flat=True).distinct())

    def regions(self):
        return sorted(v for v in School.objects.values_list("region", flat=True).distinct() if v)

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

    def school_by_short_name(self, short_name):
        try:
            return self._school_to_dc(School.objects.get(short_name=short_name))
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
            items = list(qs)
            items.sort(key=lambda r: (r.helpful - r.not_helpful, r.created_at.timestamp() if hasattr(r.created_at, 'timestamp') else r.created_at), reverse=True)
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
        agg = qs.aggregate(
            cnt=Count("id"),
            avg_overall=Avg("overall"),
            avg_diff=Avg("difficulty"),
            wta_cnt=Count("id", filter=Q(would_take_again=True)),
        )
        n = agg["cnt"] or 0
        dist_qs = qs.values("overall").annotate(c=Count("id"))
        dist = {row["overall"]: row["c"] for row in dist_qs}
        distribution = [{"score": s, "count": dist.get(s, 0), "pct": round(100 * dist.get(s, 0) / n) if n else 0} for s in range(5, 0, -1)]
        if not n:
            return {"count": 0, "overall": 0, "difficulty": 0, "wta_pct": None, "tone": "none", "distribution": distribution, "top_tags": []}
        overall = round(agg["avg_overall"], 1)
        diff = round(agg["avg_diff"], 1)
        wta = round(100 * agg["wta_cnt"] / n)
        tag_counts = Tag.objects.filter(review__professor_id=professor_id, review__status="approved").annotate(cnt=Count("review")).order_by("-cnt")[:3]
        top_tags = [t.name for t in tag_counts]
        return {"count": n, "overall": overall, "difficulty": diff, "wta_pct": wta, "tone": _tone(overall), "distribution": distribution, "top_tags": top_tags}

    def school_stats(self, school_id):
        profs = Professor.objects.filter(school_id=school_id, status="approved")
        n = profs.count()
        if not n:
            return {"prof_count": 0, "review_count": 0, "avg_overall": 0}
        total = Review.objects.filter(professor__school_id=school_id, status="approved").count()
        if not total:
            return {"prof_count": n, "review_count": 0, "avg_overall": 0}
        avg = Review.objects.filter(professor__school_id=school_id, status="approved").aggregate(v=Avg("overall"))["v"]
        return {"prof_count": n, "review_count": total, "avg_overall": round(avg, 1) if avg else 0}

    def search(self, q="", school_slug="", city=""):
        qs = Professor.objects.filter(status="approved").select_related("school").annotate(
            _avg_overall=Avg("reviews__overall", filter=Q(reviews__status="approved")),
            _avg_difficulty=Avg("reviews__difficulty", filter=Q(reviews__status="approved")),
            _cnt=Count("reviews", filter=Q(reviews__status="approved")),
            _wta=Count("reviews", filter=Q(reviews__status="approved", reviews__would_take_again=True)),
        )
        if school_slug:
            qs = qs.filter(school__slug=school_slug)
        if city:
            qs = qs.filter(school__city=city)
        if q:
            q = q.strip()[:100]
            qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(department__icontains=q))
        qs = qs.order_by(F("_avg_overall").desc(nulls_last=True), "last_name", "first_name")
        out = []
        for p in qs:
            dc = self._prof_to_dc(p)
            school = self._school_to_dc(p.school)
            n = p._cnt or 0
            avg = round(p._avg_overall, 1) if p._avg_overall is not None else 0
            diff = round(p._avg_difficulty, 1) if p._avg_difficulty is not None else 0
            wta = round(100 * p._wta / n) if n else None
            tone = _tone(avg) if n else "none"
            stats = {"count": n, "overall": avg, "difficulty": diff, "wta_pct": wta, "tone": tone, "distribution": [], "top_tags": []}
            out.append({"prof": dc, "school": school, "stats": stats})
        return out

    def has_user_reviewed(self, professor_id, course, user):
        if user is None or not getattr(user, 'is_authenticated', False):
            return False
        return Review.objects.filter(professor_id=professor_id, course__iexact=course.strip(), author=user).exists()

    def has_user_voted(self, review_id, user):
        if user is None or not getattr(user, 'is_authenticated', False):
            return False
        return Vote.objects.filter(review_id=review_id, user=user).exists()

    def _school_to_dc(self, s):
        from .repository import School as DCSchool
        return DCSchool(id=str(s.pk), name=s.name, slug=s.slug, city=s.city, short_name=s.short_name or "", region=s.region or "", type=s.type or "", website=s.website or "")

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
