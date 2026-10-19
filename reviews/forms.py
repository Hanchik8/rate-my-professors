import re
from django import forms
from django.utils.html import strip_tags
from django.utils.translation import gettext_lazy as _

from .repository import GRADES, TAGS

SCORES = [(5, "5"), (4, "4"), (3, "3"), (2, "2"), (1, "1")]

_URL_RE = re.compile(r"https?://|www\.")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(\+?\d[\d\s\-()]{7,}\d)")


class ReviewForm(forms.Form):
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
        choices=SCORES, coerce=int, widget=forms.RadioSelect,
        label=_("Общее качество (5 — лучше всего)"),
    )
    difficulty = forms.TypedChoiceField(
        choices=SCORES, coerce=int, widget=forms.RadioSelect,
        label=_("Сложность (5 — очень сложно)"),
    )
    would_take_again = forms.ChoiceField(
        choices=[("yes", _("Да")), ("no", _("Нет"))],
        widget=forms.RadioSelect,
        label=_("Пошли бы снова к этому преподавателю?"),
    )
    grade = forms.ChoiceField(
        choices=[("", _("Предпочитаю не указывать"))] + [(str(g), str(g)) for g in GRADES],
        required=False, label=_("Полученная оценка"),
    )
    tags = forms.MultipleChoiceField(
        choices=[(str(t), str(t)) for t in TAGS],
        required=False, widget=forms.CheckboxSelectMultiple,
        label=_("Теги"), help_text=_("Выберите до 3"),
    )
    comment = forms.CharField(
        min_length=20, max_length=1000,
        widget=forms.Textarea(attrs={"rows": 6}),
        label=_("Ваш отзыв"),
        help_text=_("Не менее 20 символов. Пишите только об учёбе, без оскорблений и личных данных."),
    )

    def clean_course(self):
        return self.cleaned_data["course"].strip()

    def clean_comment(self):
        raw = self.cleaned_data["comment"]
        text = strip_tags(raw).strip()
        if _URL_RE.search(text):
            raise forms.ValidationError(_("Ссылки запрещены."))
        if _EMAIL_RE.search(text):
            raise forms.ValidationError(_("Email в отзыве запрещён."))
        if _PHONE_RE.search(text):
            # avoid false positives but block typical phone patterns
            digits = re.sub(r"\D", "", text)
            if len(digits) >= 9 and _PHONE_RE.search(text):
                raise forms.ValidationError(_("Номера телефонов запрещены."))
        return text

    def clean_tags(self):
        tags = self.cleaned_data["tags"]
        if len(tags) > 3:
            raise forms.ValidationError(_("Выберите не более 3 тегов."))
        return tags

    def clean_would_take_again(self):
        return self.cleaned_data["would_take_again"] == "yes"


class ProfessorForm(forms.Form):
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
        super().__init__(*args, **kwargs)
        if schools is not None:
            self.fields["school"].choices = [(str(s.id), s.short_name or s.name) for s in schools]
