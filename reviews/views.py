from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
from django import forms

from .forms import ProfessorForm, ReviewForm
from .store import repo


def home(request):
    q = request.GET.get("q", "")
    school = request.GET.get("school", "")
    city = request.GET.get("city", "")
    department = request.GET.get("department", "")
    sort = request.GET.get("sort", "rating")
    if sort not in ("rating", "reviews"):
        sort = "rating"
    results = repo.search(q, school, city, department, sort)
    paginator = Paginator(results, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    if paginator.num_pages <= 1:
        page_results = results
        page_obj = None
    else:
        page_results = page_obj.object_list
    return render(request, "reviews/home.html", {
        "q": q, "school": school, "city": city,
        "department": department, "sort": sort,
        "schools": repo.schools(),
        "cities": repo.cities() if hasattr(repo, "cities") else sorted({s.city for s in repo.schools()}),
        "departments": repo.departments() if hasattr(repo, "departments") else sorted({r["prof"].department for r in repo.search()}),
        "results": page_results,
        "page_obj": page_obj,
    })


def _professor_or_404(slug):
    prof = repo.professor(slug)
    if prof is None:
        raise Http404("Professor not found")
    return prof


def professor_detail(request, slug):
    prof = _professor_or_404(slug)
    sort = "helpful" if request.GET.get("sort") == "helpful" else "newest"
    all_reviews = repo.reviews_for(prof.id, sort)
    paginator = Paginator(all_reviews, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    if paginator.num_pages <= 1:
        page_obj = None
        reviews = all_reviews
    else:
        reviews = page_obj.object_list
    return render(request, "reviews/professor.html", {
        "prof": prof, "school": repo.school(prof.school_id), "stats": repo.stats(prof.id),
        "reviews": reviews, "sort": sort, "page_obj": page_obj,
    })


def school_detail(request, slug):
    school = repo.school_by_slug(slug) if hasattr(repo, "school_by_slug") else next((s for s in repo.schools() if s.slug == slug), None)
    if school is None:
        raise Http404("School not found")
    results = [r for r in repo.search("", school_slug=school.slug)]
    # stats for school
    if hasattr(repo, "school_stats"):
        stats = repo.school_stats(school.id)
    else:
        stats = {"prof_count": len(results), "review_count": sum(x["stats"]["count"] for x in results), "avg_overall": 0}
    departments = sorted({r["prof"].department for r in results})
    return render(request, "reviews/school.html", {
        "school": school, "results": results, "stats": stats, "departments": departments,
    })


def rules(request):
    return render(request, "reviews/rules.html")


@login_required
def review_new(request, slug):
    prof = _professor_or_404(slug)
    if request.method == "POST":
        form = ReviewForm(request.POST)
        if form.is_valid():
            course = form.cleaned_data["course"]
            if repo.has_user_reviewed(prof.id, course, request.user):
                form.add_error("course", _("Вы уже оставляли отзыв по этому предмету у этого преподавателя."))
            else:
                try:
                    repo.add_review(prof.id, form.cleaned_data, user=request.user)
                except ValueError as e:
                    if "duplicate" in str(e).lower():
                        form.add_error("course", _("Вы уже оставляли отзыв по этому предмету у этого преподавателя."))
                    else:
                        form.add_error(None, str(e))
                else:
                    messages.success(request, _("Отзыв отправлен на модерацию. Спасибо!"))
                    return redirect("professor", slug=prof.slug)
    else:
        form = ReviewForm()
    return render(request, "reviews/review_form.html", {
        "prof": prof, "form": form,
        "login_url": reverse("login"),
        "signup_url": reverse("signup"),
        "url": reverse("rules"),
    })


@require_POST
@login_required
def review_vote(request, review_id):
    review = repo.review(review_id)
    if review is None:
        raise Http404("Review not found")
    try:
        repo.vote(review_id, helpful=request.POST.get("vote") == "up", user=request.user)
    except ValueError:
        messages.warning(request, _("Вы уже голосовали за этот отзыв."))
    prof = repo.professor_by_id(review.professor_id)
    if prof:
        return redirect(reverse("professor", args=[prof.slug]) + f"#review-{review.id}")
    return redirect("home")


@require_POST
@login_required
def review_report(request, review_id):
    review = repo.review(review_id)
    if review is None:
        raise Http404("Review not found")
    if hasattr(repo, "report"):
        try:
            repo.report(review_id, user=request.user)
        except Exception:
            pass
    messages.success(request, _("Жалоба отправлена модератору."))
    prof = repo.professor_by_id(review.professor_id)
    if prof:
        return redirect(reverse("professor", args=[prof.slug]) + f"#review-{review.id}")
    return redirect("home")


class EmailSignupForm(forms.Form):
    email = forms.EmailField(label=_("Email"))
    password1 = forms.CharField(label=_("Пароль"), widget=forms.PasswordInput)
    password2 = forms.CharField(label=_("Повторите пароль"), widget=forms.PasswordInput)

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if User.objects.filter(email__iexact=email).exists() or User.objects.filter(username__iexact=email).exists():
            raise forms.ValidationError(_("Пользователь с таким email уже существует."))
        return email

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError(_("Пароли не совпадают."))
        if p1 and len(p1) < 8:
            raise forms.ValidationError(_("Пароль должен быть не менее 8 символов."))
        return cleaned

    def save(self):
        email = self.cleaned_data["email"].lower().strip()
        user = User.objects.create_user(username=email, email=email, password=self.cleaned_data["password1"])
        return user


def signup(request):
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


@login_required
def add_professor(request):
    schools = repo.schools()
    if request.method == "POST":
        form = ProfessorForm(request.POST, schools=schools)
        if form.is_valid():
            try:
                repo.add_professor(
                    form.cleaned_data["school"],
                    form.cleaned_data["first_name"].strip(),
                    form.cleaned_data["last_name"].strip(),
                    form.cleaned_data["department"].strip(),
                    form.cleaned_data["title"],
                    status="pending",
                    user=request.user if hasattr(repo, "add_professor") and "user" in repo.add_professor.__code__.co_varnames else None,
                )
            except TypeError:
                # InMemoryRepository fallback without user param
                try:
                    repo.add_professor(
                        form.cleaned_data["school"],
                        form.cleaned_data["first_name"].strip(),
                        form.cleaned_data["last_name"].strip(),
                        form.cleaned_data["department"].strip(),
                        form.cleaned_data["title"],
                        status="pending",
                    )
                except ValueError as e:
                    form.add_error(None, _("Преподаватель с таким ФИО уже есть в этом вузе."))
                else:
                    messages.success(request, _("Преподаватель отправлен на модерацию."))
                    return redirect("home")
            except ValueError:
                form.add_error(None, _("Преподаватель с таким ФИО уже есть в этом вузе."))
            else:
                messages.success(request, _("Преподаватель отправлен на модерацию."))
                return redirect("home")
    else:
        form = ProfessorForm(schools=schools)
    return render(request, "reviews/add_professor.html", {
        "form": form,
        "login_url": reverse("login"),
        "signup_url": reverse("signup"),
    })
