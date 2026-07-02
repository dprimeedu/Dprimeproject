from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vocab', '0008_mockvocab_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='vocabword',
            name='definition',
            field=models.TextField(blank=True, default='', verbose_name='영영정의'),
        ),
    ]
