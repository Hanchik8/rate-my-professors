"""Shared helpers used by the HTTP views in ``reviews.views``.

The functions here translate request parameters into repository calls so
that views stay thin.  Helpers that need the repository take it as an
explicit argument: views pass their module-level ``repo`` so tests can
swap it out via monkeypatching.
"""
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _

from .constants import PAGE_SIZE


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


def _paginate_request(request, items):
    """Paginate ``items`` using the page number from the request query string."""
    return _paginate(items, request.GET.get("page"))


def _is_author(obj, user):
    """Return whether ``obj`` belongs to ``user`` (ids compare as strings)."""
    return obj.author_id is not None and str(obj.author_id) == str(user.id)


def _object_or_404(obj, message):
    """Return ``obj`` or raise ``Http404`` with the supplied message."""
    if obj is None:
        raise Http404(message)
    return obj


def _review_or_404(repo, review_id):
    """Fetch a review via ``repo`` or raise ``Http404`` when it does not exist."""
    return _object_or_404(repo.review(review_id), _("Review not found"))


def _owned_review_or_404(repo, review_id, user):
    """Fetch a review owned by ``user`` via ``repo`` or raise ``Http404``."""
    review = _review_or_404(repo, review_id)
    if not _is_author(review, user):
        raise Http404(_("Review not found"))
    return review


def _professor_for_review(repo, review):
    """Return the professor a review belongs to, via ``repo``."""
    return repo.professor_by_id(review.professor_id)


def _redirect_to_review(repo, review):
    """Redirect back to the review's anchor on its professor page."""
    prof = _professor_for_review(repo, review)
    if prof:
        return redirect(reverse("professor", args=[prof.slug]) + f"#review-{review.id}")
    return redirect("home")
