# 0008 — academy_access 선택지에 'view_down_2026' (2026년 열람+다운로드) 추가.
# (컨테이너 적용분 0007_member_current_session_key… 뒤로 재배치)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('member', '0007_member_current_session_key_member_max_allowed_ips_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='member',
            name='academy_access',
            field=models.CharField(
                choices=[
                    ('none', '접근 없음'),
                    ('variant_view', '변형문제 열람만'),
                    ('variant_down', '변형문제 열람+다운로드'),
                    ('view_down_2026', '2026년 열람+다운로드'),
                    ('full', '모고 전체'),
                ],
                default='none',
                help_text=(
                    '외부/학원 계정용. none=접근X, variant_view=변형문제 열람만, '
                    'variant_down=변형문제 열람+다운로드, view_down_2026=2026년 자료만 열람+다운로드, '
                    'full=모고 전체. '
                    '관리자(is_staff·is_superuser)는 이 값과 무관하게 항상 전체.'
                ),
                max_length=15,
                verbose_name='모고 데이터 접근범위',
            ),
        ),
    ]
