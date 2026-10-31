"""Import real professors collected from university websites.

    python manage.py import_professors data/professors            # add / update
    python manage.py import_professors data/professors --dry-run  # report only

Each <code>.json file holds {"code": ..., "professors": [{last_name, first_name,
department, title, source_url, initials_only?}]}. Records are matched to schools
by code, cleaned, de-duplicated case-insensitively per school, and created as
approved, non-demo professors. Re-running is safe: existing names are skipped.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from reviews.models import Professor, School

TITLES = {"профессор", "доцент", "старший преподаватель", "преподаватель"}
_NAME_RE = re.compile(r"^[^\W\d_]+(?:[ '’.-]+[^\W\d_]+)*\.?$")
_DEGREE_RE = re.compile(r"(?<!\w)(?:[дк]\.\s?[а-я]{1,4}\.(?:\s?-\s?[а-я]{1,4}\.)?\s?н\.?|ph\.\s?d\.?|phd|проф\.|доц\.)", re.I)


def _clean(value: str, limit: int) -> str:
    value = " ".join(str(value or "").replace("\u00a0", " ").split())
    return value[:limit].strip()


def clean_record(rec: dict) -> dict | None:
    """Return a normalized record, or None when it can't be a real name."""
    # anything after a comma or bracket is a degree / note, not part of the name
    last = re.split(r"[,(]", str(rec.get("last_name", "")))[0]
    first = re.split(r"[,(]", str(rec.get("first_name", "")))[0]
    last = _clean(_DEGREE_RE.sub("", last), 40).strip(" ,.")
    first = _clean(_DEGREE_RE.sub("", first), 40).strip(" ,")
    if not last or not first or not _NAME_RE.match(last) or not _NAME_RE.match(first):
        return None
    dept = _clean(rec.get("department", ""), 80)
    dept = re.sub(r"^(кафедра|department of)\s+", "", dept, flags=re.I).strip(" «»\"")
    dept = (dept[:1].upper() + dept[1:]) if dept else "Общая"
    title = _clean(rec.get("title", ""), 40).lower()
    if title not in TITLES:
        title = "преподаватель"
    return {"last_name": last, "first_name": first, "department": dept, "title": title}


def _key(first: str, last: str) -> str:
    return " ".join(f"{first} {last}".lower().replace("ё", "е").split())


class Command(BaseCommand):
    help = "Импорт реальных преподавателей из JSON-файлов по вузам."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Папка с <code>.json или один файл")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--skip-initials", action="store_true",
                            help="Не импортировать записи, где известны только инициалы")

    def handle(self, path, dry_run=False, skip_initials=False, **opts):
        p = Path(path)
        files = sorted(p.glob("*.json")) if p.is_dir() else [p]
        if not files:
            raise CommandError(f"Нет JSON-файлов в {path}")
        total_new = total_bad = total_dup = 0
        for f in files:
            data = json.loads(f.read_text(encoding="utf-8"))
            code = data.get("code") or f.stem
            school = School.objects.filter(code=code).first()
            if school is None:
                self.stderr.write(f"{f.name}: вуз с code={code} не найден, пропуск")
                continue
            existing = {_key(a, b) for a, b in Professor.objects.filter(school=school)
                        .values_list("first_name", "last_name")}
            new, bad, dup = [], 0, 0
            for rec in data.get("professors", []):
                if skip_initials and rec.get("initials_only"):
                    continue
                clean = clean_record(rec)
                if clean is None:
                    bad += 1
                    continue
                k = _key(clean["first_name"], clean["last_name"])
                if k in existing:
                    dup += 1
                    continue
                existing.add(k)
                new.append(clean)
            if not dry_run and new:
                with transaction.atomic():
                    for c in new:
                        Professor.objects.create(school=school, slug=self._slug(c), status="approved",
                                                 is_demo=False, **c)
            self.stdout.write(f"{code}: новых {len(new)}, отброшено {bad}, дублей {dup}")
            total_new += len(new); total_bad += bad; total_dup += dup
        verb = "Было бы добавлено" if dry_run else "Добавлено"
        self.stdout.write(f"{verb} {total_new}, отброшено {total_bad}, дублей {total_dup}.")

    @staticmethod
    def _slug(c: dict) -> str:
        base = slugify(f"{c['first_name']} {c['last_name']}", allow_unicode=True)[:180] or "prof"
        slug, n = base, 2
        while Professor.objects.filter(slug=slug).exists():
            slug, n = f"{base}-{n}", n + 1
        return slug
