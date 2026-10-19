from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST
import logging

from django import forms
from django.conf import settings
from django_ratelimit.decorators import ratelimit

from .forms import ProfessorForm, ReviewForm
from .net import client_ip
from .store import repo
from .tokens import email_confirm_token

logger = logging.getLogger(__name__)

# helpers for ratelimit keys using real IP
def _ratelimit_ip(group, request):
    return client_ip(request)

def _ratelimit_user(group, request):
    if request.user.is_authenticated:
        return str(request.user.pk)
    return client_ip(request)


def home(request):
    q = request.GET.get("q", "")[:100]
    school = request.GET.get("school", "")
    city = request.GET.get("city", "")
    results = repo.search(q, school, city)
    paginator = Paginator(results, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    if paginator.num_pages <= 1:
        page_results = results
        page_obj = None
    else:
        page_results = page_obj.object_list
    schools = repo.schools()
    from collections import defaultdict
    by_city = defaultdict(list)
    for s in schools:
        by_city[s.city].append(s)
    grouped = sorted(by_city.items())
    return render(request, "reviews/home.html", {
        "q": q, "school": school, "city": city,
        "schools": schools,
        "grouped_schools": grouped,
        "cities": repo.cities() if hasattr(repo, "cities") else sorted({s.city for s in schools}),
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


def school_list(request):
    schools = repo.schools()
    region = request.GET.get("region", "")
    type_ = request.GET.get("type", "")
    filtered = schools
    if region:
        filtered = [s for s in filtered if getattr(s, 'region', '') == region]
    if type_:
        filtered = [s for s in filtered if getattr(s, 'type', '') == type_]
    regions = sorted({getattr(s, 'region', '') for s in schools if getattr(s, 'region', '')})
    return render(request, "reviews/schools.html", {
        "schools": filtered,
        "regions": regions,
        "region": region,
        "type": type_,
    })


def school_detail(request, slug):
    school = repo.school_by_slug(slug) if hasattr(repo, "school_by_slug") else next((s for s in repo.schools() if s.slug == slug), None)
    if school is None:
        raise Http404("School not found")
    results = [r for r in repo.search("", school_slug=school.slug)]
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


def privacy(request):
    return render(request, "reviews/privacy.html")


@login_required
def delete_account(request):
    if request.method == "POST":
        user = request.user
        try:
            from .models import Review
            Review.objects.filter(author=user).update(author=None)
        except Exception:  # keep anonymization best-effort on delete  # nosec B110
            logger.exception("delete_account anonymize failed for user %s", user.pk)
        from django.contrib.auth import logout
        logout(request)
        user.delete()
        messages.success(request, _("Аккаунт удалён. Отзывы остались анонимными."))
        return redirect("home")
    return render(request, "reviews/delete_account.html")


@login_required
@ratelimit(key=_ratelimit_user, rate="5/d", method="POST", block=True)
def review_new(request, slug):
    # email confirmed gate via Profile
    from .models import Profile
    try:
        prof_conf = request.user.profile.email_confirmed
    except Exception:
        prof_conf = False
    if not prof_conf:
        messages.warning(request, _("Подтвердите email, прежде чем оставлять отзывы."))
        return redirect("home")
    prof = _professor_or_404(slug)
    if request.method == "POST":
        form = ReviewForm(request.POST)
        if form.is_valid():
            try:
                repo.add_review(prof.id, form.cleaned_data, user=request.user)
            except ValueError as e:
                if "duplicate" in str(e).lower():
                    form.add_error("course", _("Вы уже оставляли отзыв для этого предмета у этого преподавателя."))
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


@login_required
@ratelimit(key=_ratelimit_user, rate="60/h", method="POST", block=True)
@require_POST
def review_vote(request, review_id):
    review = repo.review(review_id)
    if review is None:
        raise Http404("Review not found")
    if getattr(review, 'status', 'approved') != 'approved':
        raise Http404("Review not found")
    if getattr(review, 'author_id', None) == request.user.id:
        return HttpResponseForbidden(_("Нельзя голосовать за свой отзыв."))
    try:
        repo.vote(review_id, helpful=request.POST.get("vote") == "up", user=request.user)
    except ValueError:
        messages.warning(request, _("Вы уже голосовали за этот отзыв."))
    prof = repo.professor_by_id(review.professor_id)
    if prof:
        return redirect(reverse("professor", args=[prof.slug]) + f"#review-{review.id}")
    return redirect("home")


@login_required
@ratelimit(key=_ratelimit_user, rate="20/h", method="POST", block=True)
@require_POST
def review_report(request, review_id):
    review = repo.review(review_id)
    if review is None:
        raise Http404("Review not found")
    if getattr(review, 'status', 'approved') != 'approved':
        raise Http404("Review not found")
    if getattr(review, 'author_id', None) == request.user.id:
        return HttpResponseForbidden(_("Нельзя жаловаться на свой отзыв."))
    if hasattr(repo, "report"):
        try:
            repo.report(review_id, user=request.user)
        except ValueError:
            messages.warning(request, _("Вы уже жаловались на этот отзыв."))
            prof2 = repo.professor_by_id(review.professor_id)
            if prof2:
                return redirect(reverse("professor", args=[prof2.slug]) + f"#review-{review.id}")
            return redirect("home")
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
        return self.cleaned_data["email"].lower().strip()

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError(_("Пароли не совпадают."))
        if p1:
            try:
                validate_password(p1)
            except ValidationError as e:
                raise forms.ValidationError(e.messages)
        return cleaned

    def save(self, request=None, commit=True):
        email = self.cleaned_data["email"].lower().strip()
        user = User.objects.create_user(username=email, email=email, password=self.cleaned_data["password1"], is_active=False)
        from .models import Profile
        Profile.objects.get_or_create(user=user, defaults={"email_confirmed": False})
        token = email_confirm_token.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        confirm_url = request.build_absolute_uri(reverse("confirm_email", args=[uid, token])) if request else f"/accounts/confirm/{uid}/{token}/"
        subject = _("Подтвердите email — ProfLens")
        body = _("Перейдите по ссылке для подтверждения (24 часа): %(url)s") % {"url": confirm_url}
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=True)
        except Exception:  # email backend may be misconfigured  # nosec B110
            logger.exception("send confirmation email failed for %s", email)
        return user


@ratelimit(key=_ratelimit_ip, rate="5/h", method="POST", block=True)
def signup(request):
    if request.user.is_authenticated:
        return redirect("home")
    if request.method == "POST":
        form = EmailSignupForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"].lower().strip()
            existing = User.objects.filter(email__iexact=email).first() or User.objects.filter(username__iexact=email).first()
            if existing:
                try:
                    send_mail(
                        _("Вы уже зарегистрированы — ProfLens"),
                        _("Кто-то попытался зарегистрироваться с вашим email. Если это были не вы — проигнорируйте письмо."),
                        settings.DEFAULT_FROM_EMAIL, [email], fail_silently=True
                    )
                except Exception:  # nosec B110
                    logger.exception("send already-registered email failed for %s", email)
                messages.success(request, _("Если email существует, мы отправили письмо. Проверьте почту."))
                return render(request, "registration/signup.html", {"form": form, "sent": True})
            user = form.save(request=request)
            messages.success(request, _("Проверьте почту — мы отправили ссылку для подтверждения (24 часа)."))
            return render(request, "registration/signup.html", {"form": form, "sent": True})
    else:
        form = EmailSignupForm()
    return render(request, "registration/signup.html", {"form": form})


def confirm_email(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except Exception:
        user = None
    if user and email_confirm_token.check_token(user, token):
        # one-time: only activate if email not yet confirmed
        from .models import Profile
        profile, _created = Profile.objects.get_or_create(user=user, defaults={"email_confirmed": False})
        if profile.email_confirmed:
            messages.error(request, _("Ссылка недействительна или просрочена."))
            return redirect("signup")
        user.is_active = True
        user.save(update_fields=["is_active"])
        profile.email_confirmed = True
        profile.save(update_fields=["email_confirmed"])
        messages.success(request, _("Email подтверждён. Войдите."))
        return redirect("login")
    messages.error(request, _("Ссылка недействительна или просрочена."))
    return redirect("signup")


@login_required
@ratelimit(key=_ratelimit_user, rate="5/d", method="POST", block=True)
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
                    user=request.user,
                )
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


def ratelimited(request, exception=None):
    return render(request, "reviews/429.html", status=429)


def permission_denied(request, exception=None):
    from django_ratelimit.exceptions import Ratelimited

    if isinstance(exception, Ratelimited):
        return render(request, "reviews/429.html", status=429)
    from django.views.defaults import permission_denied as _pd

    return _pd(request, exception)
