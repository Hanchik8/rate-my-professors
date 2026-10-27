from django.db import migrations


def fill_search_text_and_fix_duplicates(apps, schema_editor):
    """Prepare old data for the new constraints without deleting anything:
    * fill Professor.search_text;
    * duplicate professors (same school + name, any case) beyond the first -> status "rejected"
      (a moderator can review them in the admin);
    * duplicate reviews of one author for one professor+course -> course gets a " (2)" suffix.
    """
    Professor = apps.get_model("reviews", "Professor")
    Review = apps.get_model("reviews", "Review")
    seen = set()
    for p in Professor.objects.order_by("created_at", "id"):
        p.search_text = " ".join(f"{p.first_name} {p.last_name} {p.department}".lower().replace("ё", "е").split())
        key = (p.school_id, p.first_name.lower(), p.last_name.lower())
        if p.status != "rejected":
            if key in seen:
                p.status = "rejected"
            seen.add(key)
        p.save(update_fields=["search_text", "status"])
    seen = {}
    for r in Review.objects.filter(author__isnull=False).order_by("created_at", "id"):
        key = (r.professor_id, r.author_id, r.course.lower())
        if key in seen:
            seen[key] += 1
            r.course = f"{r.course[:74]} ({seen[key]})"
            r.save(update_fields=["course"])
        else:
            seen[key] = 1


class Migration(migrations.Migration):

    dependencies = [
        ("reviews", "0002_production_hardening"),
    ]

    operations = [
        migrations.RunPython(fill_search_text_and_fix_duplicates, migrations.RunPython.noop),
    ]
