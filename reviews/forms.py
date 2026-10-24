from django import forms
from django.utils.translation import gettext_lazy as _

from .repository import GRADES, TAGS
from .sanitize import MAX_COMMENT_LENGTH, MIN_COMMENT_LENGTH, clean_text

SCORES = [(5, "5"), (4, "4"), (3, "3"), (2, "2"), (1, "1")]


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
        min_length=MIN_COMMENT_LENGTH, max_length=MAX_COMMENT_LENGTH,
        widget=forms.Textarea(attrs={"rows": 6}),
        label=_("Ваш отзыв"),
        help_text=_("Не менее 20 символов. Пишите только об учёбе, без оскорблений и личных данных."),
    )

    def clean_course(self):
        # свободный текст, до 80 символов, без upper-case нормализации — только trim
        return clean_text(self.cleaned_data["course"])

    def clean_term(self):
        return clean_text(self.cleaned_data.get("term", ""))

    def clean_comment(self):
        # Контрольные символы удаляются, после чего длина проверяется повторно:
        # «мусорные» символы не должны помогать обойти минимум.
        comment = clean_text(self.cleaned_data["comment"])
        if len(comment) < MIN_COMMENT_LENGTH:
            raise forms.ValidationError(
                _("Отзыв должен содержать не менее %(n)d символов.") % {"n": MIN_COMMENT_LENGTH}
            )
        if len(comment) > MAX_COMMENT_LENGTH:
            raise forms.ValidationError(
                _("Отзыв должен содержать не более %(n)d символов.") % {"n": MAX_COMMENT_LENGTH}
            )
        return comment

    def clean_tags(self):
        tags = [clean_text(t) for t in self.cleaned_data["tags"]]
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
            self.fields["school"].choices = [(str(s.id), s.name) for s in schools]

    def clean_first_name(self):
        return clean_text(self.cleaned_data["first_name"])

    def clean_last_name(self):
        return clean_text(self.cleaned_data["last_name"])

    def clean_department(self):
        return clean_text(self.cleaned_data["department"])
