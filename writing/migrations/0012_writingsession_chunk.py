from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('writing', '0011_flashcardactivity'),
    ]

    operations = [
        migrations.AddField(
            model_name='writingsession',
            name='start_index',
            field=models.IntegerField(blank=True, null=True, verbose_name='시작 문항'),
        ),
        migrations.AddField(
            model_name='writingsession',
            name='end_index',
            field=models.IntegerField(blank=True, null=True, verbose_name='끝 문항'),
        ),
    ]
