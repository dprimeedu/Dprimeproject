from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('member', '0008_alter_member_academy_access'),
    ]

    operations = [
        migrations.AddField(
            model_name='member',
            name='needs_type_selection',
            field=models.BooleanField(
                default=False,
                help_text='소셜 가입처럼 학생/학원 구분을 안 받은 계정 — 다음 접속 시 선택 화면을 띄움.',
                verbose_name='가입 유형 선택 필요',
            ),
        ),
    ]
