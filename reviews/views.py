from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from . import store
from .geo import REGION_CODES, REGION_PREFIX, build_locations, filter_schools, parse_place, region_name

REGION_ORDER = {code: i for i, code in enumerate(REGION_CODES)}
from .accounts import get_profile, is_verified, send_verification_email, token_generator, verified_required
from .forms import EmailAuthenticationForm, EmailSignupForm, ProfessorForm, ReviewForm
from .ratelimit import ratelimit

PAGE_SIZE = 20
MAX_QUERY_LENGTH = 100


def _repo():
    # read at call time so tests can swap store.repo
    return store.repo


def _page(request, items, per_page=PAGE_SIZE):
    """Return (current page items, page object or None when everything fits one page)."""
    paginator = Paginator(items, per_page)
    page_obj = paginator.get_page(request.GET.get("page"))
    return list(page_obj.object_list), (page_obj if paginator.num_pages > 1 else None)


def _school_groups(all_schools, visible_slugs):
    """Schools for the <select>, grouped by region in the fixed region order."""
    groups = {}
    for s in sorted(all_schools, key=lambda s: s.display_name.lower()):
        groups.setdefault(s.region, []).append(s)
    return [{"name": region_name(code) or "—", "schools": groups[code],
             "visible": any(s.slug in visible_slugs for s in groups[code])}
            for code in sorted(groups, key=lambda c: REGION_ORDER.get(c, 99))]


@require_GET
def home(request):
    repo = _repo()
    q = request.GET.get("q", "").strip()[:MAX_QUERY_LENGTH]
    school = request.GET.get("school", "")[:220]
    place = request.GET.get("city", "")[:80]
    region, city = parse_place(place)
    if not region and not city:
        # ?region=chuy is accepted too (links from school pages)
        region, _city = parse_place(REGION_PREFIX + request.GET.get("region", "")[:20])
        place = REGION_PREFIX + region if region else ""
    all_schools = repo.schools()  # one query (or cache hit) feeds both selects
    schools = filter_schools(all_schools, region, city)
    if school and not any(s.slug == school for s in schools):
        # the chosen school is not in the chosen place: the place wins
        school = ""
    results, page_obj = _page(request, repo.search(q, school, city, region))
    return render(request, "reviews/home.html", {
        "q": q, "school": school, "city": place,
        "schools": schools,
        "school_slugs": {s.slug for s in schools},
        "school_groups": _school_groups(all_schools, {s.slug for s in schools}),
        "locations": build_locations(all_schools),
        "results": results,
        "page_obj": page_obj,
    })


def _professor_or_404(slug):
    prof = _repo().professor(slug)
    if prof is None:
        raise Http404("Professor not found")
    return prof


@require_GET
def professor_detail(request, slug):
    repo = _repo()
    prof = _professor_or_404(slug)
    sort = "helpful" if request.GET.get("sort") == "helpful" else "newest"
    reviews, page_obj = _page(request, repo.reviews_for(prof.id, sort), per_page=10)
    return render(request, "reviews/professor.html", {
        "prof": prof, "school": repo.school(prof.school_id), "stats": repo.stats(prof.id),
        "reviews": reviews, "sort": sort, "page_obj": page_obj,
    })


@require_GET
def school_detail(request, slug):
    repo = _repo()
    school = repo.school_by_slug(slug)
    if school is None:
        raise Http404("School not found")
    results, page_obj = _page(request, repo.search("", school_slug=school.slug))
    return render(request, "reviews/school.html", {
        "school": school, "results": results, "page_obj": page_obj,
        "stats": repo.school_stats(school.id),
        "departments": repo.departments_for_school(school.id),
    })


@require_GET
def rules(request):
    return render(request, "reviews/rules.html")


@ratelimit("review")
@login_required
@verified_required
def review_new(request, slug):
    repo = _repo()
    prof = _professor_or_404(slug)
    if request.method == "POST":
        form = ReviewForm(request.POST)
        if form.is_valid():
            try:
                repo.add_review(prof.id, form.cleaned_data, user=request.user)
            except ValueError:
                form.add_error("course", _("Вы уже оставляли отзыв для этого предмета у этого преподавателя."))
            else:
                messages.success(request, _("Отзыв отправлен на модерацию. Спасибо!"))
                return redirect("professor", slug=prof.slug)
    else:
        form = ReviewForm()
    return render(request, "reviews/review_form.html", {"prof": prof, "form": form})


def _approved_review_or_404(review_id):
    review = _repo().review(review_id)
    if review is None or review.status != "approved":
        raise Http404("Review not found")
    return review


def _back_to_review(review):
    prof = _repo().professor_by_id(review.professor_id)
    if prof:
        return redirect(reverse("professor", args=[prof.slug]) + f"#review-{review.id}")
    return redirect("home")


@require_POST
@ratelimit("vote")
@login_required
@verified_required
def review_vote(request, review_id):
    choice = request.POST.get("vote")
    if choice not in ("up", "down"):
        return HttpResponseBadRequest("vote must be up or down")
    review = _approved_review_or_404(review_id)
    if review.author_id is not None and review.author_id == request.user.id:
        messages.warning(request, _("Нельзя голосовать за свой отзыв."))
        return _back_to_review(review)
    try:
        _repo().vote(review.id, helpful=choice == "up", user=request.user)
    except ValueError:
        messages.warning(request, _("Вы уже голосовали за этот отзыв."))
    return _back_to_review(review)


@require_POST
@ratelimit("report")
@login_required
@verified_required
def review_report(request, review_id):
    review = _approved_review_or_404(review_id)
    _repo().report(review.id, user=request.user)
    messages.success(request, _("Жалоба отправлена модератору."))
    return _back_to_review(review)


@ratelimit("add_professor")
@login_required
@verified_required
def add_professor(request):
    repo = _repo()
    schools = repo.schools()
    if request.method == "POST":
        form = ProfessorForm(request.POST, schools=schools)
        if form.is_valid():
            data = form.cleaned_data
            try:
                repo.add_professor(data["school"], data["first_name"], data["last_name"],
                                   data["department"], data["title"], status="pending", user=request.user)
            except ValueError:
                form.add_error(None, _("Преподаватель с таким ФИО уже есть в этом вузе."))
            else:
                messages.success(request, _("Преподаватель отправлен на модерацию."))
                return redirect("home")
    else:
        form = ProfessorForm(schools=schools)
    return render(request, "reviews/add_professor.html", {"form": form})


# ---------- accounts ----------

class LoginView(auth_views.LoginView):
    template_name = "registration/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True


login_view = ratelimit("login")(LoginView.as_view())


@ratelimit("signup")
def signup(request):
    if request.user.is_authenticated:
        return redirect("home")
    if request.method == "POST":
        form = EmailSignupForm(request.POST)
        if form.is_valid():
            user = form.save()
            if user is not None:
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                send_verification_email(request, user)
                messages.success(request, _("Регистрация выполнена. Мы отправили письмо для подтверждения email."))
                return redirect("home")
    else:
        form = EmailSignupForm()
    return render(request, "registration/signup.html", {"form": form})


@require_GET
def verify_email(request, uidb64, token):
    User = get_user_model()
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)))
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None
    if user is None or not token_generator.check_token(user, token):
        return render(request, "registration/verify_email.html", {"ok": False}, status=400)
    profile = get_profile(user)
    profile.email_verified = True
    profile.email_verified_at = timezone.now()
    profile.save(update_fields=["email_verified", "email_verified_at"])
    # note: we deliberately do NOT log the user in and do NOT touch user.is_active
    return render(request, "registration/verify_email.html", {"ok": True})


@ratelimit("resend_verification")
@login_required
def verification_needed(request):
    if is_verified(request.user):
        return redirect("home")
    if request.method == "POST":
        if send_verification_email(request, request.user):
            messages.success(request, _("Письмо отправлено ещё раз."))
        else:
            messages.error(request, _("Не удалось отправить письмо, попробуйте позже."))
        return redirect("verification_needed")
    return render(request, "registration/verification_needed.html", {
        "required": settings.REQUIRE_EMAIL_VERIFICATION,
    })

