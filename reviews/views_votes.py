"""Review voting and reporting views."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .throttle import rate_limit


def _review_or_404(review_id):
    from . import views
    return views._object_or_404(views.repo.review(review_id), _("Review not found"))


def _is_author(obj, user):
    return obj.author_id is not None and str(obj.author_id) == str(user.id)


def _professor_for_review(review):
    from . import views
    return views.repo.professor_by_id(review.professor_id)


def _redirect_to_review(review):
    prof = _professor_for_review(review)
    if prof:
        return redirect(reverse("professor", args=[prof.slug]) + f"#review-{review.id}")
    return redirect("home")


@require_POST
@login_required
@rate_limit("vote")
def review_vote(request, review_id):
    from . import views
    review = views._review_or_404(review_id)
    if views._is_author(review, request.user):
        messages.warning(request, _("Нельзя голосовать за свой отзыв."))
        return views._redirect_to_review(review)
    try:
        views.repo.vote(review_id, helpful=request.POST.get("vote") == "up", user=request.user)
    except ValueError:
        messages.warning(request, _("Вы уже голосовали за этот отзыв."))
    return views._redirect_to_review(review)


@require_POST
@login_required
@rate_limit("report")
def review_report(request, review_id):
    from . import views
    review = views._review_or_404(review_id)
    form = views.ReportForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Выберите корректную причину жалобы."))
        return views._redirect_to_review(review)
    views.repo.report(review_id, user=request.user, reason=form.cleaned_data["reason"])
    messages.success(request, _("Жалоба отправлена модератору."))
    return views._redirect_to_review(review)
