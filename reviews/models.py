import uuid
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, URLValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils.html import strip_tags
from django.utils.text import slugify


class School(models.Model):
    TYPE_CHOICES = [("state", "state"), ("private", "private")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    short_name = models.CharField(max_length=80, blank=True, default="")
    slug = models.SlugField(max_length=220, unique=True, allow_unicode=True)
    city = models.CharField(max_length=80)
    region = models.CharField(max_length=80, blank=True, default="")
    type = models.CharField(max_length=10, choices=TYPE_CHOICES, blank=True, default="")
    website = models.URLField(blank=True, default="", validators=[URLValidator(schemes=["http", "https"])])

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.short_name or self.name

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

    class Meta:
        ordering = ["last_name", "first_name"]
        constraints = [
            models.UniqueConstraint(fields=["school", "first_name", "last_name"], name="uniq_prof_school_name"),
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
        super().save(*args, **kwargs)


class Review(models.Model):
    STATUS_CHOICES = [("pending", "pending"), ("approved", "approved"), ("rejected", "rejected")]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    professor = models.ForeignKey(Professor, on_delete=models.CASCADE, related_name="reviews")
    course = models.CharField(max_length=80)
    term = models.CharField(max_length=20, blank=True)
    overall = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    difficulty = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
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
            models.UniqueConstraint(
                Lower("course"), "professor", "author",
                name="uniq_review_prof_author_course",
                condition=Q(author__isnull=False),
            ),
            models.CheckConstraint(condition=Q(overall__gte=1, overall__lte=5), name="check_overall_range"),
            models.CheckConstraint(condition=Q(difficulty__gte=1, difficulty__lte=5), name="check_difficulty_range"),
        ]

    def save(self, *args, **kwargs):
        # strip HTML from comment
        if self.comment:
            self.comment = strip_tags(self.comment)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.professor} {self.course} {self.overall}"


# Functional unique on Lower(course) can't be expressed via fields; add via migrations.RunSQL or extra constraint
# We'll add the real Lower constraint in migration 0003

class Vote(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="votes")
    helpful = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["review", "user"], name="uniq_vote_review_user"),
        ]


class Report(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="reports")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reports")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["review", "user"], name="uniq_report_review_user"),
        ]
