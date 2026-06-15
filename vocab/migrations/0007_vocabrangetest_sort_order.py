from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('vocab', '0006_wordcardstar'),
    ]

    operations = [
        migrations.AddField(
            model_name='vocabrangetest',
            name='sort_order',
            field=models.IntegerField(default=0, verbose_name='관리표 행순서'),
        ),
    ]
