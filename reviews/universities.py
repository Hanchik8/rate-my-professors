"""All higher education institutions of Kyrgyzstan from data/universities_kg.json.

The file is the single source for both repositories: the memory backend adds
them on start, seed_kg writes them to the database idempotently (by `code`).
"""
import json
from functools import lru_cache
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "universities_kg.json"
FIELDS = ("name", "name_ky", "name_en", "short_name", "city", "region", "kind", "website")


@lru_cache(maxsize=1)
def load_universities():
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    out = []
    for item in raw["universities"]:
        out.append({
            "code": item["code"], "name": item["name"], "name_ky": item.get("name_ky", ""),
            "name_en": item.get("name_en", ""), "short_name": item.get("short_name", ""),
            "city": item["city"], "region": item["region"], "kind": item.get("type", ""),
            "website": item.get("website", ""), "aliases": tuple(item.get("aliases", ())),
        })
    return tuple(out)


def add_to_repo(repo):
    """Add every institution to a repository (memory backend). Returns {code: School}."""
    return {u["code"]: repo.add_school(**{k: u[k] for k in FIELDS}, code=u["code"]) for u in load_universities()}


def sync_to_db():
    """Create or update every institution in the database. Safe to run again.

    An existing row is found by code, or (for rows made before codes existed)
    by its current name or an old name listed in `aliases`; its slug is kept so
    old links keep working. Returns (created, updated).
    """
    from django.db import transaction
    from .models import School

    created = updated = 0
    with transaction.atomic():
        for u in load_universities():
            values = {k: u[k] for k in FIELDS}
            school = School.objects.filter(code=u["code"]).first()
            if school is None:
                names = [u["name"], *u["aliases"]]
                school = next((s for s in School.objects.filter(code__isnull=True)
                               if s.name.lower() in {n.lower() for n in names}), None)
            if school is None:
                slug = u["code"]
                while School.objects.filter(slug=slug).exists():
                    slug += "-kg"
                School.objects.create(code=u["code"], slug=slug, **values)
                created += 1
                continue
            changed = school.code != u["code"] or any(getattr(school, k) != v for k, v in values.items())
            if changed:
                school.code = u["code"]
                for k, v in values.items():
                    setattr(school, k, v)
                school.save()
                updated += 1
    return created, updated
