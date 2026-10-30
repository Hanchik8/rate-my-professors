"""Display translations for common Russian department names."""
from django import template
from django.utils.translation import gettext

register = template.Library()


@register.simple_tag
def translate_department(value):
    """Translate known department labels, retaining unknown values verbatim."""
    return gettext(value)
