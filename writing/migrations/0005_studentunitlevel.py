import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('writing', '0004_bugreport'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='StudentUnitLevel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('level', models.IntegerField(default=1)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='unit_levels', to=settings.AUTH_USER_MODEL)),
                ('unit', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='student_levels', to='writing.writingunit')),
            ],
            options={
                'verbose_name': '학생 단원 레벨',
                'verbose_name_plural': '학생 단원 레벨',
                'db_table': 'writing_student_unit_level',
                'unique_together': {('student', 'unit')},
            },
        ),
    ]
