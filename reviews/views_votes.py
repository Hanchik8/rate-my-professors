"""Review voting and reporting views."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from .throttle import rate_limit


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
    else:
        messages.success(request, _("Ваш голос учтён. Спасибо!"))
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
