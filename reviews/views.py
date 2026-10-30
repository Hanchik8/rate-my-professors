"""HTTP views for the ProfLens review app.

Views stay thin: they translate request parameters into repository calls
and render templates, so that no storage detail leaks into the request
layer.  Reusable pieces (pagination, filter parsing, moderation redirects)
live in small private helpers below.
"""
from django import forms
from django.conf import settings
from django.contrib import messages
from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import connection
from django.http import HttpResponse, JsonResponse
import json
from django.shortcuts import redirect, render, resolve_url
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_http_methods, require_POST
from django.views.defaults import page_not_found, server_error

from .caching import (
    get_or_set,
    home_cache_key,
    options_cache_key,
    school_cache_key,
)
from .forms import ProfessorForm, ReportForm, ReviewForm
from . import email_verification, services, view_helpers
from .models import EmailVerification as EmailVerificationModel
from .store import repo
from .throttle import is_rate_limited, rate_limit
from .view_helpers import (
    _is_author,
    _object_or_404,
    _paginate,
    _paginate_request,
)


def handler404(request, exception=None):
    """Render the project's translated 404 template."""
    return page_not_found(request, exception, template_name="404.html")


def handler500(request):
    """Render the project's 500 template without touching the database."""
    return server_error(request, template_name="500.html")


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


def _form_for_request(request, form_class, **kwargs):
    """Return a form bound to POST data, or an unbound form otherwise."""
    data = request.POST if request.method == "POST" else None
    return form_class(data, **kwargs)


def _is_valid_post(request, form):
    """Return ``True`` when ``request`` is a POST with a valid ``form``."""
    return request.method == "POST" and form.is_valid()


def _sort_param(request, allowed, default, aliases=None):
    """Return a validated sort key from the query string."""
    sort = request.GET.get("sort", default)
    if aliases:
        sort = aliases.get(sort, sort)
    return sort if sort in allowed else default


def _home_filters(request):
    """Parse and normalize the home page's search/filter query string."""
    q = request.GET.get("q", "")
    school = request.GET.get("school", "")
    city = request.GET.get("city", "")
    department = request.GET.get("department", "")
    sort = _sort_param(request, ("rating", "reviews"), "rating")
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
        lambda: {"results": services.search_professors(
            repo, q, school=school, city=city, department=department, sort=sort,
        )},
    )
    page_results, page_obj = _paginate_request(request, data["results"])
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


def professor_detail(request, slug):
    """Show a professor profile with aggregate stats and paginated reviews."""
    prof = _professor_or_404(slug)
    sort = _sort_param(
        request,
        ("new", "old", "high", "low", "helpful"),
        "new",
        aliases={"newest": "new"},
    )
    all_reviews = repo.reviews_for(prof.id, sort)
    reviews, page_obj = _paginate_request(request, all_reviews)
    stats = repo.stats(prof.id)
    person_schema = {
        "@context": "https://schema.org",
        "@type": "Person",
        "name": prof.full_name,
        "url": (
            f"{settings.SITE_URL}{reverse('professor', args=[prof.slug])}"
            if settings.SITE_URL
            else request.build_absolute_uri(reverse("professor", args=[prof.slug]))
        ),
    }
    if stats["count"]:
        person_schema["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": stats["overall"],
            "reviewCount": stats["count"],
        }
    person_jsonld = json.dumps(person_schema, ensure_ascii=False)
    person_jsonld = (person_jsonld.replace("&", "\\u0026")
                     .replace("<", "\\u003c").replace(">", "\\u003e"))
    return render(request, "reviews/professor.html", {
        "prof": prof, "school": repo.school(prof.school_id), "stats": stats,
        "person_jsonld": person_jsonld,
        "reviews": reviews, "sort": sort, "page_obj": page_obj,
        "sort_options": [("new", "сначала новые"), ("old", "сначала старые"), ("high", "сначала высокая оценка"),
                         ("low", "сначала низкая оценка"), ("helpful", "сначала полезные")],
        "report_form": ReportForm(auto_id=False),
    })


def _school_or_404(slug):
    """Fetch a school by slug or raise ``Http404``."""
    return _object_or_404(repo.school_by_slug(slug), _("School not found"))


def _school_context(school, request):
    """Build the template context for a school page."""
    # Search already returns batched stats for every approved professor; reuse
    # them here instead of issuing the separate school_stats query set.
    data = get_or_set(school_cache_key(school.slug), lambda: {
        "results": services.professors_for_school(repo, school.slug),
    })
    results = data["results"]
    rated = [r["stats"]["overall"] for r in results if r["stats"]["count"]]
    stats = {
        "prof_count": len(results),
        "review_count": sum(r["stats"]["count"] for r in results),
        "avg_overall": round(sum(rated) / len(rated), 1) if rated else 0,
    }
    page_results, page_obj = _paginate_request(request, results)
    return {
        "school": school,
        "results": page_results,
        "stats": stats,
        "departments": sorted({r["prof"].department for r in results}),
        "page_obj": page_obj,
    }


def school_detail(request, slug):
    """Show a school page: its professors, aggregate stats and departments."""
    school = _school_or_404(slug)
    return render(
        request,
        "reviews/school.html",
        _school_context(school, request),
    )


def rules(request):
    """Render the community rules page."""
    return render(request, "reviews/rules.html")


def about(request):
    """Render the about page."""
    return render(request, "reviews/about.html")


def _owned_review_or_404(review_id, user):
    """Fetch a review owned by ``user`` or raise ``Http404``."""
    return view_helpers._owned_review_or_404(repo, review_id, user)


def _professor_for_review(review):
    """Return the professor a review belongs to."""
    return view_helpers._professor_for_review(repo, review)


def _review_initial(review):
    """Return the initial form values for editing an existing review."""
    return {
        "course": review.course,
        "term": review.term,
        "overall": review.overall,
        "difficulty": review.difficulty,
        "would_take_again": "yes" if review.would_take_again else "no",
        "grade": review.grade,
        "tags": review.tags,
        "comment": review.comment,
    }


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


def _review_form_context(prof, form, *, editing=False):
    """Build the shared context for creating or editing a review."""
    context = {"prof": prof, "form": form, "url": reverse("rules")}
    if editing:
        context["editing"] = True
    else:
        context.update(_account_urls())
    return context


@require_http_methods(["GET", "POST"])
@login_required
@rate_limit("review")
def review_new(request, slug):
    """Create a review for a professor; new reviews await moderation."""
    prof = _professor_or_404(slug)
    form = _form_for_request(request, ReviewForm)
    if _is_valid_post(request, form) and _save_review(form, prof, request):
        return redirect("professor", slug=prof.slug)
    return render(
        request,
        "reviews/review_form.html",
        _review_form_context(prof, form),
    )


def _redirect_to_review(review):
    """Redirect back to the review's anchor on its professor page."""
    return view_helpers._redirect_to_review(repo, review)


def _review_or_404(review_id):
    """Fetch a review or raise ``Http404`` when it does not exist."""
    return view_helpers._review_or_404(repo, review_id)


from .views_votes import review_report, review_vote
from .views_profile import profile, review_delete, review_edit


def _requested_next_url(request):
    """Return a ``next`` URL from the request, preferring POST data."""
    target = request.POST.get("next") or request.GET.get("next")
    if target and url_has_allowed_host_and_scheme(
        url=target,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return target
    return None


def _safe_next_url(request, default):
    """Return the requested ``next`` URL only if it stays on this host."""
    return _requested_next_url(request) or default


def _auth_success_url(request, default_setting):
    """Return a safe requested URL, or the resolved auth redirect default."""
    return _safe_next_url(request, resolve_url(default_setting))


class ThrottledLoginView(auth_views.LoginView):
    """Login view with a simple per-IP attempt limit backed by the cache."""

    def post(self, request, *args, **kwargs):
        """Reject the request when the per-IP login rate limit is exceeded."""
        if is_rate_limited(request, "login"):
            return HttpResponse(
                _("Слишком много попыток входа. Попробуйте позже."), status=429
            )
        return super().post(request, *args, **kwargs)

    def get_success_url(self):
        """Redirect to a validated local ``next`` URL, else to the default."""
        return _auth_success_url(self.request, settings.LOGIN_REDIRECT_URL)

    def form_invalid(self, form):
        """Explain that an unconfirmed account needs its email code first.

        The hint only appears when the password is correct, so it does not
        reveal which addresses are registered.
        """
        username = _normalize_email(form.data.get("username", "") or "")
        password = form.data.get("password", "") or ""
        user = User.objects.filter(username__iexact=username, is_active=False).first() if username else None
        if user is not None and password and user.check_password(password) and (
            EmailVerificationModel.objects.filter(user=user).exists()
        ):
            self.request.session[VERIFY_SESSION_KEY] = user.email
            form._errors.clear()
            return self.render_to_response(self.get_context_data(form=form, unverified=True))
        return super().form_invalid(form)


class SafeLogoutView(auth_views.LogoutView):
    """Logout view that never follows an off-site ``next`` parameter."""

    def get_success_url(self):
        """Redirect to a validated local ``next`` URL, else to the default."""
        return _auth_success_url(self.request, settings.LOGOUT_REDIRECT_URL)


def _normalize_email(email):
    """Return an email address lowercased and stripped of whitespace."""
    return email.lower().strip()


class EmailSignupForm(forms.Form):
    """Self-service signup that uses the email address as the username."""

    email = forms.EmailField(label=gettext_lazy("Email"))
    password1 = forms.CharField(label=gettext_lazy("Пароль"), widget=forms.PasswordInput)
    password2 = forms.CharField(label=gettext_lazy("Повторите пароль"), widget=forms.PasswordInput)

    def clean_email(self):
        """Normalize the email and reject duplicates (case-insensitive).

        The signup page offers login and password-reset links, but never
        reveals whether the existing account has already confirmed its email.
        """
        email = _normalize_email(self.cleaned_data["email"])
        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
            self.duplicate_email = True
            raise forms.ValidationError(
                _("Этот email уже зарегистрирован. Войдите или восстановите пароль.")
            )
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
        email = _normalize_email(self.cleaned_data["email"])
        user = User.objects.create_user(username=email, email=email, password=self.cleaned_data["password1"])
        return user


VERIFY_SESSION_KEY = "verify_email"


class VerifyCodeForm(forms.Form):
    """Six-digit email confirmation code."""

    code = forms.RegexField(
        label=_("Код из письма"),
        regex=r"^\s*\d{6}\s*$",
        max_length=12,
        error_messages={"invalid": _("Введите 6 цифр из письма.")},
        widget=forms.TextInput(attrs={
            "inputmode": "numeric", "autocomplete": "one-time-code", "pattern": "[0-9]{6}", "maxlength": "6",
        }),
    )


def _start_verification(request, user):
    """Send the first code and remember whom the verify page is for."""
    request.session[VERIFY_SESSION_KEY] = user.email
    if email_verification.issue_code(user):
        messages.success(request, _("Мы отправили 6-значный код на %(email)s. Введите его, чтобы завершить регистрацию.") % {"email": user.email})
    else:
        _email_delivery_failed(request)


def _email_delivery_failed(request):
    """Show the shared error message when a verification email cannot be sent."""
    messages.error(request, _("Не удалось отправить письмо с кодом. Попробуйте отправить код ещё раз чуть позже."))


@require_http_methods(["GET", "POST"])
@rate_limit("signup")
def signup(request):
    """Register a new user; confirm the email by code before the first login."""
    if request.user.is_authenticated:
        return redirect("home")
    form = _form_for_request(request, EmailSignupForm)
    if _is_valid_post(request, form):
        user = form.save()
        if email_verification.is_required():
            user.is_active = False
            user.save(update_fields=["is_active"])
            _start_verification(request, user)
            return redirect("signup_verify")
        login(request, user)
        messages.success(request, _("Регистрация выполнена. Добро пожаловать!"))
        return redirect("home")
    return render(request, "registration/signup.html", {
        "form": form,
        "duplicate_email": getattr(form, "duplicate_email", False),
    })


def _pending_user(request):
    """Return the inactive user whose email is waiting for confirmation."""
    email = request.session.get(VERIFY_SESSION_KEY)
    if not email:
        return None
    return User.objects.filter(username__iexact=email, is_active=False).first()


def _handle_resend(request, user):
    if is_rate_limited(request, "resend"):
        result = None
    else:
        result = email_verification.resend_code(user)
    if result is None or not result.sent:
        wait = result.wait if result else email_verification.resend_interval()
        messages.warning(request, _("Новый код можно запросить через %(seconds)s с.") % {"seconds": wait})
    elif result.delivered:
        messages.success(request, _("Новый код отправлен на %(email)s.") % {"email": user.email})
    else:
        _email_delivery_failed(request)
    return redirect("signup_verify")


_VERIFY_ERRORS = {
    email_verification.WRONG: lambda: _("Неверный код. Проверьте письмо и попробуйте ещё раз."),
    email_verification.EXPIRED: lambda: _("Срок действия кода истёк. Запросите новый код."),
    email_verification.LOCKED: lambda: _("Слишком много неверных попыток. Запросите новый код."),
    email_verification.MISSING: lambda: _("Код не найден. Запросите новый код."),
}


@require_http_methods(["GET", "POST"])
@rate_limit("verify")
def signup_verify(request):
    """Enter the emailed code to activate the account, or ask for a new one."""
    if request.user.is_authenticated:
        return redirect("home")
    user = _pending_user(request)
    if user is None:
        request.session.pop(VERIFY_SESSION_KEY, None)
        messages.info(request, _("Подтверждать нечего: войдите или зарегистрируйтесь."))
        return redirect("login")
    if request.method == "POST" and request.POST.get("action") == "resend":
        return _handle_resend(request, user)
    form = _form_for_request(request, VerifyCodeForm)
    if _is_valid_post(request, form):
        status = email_verification.check_code(user, form.cleaned_data["code"].strip())
        if status == email_verification.OK:
            user.is_active = True
            user.save(update_fields=["is_active"])
            request.session.pop(VERIFY_SESSION_KEY, None)
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, _("Email подтверждён. Добро пожаловать!"))
            return redirect("home")
        form.add_error("code", _VERIFY_ERRORS[status]())
    context = {
        "form": form,
        "email": user.email,
        "resend_wait": email_verification.seconds_until_resend(getattr(user, "email_verification", None)),
    }
    return render(request, "registration/signup_verify.html", context)


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


def _existing_professor(form):
    """Return the professor that made ``form`` fail the duplicate check."""
    data = form.cleaned_data
    return repo.professor_by_name(
        data["school"], data["first_name"], data["last_name"],
    )


@require_http_methods(["GET", "POST"])
@login_required
@rate_limit("review")
def add_professor(request):
    """Allow a logged-in user to submit a professor for moderation."""
    schools = repo.schools()
    form = _form_for_request(request, ProfessorForm, schools=schools)
    context = {"form": form, **_account_urls()}
    if _is_valid_post(request, form):
        if _submit_professor(form, request.user):
            messages.success(request, _("Преподаватель отправлен на модерацию."))
            return redirect("home")
        existing = _existing_professor(form)
        if existing is not None:
            context["professor"] = existing
    return render(request, "reviews/add_professor.html", context)
