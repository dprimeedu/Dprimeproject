from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('grammar', '0003_session_rounds'),
    ]

    operations = [
        migrations.AddField(
            model_name='grammarsession',
            name='closed',
            field=models.BooleanField(default=False, db_index=True, verbose_name='마감(학생에게 숨김)'),
        ),
    ]
