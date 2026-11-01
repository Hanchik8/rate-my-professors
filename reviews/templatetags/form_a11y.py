"""Template helpers for accessible form rendering."""
from django import template

from ..forms import apply_form_accessibility

register = template.Library()


@register.simple_tag
def prepare_form(form):
    """Wire error/help attributes immediately before a form is rendered."""
    apply_form_accessibility(form)
    return ""
