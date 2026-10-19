import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils.text import slugify

from reviews.models import School


class Command(BaseCommand):
    help = "Идемпотентно загружает вузы из data/kg_universities.json (update_or_create по slug, сопоставление по short_name)"

    def add_arguments(self, parser):
        parser.add_argument("--file", default="data/kg_universities.json", help="Путь к JSON файлу")

    def handle(self, *args, **opts):
        path = Path(opts["file"])
        if not path.is_absolute():
            from django.conf import settings
            path = Path(settings.BASE_DIR) / path
        if not path.exists():
            self.stderr.write(self.style.ERROR(f"Файл не найден: {path}"))
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        created = 0
        updated = 0
        for item in data:
            name = item["name"].strip()
            short_name = item.get("short_name", "").strip()
            city = item.get("city", "").strip()
            region = item.get("region", "").strip()
            type_ = item.get("type", "").strip()
            website = item.get("website", "").strip()
            slug = slugify(name, allow_unicode=True) or slugify(name) or name.lower().replace(" ", "-")
            # try by slug first
            school = School.objects.filter(slug=slug).first()
            # if not found, try by short_name (for the 8 seed schools whose name may differ slightly)
            if not school and short_name:
                school = School.objects.filter(short_name=short_name).first()
            if school:
                # update fields
                changed = False
                for k, v in [("name", name), ("short_name", short_name), ("city", city), ("region", region), ("type", type_), ("website", website)]:
                    if getattr(school, k) != v:
                        setattr(school, k, v)
                        changed = True
                # ensure slug reflects current name if name changed
                new_slug = slugify(name, allow_unicode=True) or slugify(name)
                if school.slug != new_slug and not School.objects.filter(slug=new_slug).exclude(pk=school.pk).exists():
                    school.slug = new_slug
                if changed:
                    school.save()
                    updated += 1
                else:
                    # still count as updated if we touched short_name etc that was empty before
                    pass
                # if school existed but no field changed, don't count
                if not changed:
                    # check if we just matched by short_name but slug differs — need to save slug if free
                    pass
            else:
                # ensure unique slug
                base, i = slug, 1
                while School.objects.filter(slug=slug).exists():
                    slug = f"{base}-{i}"
                    i += 1
                School.objects.create(name=name, slug=slug, city=city, short_name=short_name, region=region, type=type_, website=website)
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Готово: создано {created}, обновлено {updated}, всего {School.objects.count()} вузов."))
