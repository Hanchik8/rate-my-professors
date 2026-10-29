"""Static template security checks.

Greps the ``reviews/templates`` tree to guarantee that every POST form
carries ``{% csrf_token %}`` and that the ``|safe`` filter is never
applied to user-controlled variables.
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

APP_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = APP_DIR / "templates"
FORM_TAG = re.compile(r"<form\b[^>]*>", re.IGNORECASE)
FORM_METHOD = re.compile(r"method\s*=\s*[\"']?\s*(\w+)", re.IGNORECASE)
VARIABLE_EXPRESSION = re.compile(r"\{\{([^{}]*)\}\}")
SAFE_FILTER = re.compile(r"\|\s*safe\b")

# ``person_jsonld`` is serialized with ``json.dumps`` and hardened by
# escaping ``&``, ``<`` and ``>`` in ``reviews.views.professor_detail``
# (verified by ``reviews.tests_jsonld``), so ``|safe`` is safe there.
SAFE_ALLOWED_VARIABLES = {"person_jsonld"}


def _template_paths():
    return sorted(TEMPLATE_DIR.rglob("*.html")) + sorted(
        path for path in TEMPLATE_DIR.rglob("*.txt")
    )


def _app_python_paths():
    paths = [
        path for path in APP_DIR.glob("*.py")
        if not path.name.startswith("test")
    ]
    templatetags = APP_DIR / "templatetags"
    if templatetags.is_dir():
        paths.extend(templatetags.glob("*.py"))
    return sorted(paths)


def _post_form_issues(content):
    issues = []
    for match in FORM_TAG.finditer(content):
        method = FORM_METHOD.search(match.group(0))
        if not method or method.group(1).lower() != "post":
            continue
        end = content.find("</form>", match.start())
        if end == -1:
            end = len(content)
        body = content[match.start():end]
        if "{% csrf_token %}" not in body:
            issues.append(match.start())
    return issues


def _safe_filter_variables(content):
    variables = []
    for match in VARIABLE_EXPRESSION.finditer(content):
        expression = match.group(1)
        if SAFE_FILTER.search(expression):
            variables.append(expression.split("|", 1)[0].strip())
    return variables


class PostFormCsrfTests(SimpleTestCase):
    def test_every_post_form_contains_csrf_token(self):
        failures = []
        for path in _template_paths():
            content = path.read_text(encoding="utf-8")
            for offset in _post_form_issues(content):
                failures.append(
                    f"{path.relative_to(TEMPLATE_DIR)}: POST form at offset {offset}"
                )
        self.assertEqual(
            failures, [], "POST forms without {% csrf_token %}: " + ", ".join(failures)
        )


class SafeFilterTests(SimpleTestCase):
    def test_safe_filter_not_used_on_user_variables(self):
        violations = []
        for path in _template_paths():
            content = path.read_text(encoding="utf-8")
            for variable in _safe_filter_variables(content):
                if variable not in SAFE_ALLOWED_VARIABLES:
                    failures = f"{path.relative_to(TEMPLATE_DIR)}: {variable}"
                    violations.append(failures)
        self.assertEqual(
            violations, [], "|safe used on non-allowlisted variables: " + ", ".join(violations)
        )

    def test_allowed_safe_variable_is_escaped_server_side(self):
        views_source = (APP_DIR / "views.py").read_text(encoding="utf-8")
        self.assertIn('"person_jsonld"', views_source)
        for character in ('&', '<', '>'):
            self.assertIn(
                f'"{character}"', views_source,
                f"person_jsonld must escape {character!r} before |safe",
            )

    def test_mark_safe_not_used_in_app_code(self):
        offenders = [
            path.name for path in _app_python_paths()
            if "mark_safe" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])
