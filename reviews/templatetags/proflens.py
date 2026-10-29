from django import template
from django.utils.translation import gettext

register = template.Library()


@register.filter
def translate_each(values):
    """Translate stored Russian tag names into the current language: {{ r.tags|translate_each|join:", " }}"""
    return [gettext(str(v)) for v in values]


@register.simple_tag(takes_context=True)
def page_url(context, page):
    """Current URL with ?page=N, keeping other GET params (q, school, sort...)."""
    params = context["request"].GET.copy()
    params["page"] = page
    return "?" + params.urlencode()
