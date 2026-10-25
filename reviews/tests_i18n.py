"""Completeness checks for the ky/ru translation catalogs.

Forms, view messages and validators must all have entries in
``locale/<lang>/LC_MESSAGES/django.po`` so the UI never silently falls back to
another language.  These tests parse the catalogs directly (no gettext binary
required) and also resolve a few strings through Django's translation layer.
"""
import ast
import re
from pathlib import Path

from django.test import TestCase
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


class CatalogCompletenessTests(TestCase):
    """Every form/message/validator string is present in ky and ru catalogs."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.catalogs = {
            lang: parse_po(LOCALE_DIR / lang / "LC_MESSAGES" / "django.po")
            for lang in ("ky", "ru", "en")
        }

    def _required_strings(self):
        return python_translatable_strings() | template_translatable_strings()

    def test_python_source_strings_present_with_translation(self):
        for lang in ("ky", "ru"):
            catalog = self.catalogs[lang]
            for msgid in sorted(python_translatable_strings()):
                with self.subTest(lang=lang, msgid=msgid):
                    self.assertIn(msgid, catalog)
                    self.assertTrue(catalog[msgid], f"empty translation for {msgid!r}")

    def test_template_strings_present_with_translation(self):
        for lang in ("ky", "ru"):
            catalog = self.catalogs[lang]
            for msgid in sorted(template_translatable_strings()):
                with self.subTest(lang=lang, msgid=msgid):
                    self.assertIn(msgid, catalog)
                    self.assertTrue(catalog[msgid], f"empty translation for {msgid!r}")

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
