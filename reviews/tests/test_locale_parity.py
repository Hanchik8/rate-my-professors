"""Catalog parity for ru/ky/en: same msgids, no gaps, matching placeholders."""

import re
from pathlib import Path

import polib
from django.test import SimpleTestCase

LOCALE_DIR = Path(__file__).resolve().parent.parent.parent / "locale"
LANGS = ("ru", "ky", "en")
PLACEHOLDER_RE = re.compile(r"%(?:\((\w+)\))?[sdif]")


def _catalog(lang):
    return polib.pofile(str(LOCALE_DIR / lang / "LC_MESSAGES" / "django.po"))


class LocaleParityTests(SimpleTestCase):
    """A language switch must never fall back for a string we have in another catalog."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.catalogs = {lang: _catalog(lang) for lang in LANGS}
        cls.msgids = {lang: {e.msgid for e in po if not e.obsolete} for lang, po in cls.catalogs.items()}

    def test_msgid_sets_are_identical(self):
        reference = self.msgids["ru"]
        for lang in ("ky", "en"):
            missing = sorted(reference - self.msgids[lang])
            extra = sorted(self.msgids[lang] - reference)
            self.assertEqual(missing, [], f"{lang} is missing msgids that exist in ru: {missing}")
            self.assertEqual(extra, [], f"{lang} has msgids absent from ru: {extra}")

    def test_no_empty_translations(self):
        for lang, po in self.catalogs.items():
            empty = sorted(e.msgid for e in po if not e.msgstr and not e.msgstr_plural)
            self.assertEqual(empty, [], f"{lang} has untranslated entries: {empty}")

    def test_no_fuzzy_entries(self):
        for lang, po in self.catalogs.items():
            fuzzy = sorted(e.msgid for e in po if "fuzzy" in e.flags)
            self.assertEqual(fuzzy, [], f"{lang} has fuzzy entries: {fuzzy}")

    def test_placeholders_match_between_msgid_and_msgstr(self):
        for lang, po in self.catalogs.items():
            for entry in po:
                expected = sorted(PLACEHOLDER_RE.findall(entry.msgid))
                actual = sorted(PLACEHOLDER_RE.findall(entry.msgstr))
                self.assertEqual(
                    actual,
                    expected,
                    f"{lang}: placeholders differ for {entry.msgid!r} ({expected} -> {actual})",
                )