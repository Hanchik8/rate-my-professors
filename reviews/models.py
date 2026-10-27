import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.text import slugify


def normalize_search(text):
    """Lower-case + ё->е. Used both for stored search_text and for queries,
    so search is case-insensitive for Cyrillic on PostgreSQL and SQLite alike."""
    return " ".join((text or "").lower().replace("ё", "е").split())


class School(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, allow_unicode=True)
    city = models.CharField(max_length=80, db_index=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name, allow_unicode=True) or slugify(self.name)
        super().save(*args, **kwargs)


class Tag(models.Model):
    name = models.CharField(max_length=80, unique=True)

    def __str__(self):
        return self.name


class Professor(models.Model):
    STATUS_CHOICES = [("pending", "pending"), ("approved", "approved"), ("rejected", "rejected")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="professors")
    first_name = models.CharField(max_length=40)
    last_name = models.CharField(max_length=40)
    slug = models.SlugField(max_length=200, unique=True, allow_unicode=True)
    department = models.CharField(max_length=80)
    title = models.CharField(max_length=40)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="approved")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    # "имя фамилия кафедра" in lower case, filled in save(); used by search
    search_text = models.CharField(max_length=200, blank=True, default="", editable=False)

    class Meta:
        ordering = ["last_name", "first_name"]
        constraints = [
            # same name twice at one school is a duplicate (case-insensitive); rejected ones don't count
            models.UniqueConstraint(
                "school", Lower("first_name"), Lower("last_name"),
                condition=~Q(status="rejected"), name="uniq_prof_school_name_ci",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "last_name", "first_name"], name="prof_status_name_idx"),
            models.Index(fields=["school", "status"], name="prof_school_status_idx"),
        ]

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def __str__(self):
        return f"{self.full_name} ({self.school})"

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(f"{self.first_name} {self.last_name}", allow_unicode=True) or slugify(f"{self.first_name} {self.last_name}")
            slug = base
            i = 1
            while Professor.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{i}"
                i += 1
            self.slug = slug
        self.search_text = normalize_search(f"{self.first_name} {self.last_name} {self.department}")
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {"search_text"}
        super().save(*args, **kwargs)


class Review(models.Model):
    STATUS_CHOICES = [("pending", "pending"), ("approved", "approved"), ("rejected", "rejected")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    professor = models.ForeignKey(Professor, on_delete=models.CASCADE, related_name="reviews")
    course = models.CharField(max_length=80)
    term = models.CharField(max_length=20, blank=True)
    overall = models.IntegerField()
    difficulty = models.IntegerField()
    would_take_again = models.BooleanField()
    grade = models.CharField(max_length=20, blank=True)
    comment = models.TextField()
    tags = models.ManyToManyField(Tag, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="pending")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="reviews")
    helpful = models.IntegerField(default=0)
    not_helpful = models.IntegerField(default=0)
    reported = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # one review per user per professor+course (case-insensitive). Seed reviews have no author.
            models.UniqueConstraint(
                "professor", "author", Lower("course"),
                condition=Q(author__isnull=False), name="uniq_review_author_prof_course",
            ),
            models.CheckConstraint(condition=Q(overall__gte=1, overall__lte=5), name="review_overall_1_5"),
            models.CheckConstraint(condition=Q(difficulty__gte=1, difficulty__lte=5), name="review_difficulty_1_5"),
        ]
        indexes = [
            models.Index(fields=["professor", "status", "-created_at"], name="review_prof_status_date_idx"),
            models.Index(fields=["status", "-created_at"], name="review_status_date_idx"),
        ]

    def __str__(self):
        return f"{self.professor} {self.course} {self.overall}"


class Vote(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="votes")
    helpful = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("review", "user")]


class Report(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="reports")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("review", "user")]


class AccountProfile(models.Model):
    """Extra per-user flags. email_verified is separate from User.is_active on purpose:
    confirming an email must never re-enable a banned (is_active=False) account."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    email_verified = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.user} ({'verified' if self.email_verified else 'unverified'})"
