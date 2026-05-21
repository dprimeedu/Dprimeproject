"""
단원별 학생 숙련 단계 — 힌트 단계 축소 + XP 배수.

학생에게는 "기본 / 도전 ★ / 마스터 ★★" 로 표시 (XP 레벨업과 어휘 분리).
내부 코드 level=1/2/3 그대로 사용.

흐름
- 기본 (1):   한글 → 첫글자 → 정답 (×1.0)
- 도전 (2):   한글 → 정답 (첫글자 제거, ×1.2)
- 마스터 (3): 정답만 (힌트 제거, ×1.5)

측정 단위 = "이번 풀이 한 번(세션)"의 결과 비율.
이번 세션 잘 풀면 다음 같은 단원 풀이에 승급된 상태로 시작.
"""
from django.db.models import Q

from ..models import StudentUnitLevel, WritingAttempt


# 한 세션 안에서 비-자동 결과가 이만큼 이상이어야 승급/강등 판정
MIN_SESSION_WORDS = 5
PROMOTE_RATIO = 0.8
DEMOTE_RATIO = 0.6

LEVEL_XP_MULTIPLIER = {1: 1.0, 2: 1.2, 3: 1.5}

# 단계별 한 단어에 허용되는 최대 시도 횟수 (이를 넘기면 정답 공개)
MAX_ATTEMPTS_BY_LEVEL = {1: 3, 2: 2, 3: 1}

LEVEL_NAME = {1: '기본', 2: '도전', 3: '마스터'}
LEVEL_STARS = {1: '', 2: '★', 3: '★★'}


def get_or_create_unit_level(student, unit):
    obj, _ = StudentUnitLevel.objects.get_or_create(student=student, unit=unit)
    return obj


def xp_multiplier(unit_level):
    return LEVEL_XP_MULTIPLIER.get(unit_level, 1.0)


def max_attempts_for(unit_level):
    return MAX_ATTEMPTS_BY_LEVEL.get(unit_level, 3)


def recompute_unit_level(student, unit, session):
    """
    이번 세션 결과로 단원 단계 재계산.

    카테고리(단어당 마지막 attempt 기준):
    - PERFECT = is_correct AND hint_level=0
    - GREAT   = is_correct AND hint_level=1
    - BOO 등  = 나머지
    자동 채우기(is_correct=True AND score_earned=0) 제외.

    Returns: (old_level, new_level). 변경 없으면 둘이 같음.
    """
    sul = get_or_create_unit_level(student, unit)
    old = sul.level

    qs = (
        WritingAttempt.objects
        .filter(session=session)
        .filter(Q(is_correct=True) | Q(hint_level=3))
        .exclude(is_correct=True, score_earned=0)
        .values('is_correct', 'hint_level')
    )
    rows = list(qs)
    total = len(rows)

    if total < MIN_SESSION_WORDS:
        return (old, old)

    perfect = sum(1 for r in rows if r['is_correct'] and r['hint_level'] == 0)
    great = sum(1 for r in rows if r['is_correct'] and r['hint_level'] == 1)

    perfect_ratio = perfect / total
    pg_ratio = (perfect + great) / total

    new = old
    if old == 1:
        # 마스터 점프 우선 (PERFECT 80%면 도전 거치지 않고)
        if perfect_ratio >= PROMOTE_RATIO:
            new = 3
        elif pg_ratio >= PROMOTE_RATIO:
            new = 2
    elif old == 2:
        if perfect_ratio >= PROMOTE_RATIO:
            new = 3
        elif pg_ratio < DEMOTE_RATIO:
            new = 1
    elif old == 3:
        if perfect_ratio < DEMOTE_RATIO:
            new = 2

    if new != old:
        sul.level = new
        sul.save(update_fields=['level', 'updated_at'])
    return (old, new)


def level_summary(unit_level):
    """클라이언트 표시용 — 단계 이름/별/설명."""
    if unit_level == 2:
        return {
            'level': 2, 'name': '도전', 'stars': '★', 'multiplier': 1.2,
            'hint_style': '한글 → 정답', 'desc': '첫글자 힌트 없음',
        }
    if unit_level == 3:
        return {
            'level': 3, 'name': '마스터', 'stars': '★★', 'multiplier': 1.5,
            'hint_style': '정답만', 'desc': '힌트 없음',
        }
    return {
        'level': 1, 'name': '기본', 'stars': '', 'multiplier': 1.0,
        'hint_style': '한글 → 첫글자 → 정답', 'desc': '기본',
    }
