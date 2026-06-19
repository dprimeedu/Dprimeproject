from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('exam', '0010_examsession_student_redblue_done'),
    ]

    operations = [
        migrations.AddField(
            model_name='examanswer',
            name='review_marked',
            field=models.BooleanField(default=False, verbose_name='학생 모르는 문제 표시'),
        ),
    ]
