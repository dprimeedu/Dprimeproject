import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('summary', '0002_summarysession_end_index_summarysession_start_index'),
    ]

    operations = [
        migrations.CreateModel(
            name='SummaryRangeTest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('start_index', models.IntegerField(verbose_name='시작 번호')),
                ('end_index', models.IntegerField(verbose_name='끝 번호')),
                ('source_label', models.CharField(default='요약문완성', max_length=100, verbose_name='라벨')),
                ('is_active', models.BooleanField(default=True, verbose_name='활성화')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('assigned_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='summary_range_tests_made', to=settings.AUTH_USER_MODEL, verbose_name='배정자')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='summary_range_tests', to=settings.AUTH_USER_MODEL, verbose_name='학생')),
                ('unit', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='range_tests', to='summary.summaryunit', verbose_name='단원(요약문)')),
            ],
            options={
                'verbose_name': '요약문 시험 범위',
                'verbose_name_plural': '요약문 시험 범위',
                'db_table': 'summary_range_test',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='summaryrangetest',
            index=models.Index(fields=['student', 'is_active'], name='summary_rt_stu_act_idx'),
        ),
    ]
