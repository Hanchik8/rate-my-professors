"""Completeness checks for the ky/ru/en translation catalogs.

Forms, view messages, validators and every template string (including
``blocktranslate``) must have entries in ``locale/<lang>/LC_MESSAGES/django.po``
so the UI never silently falls back to another language.  These tests parse the
catalogs directly (no gettext binary required) and also resolve strings through
Django's translation layer, including values loaded from the repository (titles,
tags and grades).
"""
import ast
import re
from pathlib import Path
from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase
from django.utils import translation

APP_DIR = Path(__file__).parent
LOCALE_DIR = APP_DIR.parent / "locale"
TEMPLATES_DIR = APP_DIR / "templates"

GETTEXT_NAMES = {"_", "gettext", "gettext_lazy", "ngettext", "ngettext_lazy"}


def parse_po(path):
    """Return ``{msgid: msgstr}`` for a gettext ``.po`` file.

    Handles multi-line strings and (ignores) plural forms.  The header entry
    (empty msgid) is kept but not used by callers.
    """
    entries = {}
    msgid = None
    msgstr = None
    mode = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("msgid "):
            if msgid is not None:
                entries[msgid] = msgstr
            msgid = ast.literal_eval(line[len("msgid "):])
            msgstr = None
            mode = "id"
        elif line.startswith("msgstr "):
            msgstr = ast.literal_eval(line[len("msgstr "):])
            mode = "str"
        elif line.startswith('"'):
            chunk = ast.literal_eval(line)
            if mode == "id":
                msgid += chunk
            elif mode == "str":
                msgstr = (msgstr or "") + chunk
        elif line.startswith("msgid_plural") or line.startswith("msgstr["):
            mode = "plural"
    if msgid is not None:
        entries[msgid] = msgstr
    return entries


def python_translatable_strings():
    """All literal strings passed to gettext-style calls in app modules."""
    found = set()
    for path in APP_DIR.glob("*.py"):
        if path.name.startswith("tests"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name not in GETTEXT_NAMES:
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
    return found


def template_translatable_strings():
    """Simple ``{% translate "..." %}`` strings (blocktranslate excluded)."""
    found = set()
    pattern = re.compile(r"""\{%\s*(?:trans|translate)\s+("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')\s*%\}""")
    for path in TEMPLATES_DIR.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            found.add(ast.literal_eval(match.group(1)))
    return found


def template_blocktranslate_strings():
    """``{% blocktranslate %}`` strings converted to gettext ``%(var)s`` form."""
    found = set()
    pattern = re.compile(
        r"\{%\s*blocktranslate(?:[^%]*)%\}(.*?)\{%\s*endblocktranslate\s*%\}",
        re.DOTALL,
    )
    for path in TEMPLATES_DIR.rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            body = " ".join(match.group(1).split())
            found.add(re.sub(r"\{\{\s*(\w+)\s*\}\}", r"%(\1)s", body))
    return found


def all_translatable_strings():
    """Every gettext string referenced by Python modules and templates."""
    return (
        python_translatable_strings()
        | template_translatable_strings()
        | template_blocktranslate_strings()
    )


class CatalogCompletenessTests(TestCase):
    """Every source string is present and translated in all three catalogs."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.catalogs = {
            lang: parse_po(LOCALE_DIR / lang / "LC_MESSAGES" / "django.po")
            for lang in ("ky", "ru", "en")
        }

    def test_python_source_strings_present_with_translation(self):
        for lang in ("ky", "ru", "en"):
            catalog = self.catalogs[lang]
            for msgid in sorted(python_translatable_strings()):
                with self.subTest(lang=lang, msgid=msgid):
                    self.assertIn(msgid, catalog)
                    self.assertTrue(catalog[msgid], f"empty translation for {msgid!r}")

    def test_template_strings_present_with_translation(self):
        for lang in ("ky", "ru", "en"):
            catalog = self.catalogs[lang]
            for msgid in sorted(template_translatable_strings() | template_blocktranslate_strings()):
                with self.subTest(lang=lang, msgid=msgid):
                    self.assertIn(msgid, catalog)
                    self.assertTrue(catalog[msgid], f"empty translation for {msgid!r}")

    def test_all_catalogs_cover_the_same_msgids(self):
        expected = set(all_translatable_strings())
        for lang in ("ky", "ru", "en"):
            missing = expected - set(self.catalogs[lang])
            with self.subTest(lang=lang):
                self.assertEqual(missing, set(), f"missing from {lang} catalog")

    def test_catalogs_have_no_empty_translations(self):
        for lang in ("ky", "ru", "en"):
            for msgid, msgstr in self.catalogs[lang].items():
                if msgid == "":
                    continue
                with self.subTest(lang=lang, msgid=msgid):
                    self.assertTrue(msgstr, f"untranslated entry in {lang}: {msgid!r}")


class FormAndMessageTranslationTests(TestCase):
    """Specific forms/validators/messages resolve in Kyrgyz and Russian."""

    KY = {
        "Нельзя голосовать за свой отзыв.": "Өз сын-пикириңизге добуш бере албайсыз.",
        "Слишком много запросов. Попробуйте позже.": "Сурамдар өтө көп. Кийинчерээк аракет кылыңыз.",
        "Слишком много попыток входа. Попробуйте позже.": "Кирүү аракеттери өтө көп. Кийинчерээк аракет кылыңыз.",
        "Выберите не более 3 тегов.": "3төн ашык тег тандабаңыз.",
        "Отзыв должен содержать не менее %(n)d символов.": "Сын-пикир кеминде %(n)d белгиден турушу керек.",
        "Отзыв должен содержать не более %(n)d символов.": "Сын-пикир %(n)d белгиден ашпашы керек.",
        "Пароль должен быть не менее 8 символов.": "Сырсөз кеминде 8 белгиден турушу керек.",
        "Пароли не совпадают.": "Сырсөздөр дал келбейт.",
        "Вы уже голосовали за этот отзыв.": "Бул сын-пикирге добуш бергенсиз.",
    }

    def test_ky_translations_match(self):
        with translation.override("ky"):
            for msgid, expected in self.KY.items():
                with self.subTest(msgid=msgid):
                    self.assertEqual(translation.gettext(msgid), expected)

    def test_ky_plural_placeholder_is_preserved(self):
        with translation.override("ky"):
            rendered = translation.gettext("Отзыв должен содержать не менее %(n)d символов.") % {"n": 20}
            self.assertIn("20", rendered)

    def test_en_new_messages_translated(self):
        expected = {
            "Нельзя голосовать за свой отзыв.": "You cannot vote on your own review.",
            "Слишком много запросов. Попробуйте позже.": "Too many requests. Please try again later.",
            "Слишком много попыток входа. Попробуйте позже.": "Too many login attempts. Please try again later.",
        }
        with translation.override("en"):
            for msgid, value in expected.items():
                with self.subTest(msgid=msgid):
                    self.assertEqual(translation.gettext(msgid), value)


class RenderedTemplateTranslationTests(TestCase):
    """Repository values shown in templates are translated, not left in Russian."""

    def _render(self, lang):
        prof = SimpleNamespace(
            full_name="Test Professor",
            title="старший преподаватель",
            department="Computer Science",
            slug="test-professor",
        )
        school = SimpleNamespace(name="Test School", slug="test-school")
        stats = {
            "count": 1,
            "overall": 5,
            "difficulty": 3,
            "wta_pct": 100,
            "tone": "good",
            "distribution": [{"score": 5, "count": 1, "pct": 100}],
            "top_tags": ["Интересные лекции", "Вдохновляет"],
        }
        review = SimpleNamespace(
            id="review-1",
            overall=5,
            course="Algorithms",
            term="",
            difficulty=3,
            would_take_again=True,
            grade="Ещё не знаю",
            comment="Great course.",
            tags=["Понятные критерии"],
            helpful=1,
            not_helpful=0,
        )
        request = RequestFactory().get("/professors/test-professor/")
        with translation.override(lang):
            return render_to_string(
                "reviews/professor.html",
                {
                    "prof": prof,
                    "school": school,
                    "stats": stats,
                    "reviews": [review],
                    "sort": "newest",
                },
                request=request,
            )

    def test_professor_page_translates_titles_tags_and_grades(self):
        expected = {
            "en": [
                "senior lecturer",
                "Interesting lectures",
                "Inspiring",
                "Clear criteria",
                "Not sure yet",
                "Grade:",
            ],
            "ky": [
                "ага окутуучу",
                "Кызыктуу лекциялар",
                "Шыктандырат",
                "Түшүнүктүү критерийлер",
                "Азырынча билбейм",
                "Баасы:",
            ],
            "ru": [
                "старший преподаватель",
                "Интересные лекции",
                "Вдохновляет",
                "Понятные критерии",
                "Ещё не знаю",
                "Оценка:",
            ],
        }
        forbidden = {
            "en": ["старший преподаватель", "Интересные лекции", "Понятные критерии", "Ещё не знаю"],
            "ky": ["старший преподаватель", "Интересные лекции", "Понятные критерии", "Ещё не знаю"],
        }
        for lang, values in expected.items():
            with self.subTest(lang=lang):
                html = self._render(lang)
                for value in values:
                    self.assertIn(value, html)
                for value in forbidden.get(lang, []):
                    self.assertNotIn(value, html)
