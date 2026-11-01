from django.template import Context, Template
from django.test import SimpleTestCase

from reviews.repository import School
from reviews.templatetags.school_logo import _logo_codes, monogram


def _school(code="", short=""):
    return School(id="1", name="Кыргызский национальный университет", slug="x", city="Бишкек", code=code, short_name=short)


class SchoolLogoTagTests(SimpleTestCase):
    def render(self, school, size=""):
        return Template('{% load school_logo %}{% school_logo s size %}').render(Context({"s": school, "size": size}))

    def test_known_school_renders_local_logo(self):
        self.assertIn("knu", _logo_codes())
        html = self.render(_school("knu", "КНУ"))
        self.assertIn('src="/static/reviews/logos/knu.png"', html)
        self.assertIn('alt=""', html)

    def test_school_without_logo_gets_monogram_not_dash(self):
        html = self.render(_school("no-such-code", "КГЮУ (КГЮА)"))
        self.assertIn("monogram", html)
        self.assertIn(">КГЮУ<", html)

    def test_monogram_rules(self):
        self.assertEqual(monogram(_school(short="Академия ОБСЕ")), "ОБСЕ")
        self.assertEqual(monogram(_school(short="")), "КНУ")
        self.assertLessEqual(len(monogram(_school(short="КГУГГиОПР"))), 6)

    def test_size_class(self):
        self.assertIn('class="school-logo big', self.render(_school("knu"), "big"))
