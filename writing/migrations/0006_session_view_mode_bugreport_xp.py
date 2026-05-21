from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('writing', '0005_studentunitlevel'),
    ]

    operations = [
        migrations.AddField(
            model_name='writingsession',
            name='view_mode',
            field=models.BooleanField(
                default=False,
                help_text='켜면 점수 ×0.5, 이 세션은 단계 재계산에서 제외',
                verbose_name='보고 학습 모드',
            ),
        ),
        migrations.AddField(
            model_name='bugreport',
            name='xp_awarded',
            field=models.IntegerField(
                default=0,
                help_text='신고 즉시 학생에게 지급된 XP (PERFECT 풀이 XP × 2)',
                verbose_name='지급 XP',
            ),
        ),
        migrations.AddField(
            model_name='bugreport',
            name='xp_rolled_back',
            field=models.BooleanField(
                default=False,
                help_text='관리자 검토 후 문제 없는 신고로 판단해 학생 XP에서 회수',
                verbose_name='XP 회수됨',
            ),
        ),
        migrations.AddField(
            model_name='bugreport',
            name='xp_rolled_back_at',
            field=models.DateTimeField(blank=True, null=True, verbose_name='XP 회수 시각'),
        ),
    ]
