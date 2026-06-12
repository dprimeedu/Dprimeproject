"""영작 단원 '세트 패킹' — 한 세트 SET_SIZE(15)개 기준으로 단원을 합치고 재번호.

배경: 외부(부교재 출력/AI 자동화) 푸시가 큰 단원을 20개씩 잘라 단원명에
'... 통합 (1/2)', '(2/2)' 처럼 분할해 보냈다. 그 결과 한 단원은 20문제,
다른 단원은 남는 8문제로 들쭉날쭉해졌다.

여기서는 그 '(n/m)' 분할 접미사를 떼어 하나의 단원으로 합치고, 문제를
1..N 연속 번호로 다시 매긴다. 시험(TEST)은 views._chunks_from_indices 가
이 연속 index 를 SET_SIZE 단위로 끊으므로, 마지막 미완성 세트가 다음 추가분으로
자연히 채워진다('남는 8개 → 7개 채워 15, 그다음 새 세트').

학생 데이터 보존: 문제는 pk 를 유지한 채 unit/index 만 갱신(WritingAttempt FK 보존),
배정/세션/단원레벨은 합칠 단원으로 이전. 임시성 데이터(매치룸·플래시카드 heartbeat)
와 빈 단원 껍데기만 삭제.
"""
import re

from django.db import transaction

from ..models import (
    WritingUnit, WritingProblem, UnitAssignment, WritingSession, StudentUnitLevel,
)

SET_SIZE = 15

# 단원명 끝의 분할 접미사 ' (2/2)' 형태. 'part1' 등 다른 표기는 건드리지 않는다.
_SPLIT_RE = re.compile(r'\s*\(\s*(\d+)\s*/\s*(\d+)\s*\)\s*$')


def base_title(title):
    """'동백고2 ... 통합 (2/2)' → ('동백고2 ... 통합', 2). 접미사 없으면 (title, 1)."""
    t = (title or '').strip()
    m = _SPLIT_RE.search(t)
    if not m:
        return t, 1
    return _SPLIT_RE.sub('', t).strip(), int(m.group(1))


def _max_index(unit):
    m = (WritingProblem.objects.filter(unit=unit)
         .order_by('-index').values_list('index', flat=True).first())
    return m or 0


def _move_refs(target, sib):
    """sib 단원의 배정/세션/단원레벨을 target 으로 이전(문제 제외)."""
    for a in UnitAssignment.objects.filter(unit=sib):
        UnitAssignment.objects.get_or_create(student_id=a.student_id, unit=target)
    UnitAssignment.objects.filter(unit=sib).delete()
    WritingSession.objects.filter(unit=sib).update(unit=target)
    for lv in StudentUnitLevel.objects.filter(unit=sib):
        cur = StudentUnitLevel.objects.filter(student_id=lv.student_id, unit=target).first()
        if cur:
            if lv.level > cur.level:
                cur.level = lv.level
                cur.save(update_fields=['level'])
            lv.delete()
        else:
            lv.unit = target
            lv.save(update_fields=['unit'])


def absorb_siblings(target, siblings):
    """siblings 단원들의 문제를 target 뒤에 연속 번호로 이어붙이고, 참조 이전 후 삭제.

    문제는 pk 보존(unit/index 갱신) → 기존 시도(WritingAttempt) 유지.
    반환: 옮긴 문제 수.
    """
    moved = 0
    for sib in siblings:
        if sib.id == target.id:
            continue
        cur = _max_index(target)
        probs = list(WritingProblem.objects.filter(unit=sib).order_by('index'))
        for i, p in enumerate(probs, start=cur + 1):
            p.unit = target
            p.index = i
        if probs:
            WritingProblem.objects.bulk_update(probs, ['unit', 'index'])
            moved += len(probs)
        _move_refs(target, sib)
        sib.delete()   # 남은 임시참조(매치룸·플래시카드·버그)는 CASCADE/ SET_NULL 처리
    return moved


def renumber(unit):
    """단원 문제를 정렬 순서대로 1..N 연속 재번호 (구멍/중복 제거). pk 보존."""
    probs = list(WritingProblem.objects.filter(unit=unit).order_by('index', 'id'))
    # unique(unit,index) 충돌 방지: 1차로 큰 오프셋, 2차로 최종값
    for off, p in enumerate(probs, start=1):
        p.index = 1_000_000 + off
    if probs:
        WritingProblem.objects.bulk_update(probs, ['index'])
    for i, p in enumerate(probs, start=1):
        p.index = i
    if probs:
        WritingProblem.objects.bulk_update(probs, ['index'])
    return len(probs)


@transaction.atomic
def consolidate_title(base, school_title=None):
    """주어진 base 제목과 그 '(n/m)' 형제 단원들을 하나로 합쳐 1..N 재번호.

    base: 합칠 기준 제목(접미사 없는 형태). 반환: (target_unit, 합쳐진 형제 수) | (None,0).
    """
    fam = [u for u in WritingUnit.objects.filter(title__startswith=base)
           if base_title(u.title)[0] == base]
    if not fam:
        return None, 0
    # 대상 선택: 접미사 없는 제목 우선 → 없으면 part 작은 것 → id 작은 것
    fam.sort(key=lambda u: (base_title(u.title)[1], u.id))
    target = next((u for u in fam if u.title.strip() == base), fam[0])
    if target.title.strip() != base:
        target.title = base
        target.save(update_fields=['title', 'updated_at'])
    siblings = [u for u in fam if u.id != target.id]
    absorb_siblings(target, siblings)
    renumber(target)
    return target, len(siblings)


def find_families():
    """합칠 후보 = 같은 base 제목을 가진 단원이 2개 이상이거나 '(n/m)' 접미사가 있는 것.

    반환: {base_title: [WritingUnit, ...]}
    """
    fams = {}
    for u in WritingUnit.objects.all():
        b, _ = base_title(u.title)
        fams.setdefault(b, []).append(u)
    # '(n/m)' 분할 접미사를 가진 단원이 하나라도 있는 단원군만 대상(동명 중복은 건드리지 않음).
    out = {}
    for b, us in fams.items():
        if any(_SPLIT_RE.search(u.title) for u in us):
            out[b] = us
    return out
