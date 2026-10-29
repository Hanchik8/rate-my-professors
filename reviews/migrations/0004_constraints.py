import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reviews", "0003_fill_search_text"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='professor',
            constraint=models.UniqueConstraint(models.F('school'), django.db.models.functions.text.Lower('first_name'), django.db.models.functions.text.Lower('last_name'), condition=models.Q(('status', 'rejected'), _negated=True), name='uniq_prof_school_name_ci'),
        ),
        migrations.AddConstraint(
            model_name='review',
            constraint=models.UniqueConstraint(models.F('professor'), models.F('author'), django.db.models.functions.text.Lower('course'), condition=models.Q(('author__isnull', False)), name='uniq_review_author_prof_course'),
        ),
        migrations.AddConstraint(
            model_name='review',
            constraint=models.CheckConstraint(condition=models.Q(('overall__gte', 1), ('overall__lte', 5)), name='review_overall_1_5'),
        ),
        migrations.AddConstraint(
            model_name='review',
            constraint=models.CheckConstraint(condition=models.Q(('difficulty__gte', 1), ('difficulty__lte', 5)), name='review_difficulty_1_5'),
        ),
    ]
