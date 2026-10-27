"""Fill School.region from the city, and mark professors made by the old
seed_fake (last name with a numeric suffix like "Орозбаев-1865", no author)
as demo data, so `seed_fake --wipe` can remove them without touching real data."""
from django.db import migrations

# frozen copy: migrations must not import app code that may change later
CITY_REGION = {
    "Бишкек": "bishkek", "Ош": "osh-city", "Баткен": "batken", "Кызыл-Кия": "batken", "Сулюкта": "batken",
    "Жалал-Абад": "jalal-abad", "Таш-Кумыр": "jalal-abad", "Кара-Куль": "jalal-abad", "Майлуу-Суу": "jalal-abad",
    "Каракол": "issyk-kul", "Балыкчы": "issyk-kul", "Чолпон-Ата": "issyk-kul", "Нарын": "naryn",
    "Узген": "osh", "Кара-Суу": "osh", "Талас": "talas", "Токмок": "chuy", "Кант": "chuy",
    "Кара-Балта": "chuy", "Шопоков": "chuy", "Ивановка": "chuy",
}


def forward(apps, schema_editor):
    School = apps.get_model("reviews", "School")
    Professor = apps.get_model("reviews", "Professor")
    for s in School.objects.filter(region=""):
        region = CITY_REGION.get((s.city or "").strip(), "")
        if region:
            s.region = region
            s.save(update_fields=["region"])
    Professor.objects.filter(created_by__isnull=True, last_name__regex=r"-[0-9]+$").update(is_demo=True)


class Migration(migrations.Migration):
    dependencies = [("reviews", "0005_regions_and_school_details")]
    operations = [migrations.RunPython(forward, migrations.RunPython.noop)]
