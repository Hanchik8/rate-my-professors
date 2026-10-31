"""Forms for creating reviews and professors.

All user-supplied free text is passed through ``sanitize.clean_text`` so the
form layer and the repositories agree on what "clean" input looks like.
"""
import re

from django import forms
from django.utils.translation import gettext_lazy as _

from .constants import MAX_COMMENT_LENGTH, MIN_COMMENT_LENGTH
from .models import Report
from .repository import GRADES, TAGS
from .sanitize import clean_text

# Contacts and links are banned by the rules: links, bare domains, emails, phones.
_LINK_RE = re.compile(r"(https?://|www\.|\b[\w.-]+\.(?:kg|ru|com|net|org|me|io|su|info|biz)\b|@\w)", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?:\+?\d[\s()-]*){9,}")
_NAME_RE = re.compile(r"^[^\W\d_]+(?:[ '’.-][^\W\d_]+)*\.?$")
_CONTACTS_MESSAGE = _("Уберите ссылки, email и номера телефонов — это запрещено правилами.")
_NAME_MESSAGE = _("Только буквы, пробел, дефис или апостроф.")

SCORES = [(5, "5"), (4, "4"), (3, "3"), (2, "2"), (1, "1")]

_TOO_SHORT_MESSAGE = _("Отзыв должен содержать не менее %(n)d символов.")
_TOO_LONG_MESSAGE = _("Отзыв должен содержать не более %(n)d символов.")


def _reason_max_length():
    """Return the model-enforced maximum length of a report reason."""
    return Report._meta.get_field("reason").max_length


def _string_choices(values):
    """Return ``[(str(v), str(v))]`` choices for a list of stored values."""
    return [(str(value), str(value)) for value in values]


class _AutofocusChoiceMixin:
    """Put ``autofocus`` on the first option of a choice group.

    Choice widgets render a wrapper element rather than a single input, so a
    plain ``autofocus`` attribute would be copied to every option.  The form
    template tag flips ``_autofocus_first`` only for the first invalid field.
    """

    def create_option(self, *args, **kwargs):
        option = super().create_option(*args, **kwargs)
        if getattr(self, "_autofocus_first", False):
            option["attrs"]["autofocus"] = True
            self._autofocus_first = False
        return option


class AutofocusRadioSelect(_AutofocusChoiceMixin, forms.RadioSelect):
    """Radio group whose first option can receive keyboard focus."""


class AutofocusCheckboxSelectMultiple(_AutofocusChoiceMixin, forms.CheckboxSelectMultiple):
    """Checkbox group whose first option can receive keyboard focus."""


def apply_form_accessibility(form):
    """Describe invalid fields and focus the first one before rendering.

    Django 6 already adds ``aria-invalid`` for bound fields with errors, but
    field groups (radio/checkbox) do not get their error/help text wired up by
    the shared field template.  Doing this here keeps every form consistent.
    """
    if not form.is_bound:
        return
    errors = form.errors
    first_invalid = True
    for name in form.fields:
        bound_field = form[name]
        widget = bound_field.field.widget
        has_error = name in errors
        described_by = []
        if bound_field.auto_id:
            if bound_field.help_text:
                described_by.append(f"{bound_field.auto_id}_helptext")
            if has_error:
                described_by.append(f"{bound_field.auto_id}_error")
        if described_by:
            widget.attrs["aria-describedby"] = " ".join(described_by)
        if not has_error:
            continue
        if not widget.is_hidden:
            widget.attrs["aria-invalid"] = "true"
        if first_invalid:
            if isinstance(widget, _AutofocusChoiceMixin):
                widget._autofocus_first = True
            else:
                widget.attrs["autofocus"] = True
            first_invalid = False


def _ensure_length(value, minimum, maximum, too_short, too_long):
    """Raise a validation error when ``value`` falls outside the allowed range.

    ``too_short``/``too_long`` are translation templates expecting an ``n``
    placeholder for the bound that was violated.
    """
    if len(value) < minimum:
        raise forms.ValidationError(too_short % {"n": minimum})
    if len(value) > maximum:
        raise forms.ValidationError(too_long % {"n": maximum})


class ReportForm(forms.Form):
    """Validated reason supplied with a review report."""

    reason = forms.ChoiceField(
        choices=Report.REASON_CHOICES,
        required=False,
        initial=Report.REASON_OTHER,
        label=_("Причина жалобы"),
        widget=forms.Select(attrs={"aria-label": _("Причина жалобы")}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reason"].widget.attrs["maxlength"] = _reason_max_length()

    def clean(self):
        cleaned_data = super().clean()
        reason = self.data.get(self.add_prefix("reason"), "") if self.is_bound else ""
        maximum = _reason_max_length()
        if len(reason) > maximum:
            self.add_error("reason", forms.ValidationError(
                _TOO_LONG_MESSAGE,
                code="max_length",
                params={"n": maximum},
            ))
        return cleaned_data

    def clean_reason(self):
        """Keep one-click reports compatible by defaulting to ``other``."""
        return self.cleaned_data.get("reason") or Report.REASON_OTHER


class ReviewForm(forms.Form):
    """Student review form with sanitization and length limits."""

    course = forms.CharField(
        max_length=80,
        label=_("Предмет"),
        help_text=_("Например: Алгоритмы, Общая физика, Микроэкономика"),
    )
    term = forms.CharField(
        max_length=20, required=False,
        label=_("Семестр"),
        help_text=_("Например: Осень 2025 или Весна 2025"),
    )
    overall = forms.TypedChoiceField(
        choices=SCORES, coerce=int, widget=AutofocusRadioSelect,
        label=_("Общее качество (5 — лучше всего)"),
    )
    difficulty = forms.TypedChoiceField(
        choices=SCORES, coerce=int, widget=AutofocusRadioSelect,
        label=_("Сложность (5 — очень сложно)"),
    )
    would_take_again = forms.ChoiceField(
        choices=[("yes", _("Да")), ("no", _("Нет"))],
        widget=AutofocusRadioSelect,
        label=_("Пошли бы снова к этому преподавателю?"),
    )
    grade = forms.ChoiceField(
        choices=[("", _("Предпочитаю не указывать"))] + _string_choices(GRADES),
        required=False, label=_("Полученная оценка"),
    )
    tags = forms.MultipleChoiceField(
        choices=_string_choices(TAGS),
        required=False, widget=AutofocusCheckboxSelectMultiple,
        label=_("Теги"), help_text=_("Выберите до 3"),
    )
    comment = forms.CharField(
        min_length=MIN_COMMENT_LENGTH, max_length=MAX_COMMENT_LENGTH,
        widget=forms.Textarea(attrs={"rows": 6}),
        label=_("Ваш отзыв"),
        help_text=_("Не менее 20 символов. Пишите только об учёбе, без оскорблений и личных данных."),
    )

    def clean_course(self):
        """Trim the free-text course name (no case normalization)."""
        return clean_text(self.cleaned_data["course"])

    def clean_term(self):
        """Trim the optional term string."""
        return clean_text(self.cleaned_data.get("term", ""))

    def clean_comment(self):
        """Sanitize the body and enforce the min/max length on the clean text.

        Control characters are removed first: "junk" characters must not help
        a comment slip past the minimum length requirement.
        """
        comment = clean_text(self.cleaned_data["comment"])
        _ensure_length(
            comment, MIN_COMMENT_LENGTH, MAX_COMMENT_LENGTH,
            too_short=_TOO_SHORT_MESSAGE,
            too_long=_TOO_LONG_MESSAGE,
        )
        if _LINK_RE.search(comment) or _PHONE_RE.search(comment):
            raise forms.ValidationError(_CONTACTS_MESSAGE)
        return comment

    def clean_tags(self):
        """Sanitize tags and cap them at three."""
        tags = [clean_text(t) for t in self.cleaned_data["tags"]]
        if len(tags) > 3:
            raise forms.ValidationError(_("Выберите не более 3 тегов."))
        return tags

    def clean_would_take_again(self):
        """Convert the radio choice into a boolean."""
        return self.cleaned_data["would_take_again"] == "yes"


class ProfessorForm(forms.Form):
    """Submission form for a new professor (goes through moderation)."""

    school = forms.ChoiceField(label=_("Вуз"))
    first_name = forms.CharField(max_length=40, label=_("Имя"))
    last_name = forms.CharField(max_length=40, label=_("Фамилия"))
    department = forms.CharField(max_length=80, label=_("Кафедра"))
    title = forms.ChoiceField(
        label=_("Должность"),
        choices=[
            ("профессор", _("профессор")),
            ("доцент", _("доцент")),
            ("старший преподаватель", _("старший преподаватель")),
            ("преподаватель", _("преподаватель")),
        ],
    )

    def __init__(self, *args, schools=None, **kwargs):
        """Populate the school choices from the provided ``schools`` list."""
        super().__init__(*args, **kwargs)
        if schools is not None:
            self.fields["school"].choices = [(str(s.id), s.name) for s in schools]

    def clean_first_name(self):
        """Sanitize the first name and allow letters only."""
        return self._clean_name("first_name")

    def clean_last_name(self):
        """Sanitize the last name and allow letters only."""
        return self._clean_name("last_name")

    def _clean_name(self, field):
        value = self._clean_required_text(field, 40)
        if not _NAME_RE.match(" ".join(value.split())):
            raise forms.ValidationError(_NAME_MESSAGE)
        return value

    def clean_department(self):
        """Sanitize the department name."""
        return self._clean_required_text("department", 80)

    def _clean_required_text(self, field, maximum):
        value = clean_text(self.cleaned_data[field])
        if not value:
            raise forms.ValidationError(self.fields[field].error_messages["required"])
        if len(value) > maximum:
            raise forms.ValidationError(
                self.fields[field].error_messages["max_length"],
                code="max_length", params={"limit_value": maximum, "show_value": len(value)},
            )
        return value
