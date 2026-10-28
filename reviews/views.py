"""HTTP views for the ProfLens review app.

Views stay thin: they translate request parameters into repository calls
and render templates, so that no storage detail leaks into the request
layer.  Reusable pieces (pagination, filter parsing, moderation redirects)
live in small private helpers below.
"""
from django import forms
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import connection
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST, require_http_methods

from .caching import (
    get_or_set,
    home_cache_key,
    options_cache_key,
    school_cache_key,
)
from .constants import PAGE_SIZE
from .forms import ProfessorForm, ReportForm, ReviewForm
from .store import repo
from .throttle import is_rate_limited, rate_limit


def health(request):
    """Liveness endpoint used by the container orchestrator."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return JsonResponse({"status": "error"}, status=503)
    return JsonResponse({"status": "ok"})


def healthz(request):
    """Return a database-independent liveness response."""
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


def _home_options():
    """Return cached filter option lists shared by every home search."""
    return get_or_set(options_cache_key(), lambda: {
        "schools": repo.schools(),
        "cities": repo.cities(),
        "departments": repo.departments(),
    })


def home(request):
    """Search/browse professors with filters, sorting and pagination."""
    q, school, city, department, sort = _home_filters(request)
    options = _home_options()
    data = get_or_set(
        home_cache_key(q, school, city, department, sort),
        lambda: {"results": repo.search(q, school, city, department, sort)},
    )
    page_results, page_obj = _paginate(data["results"], request.GET.get("page"))
    return render(request, "reviews/home.html", {
        "q": q, "school": school, "city": city,
        "department": department, "sort": sort,
        "schools": options["schools"],
        "cities": options["cities"],
        "departments": options["departments"],
        "results": page_results,
        "page_obj": page_obj,
    })


def _professor_or_404(slug):
    """Fetch an approved professor by slug or raise ``Http404``."""
    return _object_or_404(repo.professor(slug), _("Professor not found"))


def _object_or_404(obj, message):
    """Return ``obj`` or raise ``Http404`` with the supplied message."""
    if obj is None:
        raise Http404(message)
    return obj


def professor_detail(request, slug):
    """Show a professor profile with aggregate stats and paginated reviews."""
    prof = _professor_or_404(slug)
    sort = request.GET.get("sort", "new")
    if sort == "newest":
        sort = "new"
    if sort not in ("new", "old", "high", "low", "helpful"):
        sort = "new"
    all_reviews = repo.reviews_for(prof.id, sort)
    reviews, page_obj = _paginate(all_reviews, request.GET.get("page"))
    return render(request, "reviews/professor.html", {
        "prof": prof, "school": repo.school(prof.school_id), "stats": repo.stats(prof.id),
        "reviews": reviews, "sort": sort, "page_obj": page_obj,
        "sort_options": [("new", "сначала новые"), ("old", "сначала старые"), ("high", "сначала высокая оценка"),
                         ("low", "сначала низкая оценка"), ("helpful", "сначала полезные")],
        "report_form": ReportForm(auto_id=False),
    })


def _school_or_404(slug):
    """Fetch a school by slug or raise ``Http404``."""
    return _object_or_404(repo.school_by_slug(slug), _("School not found"))


def _school_context(school, page_number):
    """Build the template context for a school page."""
    data = get_or_set(school_cache_key(school.slug), lambda: {
        "results": repo.search("", school_slug=school.slug),
        "stats": repo.school_stats(school.id),
    })
    results = data["results"]
    page_results, page_obj = _paginate(results, page_number)
    return {
        "school": school,
        "results": page_results,
        "stats": data["stats"],
        "departments": sorted({r["prof"].department for r in results}),
        "page_obj": page_obj,
    }


def school_detail(request, slug):
    """Show a school page: its professors, aggregate stats and departments."""
    school = _school_or_404(slug)
    return render(
        request,
        "reviews/school.html",
        _school_context(school, request.GET.get("page")),
    )


def rules(request):
    """Render the community rules page."""
    return render(request, "reviews/rules.html")


def about(request):
    """Render the about page."""
    return render(request, "reviews/about.html")


@login_required
def profile(request):
    """Show the current user's reviews and their moderation status."""
    return render(request, "reviews/profile.html", {
        "reviews": repo.reviews_for_user(request.user),
    })


def _owned_review_or_404(review_id, user):
    review = _review_or_404(review_id)
    if str(review.author_id) != str(user.id):
        raise Http404(_("Review not found"))
    return review


@require_http_methods(["GET", "POST"])
@login_required
def review_edit(request, review_id):
    review = _owned_review_or_404(review_id, request.user)
    prof = repo.professor_by_id(review.professor_id)
    if request.method == "POST":
        form = ReviewForm(request.POST)
        if form.is_valid():
            repo.update_review(review_id, form.cleaned_data)
            messages.success(request, _("Отзыв отправлен на модерацию."))
            return redirect("profile")
    else:
        form = ReviewForm(initial={"course": review.course, "term": review.term,
            "overall": review.overall, "difficulty": review.difficulty,
            "would_take_again": "yes" if review.would_take_again else "no",
            "grade": review.grade, "tags": review.tags, "comment": review.comment})
    return render(request, "reviews/review_form.html",
                  {"prof": prof, "form": form, "editing": True, "url": reverse("rules")})


@require_http_methods(["GET", "POST"])
@login_required
def review_delete(request, review_id):
    review = _owned_review_or_404(review_id, request.user)
    if request.method == "POST":
        repo.delete_review(review_id)
        messages.success(request, _("Отзыв удалён."))
        return redirect("profile")
    return render(request, "reviews/review_confirm_delete.html", {"review": review})


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


def _account_urls():
    """Return the login and signup URLs used by account-related forms."""
    return {"login_url": reverse("login"), "signup_url": reverse("signup")}


@require_http_methods(["GET", "POST"])
@login_required
@rate_limit("review")
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
        **_account_urls(),
        "url": reverse("rules"),
    })


def _redirect_to_review(review):
    """Redirect back to the review's anchor on its professor page."""
    prof = repo.professor_by_id(review.professor_id)
    if prof:
        return redirect(reverse("professor", args=[prof.slug]) + f"#review-{review.id}")
    return redirect("home")


def _review_or_404(review_id):
    """Fetch a review or raise ``Http404`` when it does not exist."""
    review = repo.review(review_id)
    if review is None:
        raise Http404(_("Review not found"))
    return review


@require_POST
@login_required
@rate_limit("vote")
def review_vote(request, review_id):
    """Record a helpful / not-helpful vote on a review."""
    review = _review_or_404(review_id)
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
    """Flag a review for moderator attention with a validated reason."""
    review = _review_or_404(review_id)
    form = ReportForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Выберите корректную причину жалобы."))
        return _redirect_to_review(review)
    repo.report(review_id, user=request.user, reason=form.cleaned_data["reason"])
    messages.success(request, _("Жалоба отправлена модератору."))
    return _redirect_to_review(review)


class ThrottledLoginView(auth_views.LoginView):
    """Login view with a simple per-IP attempt limit backed by the cache."""

    def post(self, request, *args, **kwargs):
        """Reject the request when the per-IP login rate limit is exceeded."""
        if is_rate_limited(request, "login"):
            return HttpResponse(
                _("Слишком много попыток входа. Попробуйте позже."), status=429
            )
        return super().post(request, *args, **kwargs)


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


@require_http_methods(["GET", "POST"])
@rate_limit("signup")
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


def _professor_args(form):
    """Return positional arguments for ``repo.add_professor`` from ``form``."""
    data = form.cleaned_data
    return (
        data["school"], data["first_name"].strip(), data["last_name"].strip(),
        data["department"].strip(), data["title"],
    )


def _add_professor(add, args, user):
    """Call ``add`` with the optional ``user`` keyword when supported.

    The in-memory repository does not accept ``user`` while the ORM backend
    does, so support is detected from the callable's signature.
    """
    supports_user = hasattr(add, "__code__") and "user" in add.__code__.co_varnames
    if supports_user:
        add(*args, status="pending", user=user)
    else:
        add(*args, status="pending")


def _submit_professor(form, user):
    """Submit a new professor for moderation, returning ``True`` on success.

    A repository conflict (same full name in the same school) is attached to
    the form as a non-field error and reported as failure.
    """
    try:
        _add_professor(repo.add_professor, _professor_args(form), user)
    except ValueError:
        form.add_error(None, _("Преподаватель с таким ФИО уже есть в этом вузе."))
        return False
    return True


@require_http_methods(["GET", "POST"])
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
        **_account_urls(),
    })
