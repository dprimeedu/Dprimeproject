from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('member', '0003_member_nickname'),
    ]

    operations = [
        migrations.AddField(
            model_name='member',
            name='school',
            field=models.CharField(blank=True, default='', help_text="학년 숫자를 뺀 학교명. 예: '동백중', '백현고'. 단원 자동배정 매칭에 사용.", max_length=30, verbose_name='학교'),
        ),
        migrations.AddField(
            model_name='member',
            name='grade',
            field=models.CharField(blank=True, default='', help_text="단원 학년과 동일 포맷. 예: '중2', '고3'. 단원 자동배정 매칭에 사용.", max_length=10, verbose_name='학년'),
        ),
    ]
