"""HTTP views for the ProfLens review app.

Views stay thin: they translate request parameters into repository calls
and render templates, so that no storage detail leaks into the request
layer.  Reusable pieces (pagination, filter parsing, moderation redirects)
live in small private helpers below.
"""
from django import forms
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .forms import ProfessorForm, ReviewForm
from .store import repo

PAGE_SIZE = 10


def health(request):
    """Liveness endpoint used by the container orchestrator."""
    return JsonResponse({"status": "ok"})


def _paginate(items, page_number):
    """Return ``(page_items, page_obj)`` for ``items``.

    ``page_obj`` is ``None`` when everything fits on one page, so templates
    can omit pagination controls while still using a flat result list.
    """
    paginator = Paginator(items, PAGE_SIZE)
    page_obj = paginator.get_page(page_number)
    if paginator.num_pages <= 1:
        return items, None
    return page_obj.object_list, page_obj


def _home_filters(request):
    """Parse and normalize the home page's search/filter query string."""
    q = request.GET.get("q", "")
    school = request.GET.get("school", "")
    city = request.GET.get("city", "")
    department = request.GET.get("department", "")
    sort = request.GET.get("sort", "rating")
    if sort not in ("rating", "reviews"):
        sort = "rating"
    return q, school, city, department, sort


def home(request):
    """Search/browse professors with filters, sorting and pagination."""
    q, school, city, department, sort = _home_filters(request)
    results = repo.search(q, school, city, department, sort)
    page_results, page_obj = _paginate(results, request.GET.get("page"))
    return render(request, "reviews/home.html", {
        "q": q, "school": school, "city": city,
        "department": department, "sort": sort,
        "schools": repo.schools(),
        "cities": repo.cities(),
        "departments": repo.departments(),
        "results": page_results,
        "page_obj": page_obj,
    })


def _professor_or_404(slug):
    """Fetch an approved professor by slug or raise ``Http404``."""
    prof = repo.professor(slug)
    if prof is None:
        raise Http404(_("Professor not found"))
    return prof


def professor_detail(request, slug):
    """Show a professor profile with aggregate stats and paginated reviews."""
    prof = _professor_or_404(slug)
    sort = "helpful" if request.GET.get("sort") == "helpful" else "newest"
    all_reviews = repo.reviews_for(prof.id, sort)
    reviews, page_obj = _paginate(all_reviews, request.GET.get("page"))
    return render(request, "reviews/professor.html", {
        "prof": prof, "school": repo.school(prof.school_id), "stats": repo.stats(prof.id),
        "reviews": reviews, "sort": sort, "page_obj": page_obj,
    })


def school_detail(request, slug):
    """Show a school page: its professors, aggregate stats and departments."""
    school = repo.school_by_slug(slug)
    if school is None:
        raise Http404(_("School not found"))
    results = [r for r in repo.search("", school_slug=school.slug)]
    stats = repo.school_stats(school.id)
    departments = sorted({r["prof"].department for r in results})
    page_results, page_obj = _paginate(results, request.GET.get("page"))
    return render(request, "reviews/school.html", {
        "school": school, "results": page_results, "stats": stats,
        "departments": departments, "page_obj": page_obj,
    })


def rules(request):
    """Render the community rules page."""
    return render(request, "reviews/rules.html")


def _save_review(form, prof, request):
    """Persist a validated review, returning ``True`` on success.

    On failure the relevant error is attached to ``form`` (duplicate course
    for this user, or any other repository error) and ``False`` is returned.
    """
    duplicate_msg = _("Вы уже оставляли отзыв по этому предмету у этого преподавателя.")
    course = form.cleaned_data["course"]
    if repo.has_user_reviewed(prof.id, course, request.user):
        form.add_error("course", duplicate_msg)
        return False
    try:
        repo.add_review(prof.id, form.cleaned_data, user=request.user)
    except ValueError as e:
        if "duplicate" in str(e).lower():
            form.add_error("course", duplicate_msg)
        else:
            form.add_error(None, str(e))
        return False
    messages.success(request, _("Отзыв отправлен на модерацию. Спасибо!"))
    return True


@login_required
def review_new(request, slug):
    """Create a review for a professor; new reviews await moderation."""
    prof = _professor_or_404(slug)
    if request.method == "POST":
        form = ReviewForm(request.POST)
        if form.is_valid() and _save_review(form, prof, request):
            return redirect("professor", slug=prof.slug)
    else:
        form = ReviewForm()
    return render(request, "reviews/review_form.html", {
        "prof": prof, "form": form,
        "login_url": reverse("login"),
        "signup_url": reverse("signup"),
        "url": reverse("rules"),
    })


def _redirect_to_review(review):
    """Redirect back to the review's anchor on its professor page."""
    prof = repo.professor_by_id(review.professor_id)
    if prof:
        return redirect(reverse("professor", args=[prof.slug]) + f"#review-{review.id}")
    return redirect("home")


@require_POST
@login_required
def review_vote(request, review_id):
    """Record a helpful / not-helpful vote on a review."""
    review = repo.review(review_id)
    if review is None:
        raise Http404(_("Review not found"))
    if review.author_id is not None and str(review.author_id) == str(request.user.id):
        messages.warning(request, _("Нельзя голосовать за свой отзыв."))
        return _redirect_to_review(review)
    try:
        repo.vote(review_id, helpful=request.POST.get("vote") == "up", user=request.user)
    except ValueError:
        messages.warning(request, _("Вы уже голосовали за этот отзыв."))
    return _redirect_to_review(review)


@require_POST
@login_required
def review_report(request, review_id):
    """Flag a review for moderator attention."""
    review = repo.review(review_id)
    if review is None:
        raise Http404(_("Review not found"))
    try:
        repo.report(review_id, user=request.user)
    except Exception:
        pass
    messages.success(request, _("Жалоба отправлена модератору."))
    return _redirect_to_review(review)


class EmailSignupForm(forms.Form):
    """Self-service signup that uses the email address as the username."""

    email = forms.EmailField(label=_("Email"))
    password1 = forms.CharField(label=_("Пароль"), widget=forms.PasswordInput)
    password2 = forms.CharField(label=_("Повторите пароль"), widget=forms.PasswordInput)

    def clean_email(self):
        """Normalize the email and reject duplicates (case-insensitive)."""
        email = self.cleaned_data["email"].lower().strip()
        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError(_("Пользователь с таким email уже существует."))
        return email

    def clean(self):
        """Validate that both passwords match and meet the minimum length."""
        cleaned = super().clean()
        self._validate_passwords(cleaned)
        return cleaned

    @staticmethod
    def _validate_passwords(cleaned):
        """Raise a validation error for mismatched or too-short passwords."""
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError(_("Пароли не совпадают."))
        if p1 and len(p1) < 8:
            raise forms.ValidationError(_("Пароль должен быть не менее 8 символов."))

    def save(self):
        """Create and return a new user from the cleaned data."""
        email = self.cleaned_data["email"].lower().strip()
        user = User.objects.create_user(username=email, email=email, password=self.cleaned_data["password1"])
        return user


def signup(request):
    """Register a new user and log them in immediately."""
    if request.user.is_authenticated:
        return redirect("home")
    if request.method == "POST":
        form = EmailSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, _("Регистрация выполнена. Добро пожаловать!"))
            return redirect("home")
    else:
        form = EmailSignupForm()
    return render(request, "registration/signup.html", {"form": form})


def _submit_professor(form, user):
    """Submit a new professor for moderation, returning ``True`` on success.

    The user is only forwarded to ``repo.add_professor`` when the active
    backend accepts that keyword (the in-memory repository does not), so the
    same view works against both repositories.
    """
    data = form.cleaned_data
    add = repo.add_professor
    supports_user = hasattr(add, "__code__") and "user" in add.__code__.co_varnames
    args = (
        data["school"], data["first_name"].strip(), data["last_name"].strip(),
        data["department"].strip(), data["title"],
    )
    try:
        if supports_user:
            add(*args, status="pending", user=user)
        else:
            add(*args, status="pending")
    except ValueError:
        form.add_error(None, _("Преподаватель с таким ФИО уже есть в этом вузе."))
        return False
    return True


@login_required
def add_professor(request):
    """Allow a logged-in user to submit a professor for moderation."""
    schools = repo.schools()
    if request.method == "POST":
        form = ProfessorForm(request.POST, schools=schools)
        if form.is_valid() and _submit_professor(form, request.user):
            messages.success(request, _("Преподаватель отправлен на модерацию."))
            return redirect("home")
    else:
        form = ProfessorForm(schools=schools)
    return render(request, "reviews/add_professor.html", {
        "form": form,
        "login_url": reverse("login"),
        "signup_url": reverse("signup"),
    })
