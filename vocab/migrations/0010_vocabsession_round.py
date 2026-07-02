from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('vocab', '0009_vocabword_definition'),
    ]

    operations = [
        migrations.AddField(
            model_name='vocabsession',
            name='round_no',
            field=models.IntegerField(default=1, verbose_name='차시'),
        ),
        migrations.AddField(
            model_name='vocabsession',
            name='parent',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='retries', to='vocab.vocabsession',
                verbose_name='이전 차시'),
        ),
    ]
