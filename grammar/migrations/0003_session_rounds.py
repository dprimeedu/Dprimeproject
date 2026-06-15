import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('grammar', '0002_sets_and_wrong'),
    ]

    operations = [
        migrations.AddField(
            model_name='grammarsession',
            name='round_no',
            field=models.IntegerField(default=1, verbose_name='차시'),
        ),
        migrations.AddField(
            model_name='grammarsession',
            name='parent',
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name='retries', to='grammar.grammarsession', verbose_name='이전 차시'),
        ),
    ]
