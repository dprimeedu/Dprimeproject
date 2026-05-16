from django.db import migrations


BADGES = [
    ('first_word',       '🌱', '첫걸음',          '첫 단어 정답',                 'first_word',     1,  1),
    ('ten_perfect',      '⭐', 'PERFECT TEN',     '1차 시도 정답 단어 10개',      'perfect_count', 10,  2),
    ('hundred_perfect',  '💯', 'PERFECT 100',     '1차 시도 정답 단어 100개',     'perfect_count', 100, 3),
    ('combo_5',          '🔥', '5콤보',           '5단어 연속 정답',              'word_combo',    5,   4),
    ('combo_10',         '🔥', '10콤보',          '10단어 연속 정답',             'word_combo',    10,  5),
    ('combo_50',         '👑', '콤보 마스터',     '50단어 연속 정답',             'word_combo',    50,  6),
    ('perfect_sentence', '✨', 'Perfect Sentence', '첫 무실수 문장 완료',         'perfect_sent',  1,   7),
    ('perfect_unit',     '🏆', 'Perfect Unit',     '한 단원 전체 무실수 완료',     'perfect_unit',  1,   8),
    ('streak_7',         '📅', '일주일 개근',     '7일 연속 로그인',              'login_streak',  7,   9),
    ('streak_30',        '📅', '한달 개근',       '30일 연속 로그인',             'login_streak',  30, 10),
    ('speed_demon',      '⚡', '스피드 데몬',     'Speed Bonus 50회 획득',        'speed',         50, 11),
    ('early_bird',       '🌅', '얼리버드',        '오전 7시 이전 학습',           'time_of_day',   7,  12),
    ('night_owl',        '🦉', '올빼미',          '밤 11시 이후 학습',            'time_of_day',   23, 13),
]


def seed_badges(apps, schema_editor):
    Achievement = apps.get_model('writing', 'Achievement')
    for code, icon, name, desc, cond_type, cond_value, order in BADGES:
        Achievement.objects.update_or_create(
            code=code,
            defaults={
                'icon': icon,
                'name': name,
                'description': desc,
                'condition_type': cond_type,
                'condition_value': cond_value,
                'order': order,
            },
        )


def remove_badges(apps, schema_editor):
    Achievement = apps.get_model('writing', 'Achievement')
    Achievement.objects.filter(code__in=[b[0] for b in BADGES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('writing', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_badges, remove_badges),
    ]
