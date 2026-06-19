from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exam', '0009_exampaper_range_end_exampaper_range_start_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='examsession',
            name='student_redblue_done',
            field=models.BooleanField(db_index=True, default=False, verbose_name='학생 빨파채점 완료'),
        ),
        migrations.AddField(
            model_name='examsession',
            name='student_redblue_done_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='학생 빨파채점 시각'),
        ),
        migrations.AddField(
            model_name='examsession',
            name='teacher_final_confirmed',
            field=models.BooleanField(db_index=True, default=False, verbose_name='선생님 최종 확인'),
        ),
        migrations.AddField(
            model_name='examsession',
            name='teacher_final_confirmed_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='최종 확인 시각'),
        ),
    ]
