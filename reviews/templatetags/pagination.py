"""Pagination helpers for templates."""
from django import template
from django.http import QueryDict

register = template.Library()


@register.simple_tag
def pagination_pages(page_obj, radius=1):
    """Return page numbers around ``page_obj`` with first/last pages.

    Gaps between pages are represented by ``None`` so templates can render
    an ellipsis without embedding layout logic in Python.
    """
    current = page_obj.number
    total = page_obj.paginator.num_pages
    try:
        radius = max(0, int(radius))
    except (TypeError, ValueError):
        radius = 1
    numbers = set(range(max(1, current - radius), min(total, current + radius) + 1))
    numbers.update({1, total})
    pages = []
    previous = None
    for number in sorted(numbers):
        if previous is not None and number - previous > 1:
            pages.append(None)
        pages.append(number)
        previous = number
    return pages


@register.simple_tag(takes_context=True)
def page_url(context, number):
    """Build a query string for ``number``, preserving all other GET params."""
    request = context.get("request")
    params = request.GET.copy() if request is not None else QueryDict("", mutable=True)
    params["page"] = number
    return f"?{params.urlencode()}"
