"""User profile and review ownership views."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_http_methods

from .throttle import rate_limit


@login_required
def profile(request):
    from . import views
    return render(request, "reviews/profile.html", {
        "reviews": views.repo.reviews_for_user(request.user),
    })


@require_http_methods(["GET", "POST"])
@login_required
@rate_limit("review")
def review_edit(request, review_id):
    from . import views
    review = views._owned_review_or_404(review_id, request.user)
    prof = views._professor_for_review(review)
    initial = None if request.method == "POST" else views._review_initial(review)
    form = views._form_for_request(request, views.ReviewForm, initial=initial)
    if views._is_valid_post(request, form):
        views.repo.update_review(review_id, form.cleaned_data)
        messages.success(request, _("Отзыв отправлен на модерацию."))
        return redirect("profile")
    return render(request, "reviews/review_form.html", views._review_form_context(prof, form, editing=True))


@require_http_methods(["GET", "POST"])
@login_required
@rate_limit("review")
def review_delete(request, review_id):
    from . import views
    review = views._owned_review_or_404(review_id, request.user)
    if request.method == "POST":
        views.repo.delete_review(review_id)
        messages.success(request, _("Отзыв удалён."))
        return redirect("profile")
    return render(request, "reviews/review_confirm_delete.html", {"review": review})
