from django.db import migrations


class Migration(migrations.Migration):
    """Join the dev history (0002..0009) with the production-ready one (0002..0006)."""

    dependencies = [
        ("reviews", "0009_email_verification"),
        ("reviews", "0006_fill_regions_mark_demo"),
    ]

    operations = []
