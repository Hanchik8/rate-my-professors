import re

from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.utils.translation import gettext_lazy as _

from .repository import GRADES, TAGS

# links, e-mails and phone numbers are not allowed in public texts (rules: no personal data, no spam)
_LINK_RE = re.compile(r"(https?://|www\.|\b[\w.-]+\.(?:kg|ru|com|net|org|me|io)\b|@\w)", re.IGNORECASE)
_PHONE_RE = re.compile(r"(?:\+?\d[\s()-]*){9,}")
_NAME_RE = re.compile(r"^[^\W\d_]+(?:[ '’.-][^\W\d_]+)*\.?$")


def _clean_text(value):
    """Trim, collapse whitespace, drop control characters."""
    value = "".join(ch for ch in value if ch.isprintable() or ch in "\n\t")
    lines = [" ".join(line.split()) for line in value.strip().splitlines()]
    return "\n".join(lines)

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
        min_length=20, max_length=1000,
        widget=forms.Textarea(attrs={"rows": 6}),
        label=_("Ваш отзыв"),
        help_text=_("Не менее 20 символов. Пишите только об учёбе, без оскорблений и личных данных."),
    )

    def clean_course(self):
        # свободный текст, до 80 символов, без upper-case нормализации — только trim
        course = " ".join(self.cleaned_data["course"].split())
        if len(course) < 2:
            raise forms.ValidationError(_("Укажите название предмета."))
        return course

    def clean_term(self):
        return " ".join(self.cleaned_data["term"].split())

    def clean_comment(self):
        comment = _clean_text(self.cleaned_data["comment"])
        if len(comment) < 20:
            raise forms.ValidationError(_("Не менее 20 символов."))
        if _LINK_RE.search(comment) or _PHONE_RE.search(comment):
            raise forms.ValidationError(_("Уберите ссылки, email и номера телефонов — это запрещено правилами."))
        return comment

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
            self.fields["school"].choices = [("", "—")] + [(str(s.id), s.display_name) for s in schools]

    def _clean_name(self, field):
        value = " ".join(self.cleaned_data[field].split())
        if not _NAME_RE.match(value):
            raise forms.ValidationError(_("Только буквы, пробел, дефис или апостроф."))
        return value

    def clean_first_name(self):
        return self._clean_name("first_name")

    def clean_last_name(self):
        return self._clean_name("last_name")

    def clean_department(self):
        value = " ".join(self.cleaned_data["department"].split())
        if _LINK_RE.search(value):
            raise forms.ValidationError(_("Ссылки не допускаются."))
        return value


class EmailAuthenticationForm(AuthenticationForm):
    """Login by email; the email is matched case-insensitively."""
    username = forms.EmailField(label=_("Email"), max_length=150,
                                widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "email"}))

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class EmailSignupForm(forms.Form):
    email = forms.EmailField(label=_("Email"), max_length=150,
                             widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password1 = forms.CharField(label=_("Пароль"), strip=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
                                help_text=_("Не менее 8 символов, не только цифры и не слишком простой."))
    password2 = forms.CharField(label=_("Повторите пароль"), strip=False,
                                widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if User.objects.filter(username__iexact=email).exists() or User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("Пользователь с таким email уже существует."))
        return email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", _("Пароли не совпадают."))
        elif p1:
            email = cleaned.get("email") or ""
            try:
                password_validation.validate_password(p1, User(username=email, email=email))
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return cleaned

    def save(self):
        email = self.cleaned_data["email"]
        try:
            with transaction.atomic():
                return User.objects.create_user(username=email, email=email, password=self.cleaned_data["password1"])
        except IntegrityError:
            # the same email registered in a parallel request
            self.add_error("email", _("Пользователь с таким email уже существует."))
            return None
