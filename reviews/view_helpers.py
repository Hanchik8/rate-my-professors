"""Shared helpers used by the HTTP views in ``reviews.views``.

The functions here translate request parameters into repository calls so
that views stay thin.  Helpers that need the repository take it as an
explicit argument: views pass their module-level ``repo`` so tests can
swap it out via monkeypatching.
"""
from django.core.paginator import Paginator
from django.http import Http404
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
