"""University logo avatar for professor cards and pages.

Logos live in reviews/static/reviews/logos/<school.code>.png (collected from
each university's own site). A school without a logo file gets a monogram
from its short name, so a card never shows an empty dash.
"""

from functools import lru_cache
from pathlib import Path

from django import template
from django.templatetags.static import static
from django.utils.html import format_html

register = template.Library()

LOGO_DIR = Path(__file__).resolve().parent.parent / "static" / "reviews" / "logos"


@lru_cache(maxsize=None)
def _logo_codes():
    if not LOGO_DIR.is_dir():
        return frozenset()
    return frozenset(p.stem for p in LOGO_DIR.glob("*.png"))


def _get(obj, name, default=""):
    if isinstance(obj, dict):
        return obj.get(name, default) or default
    return getattr(obj, name, default) or default


def monogram(school):
    import re

    short = re.sub(r"\(.*?\)|[«»\"'.]", " ", _get(school, "short_name")).split()
    if short:
        joined = "".join(short)
        if len(joined) <= 6:
            return joined.upper() if joined.isascii() else joined
        caps_words = [w for w in short if len(w) > 1 and w.isupper()]
        if caps_words and len("".join(caps_words)) <= 6:
            return "".join(caps_words)
        caps = "".join(ch for ch in joined if ch.isupper())
        if len(caps) >= 2:
            return caps[:6]
        return joined[:2]
    name = _get(school, "name")
    skip = {"им.", "и", "им", "имени", "of", "the", "and"}
    words = [w for w in name.replace("-", " ").split() if w.lower() not in skip and w[:1].isalpha()]
    return "".join(w[0] for w in words[:3]).upper() or "?"


@register.simple_tag
def school_logo(school, size=""):
    """Render the school's logo (or monogram) as a decorative avatar."""
    code = _get(school, "code")
    cls = "school-logo" + (f" {size}" if size else "")
    if code and code in _logo_codes():
        return format_html(
            '<span class="{}"><img src="{}" alt="" width="64" height="64" loading="lazy" decoding="async"></span>',
            cls, static(f"reviews/logos/{code}.png"),
        )
    text = monogram(school)
    return format_html('<span class="{} monogram" data-len="{}">{}</span>', cls, len(text), text)
