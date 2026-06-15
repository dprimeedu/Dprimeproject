"""어법 앱 — Phase 1: import API(문항 등록) + range import(오늘 볼 어법TEST).
학생 응시/채점 UI는 Phase 2.
"""
import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import (
    GrammarUnit, GrammarProblem, GrammarAssignment, GrammarRangeTest,
)
from .services import grade_from_school
from member.auto_assign import auto_assign_unit


# ─────────────────────────────────────────────
# 권한
# ─────────────────────────────────────────────

def is_teacher(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    if getattr(user, 'member_type', '') in ('academy_admin', 'admin'):
        return True
    return bool(getattr(user, 'is_academy', False))


def teacher_required(view):
    return login_required(user_passes_test(is_teacher, login_url='/login/')(view))


# ─────────────────────────────────────────────
# 외부 자동화 연동 — 토큰 인증 import API
# ─────────────────────────────────────────────

def _check_token(request):
    expected = getattr(settings, 'GRAMMAR_IMPORT_TOKEN', '')
    if not expected:
        return False, '서버에 GRAMMAR_IMPORT_TOKEN 미설정'
    got = (request.headers.get('X-Grammar-Token') or request.GET.get('token') or '')
    if not got and request.body:
        try:
            got = (json.loads(request.body) or {}).get('token', '')
        except (json.JSONDecodeError, TypeError):
            got = ''
    return (got == expected), ('' if got == expected else '토큰 불일치')


def _find_student(name, login_id):
    User = get_user_model()
    base = User.objects.exclude(is_staff=True).exclude(is_superuser=True)
    login_id = (login_id or '').strip()
    name = (name or '').strip()
    if login_id:
        u = base.filter(login_id=login_id).first()
        if u:
            return u
    if name:
        qs = list(base.filter(username=name)[:2])
        if len(qs) == 1:
            return qs[0]
    return None


@csrf_exempt
@require_POST
def import_api(request):
    """어법 문항 일괄 등록.

    body: {token, school, unit?, items:[{idx, sentence, answer, sub_unit?, unit?}],
           mode?('replace'|'merge'|'append'), assign_to_list?}
    (school, unit) 별 GrammarUnit upsert. mode 로 문항 교체/통합/이어붙임.
    학교 토큰(동백고2 등) 매칭 학생 자동배정 + assign_to_list 명시배정.
    """
    ok, reason = _check_token(request)
    if not ok:
        return JsonResponse({'success': False, 'error': reason}, status=403)
    try:
        data = json.loads(request.body or '{}')
        items = data.get('items') or []
        school = str(data.get('school', '')).strip()
        top_unit = str(data.get('unit', '')).strip()
        mode = str(data.get('mode', 'replace') or 'replace').strip().lower()
        assign_to_list = [str(x).strip() for x in (data.get('assign_to_list') or []) if str(x).strip()]
    except (json.JSONDecodeError, TypeError):
        return HttpResponseBadRequest('Invalid JSON')
    if not items:
        return JsonResponse({'success': False, 'error': 'items 비어있음'}, status=400)

    groups = {}
    for it in items:
        u = str(it.get('unit') or top_unit or '').strip()
        groups.setdefault(u, []).append(it)

    grade = grade_from_school(school)
    results, created_total, created_units = [], 0, []
    with transaction.atomic():
        for unit_name, group in groups.items():
            unit_obj, _ = GrammarUnit.objects.update_or_create(
                school=school, exam=unit_name,
                defaults={
                    'title': (f'{school} {unit_name}').strip() or school or unit_name or '어법 단원',
                    'grade': grade, 'is_active': True,
                },
            )
            created_units.append(unit_obj)

            parsed = []
            for it in group:
                sentence = str(it.get('sentence', '') or '').strip()
                if not sentence:
                    continue
                try:
                    idx = int(it.get('idx'))
                except (TypeError, ValueError):
                    idx = len(parsed) + 1
                parsed.append({
                    'index': idx,
                    'sentence': sentence,
                    'answer': str(it.get('answer', '') or '').strip(),
                    'sub_unit': str(it.get('sub_unit', '') or '').strip(),
                })

            def _mk(p):
                return GrammarProblem(
                    unit=unit_obj, index=p['index'], sentence=p['sentence'],
                    answer=p['answer'], sub_unit=p['sub_unit'])

            if mode == 'append':
                base = (GrammarProblem.objects.filter(unit=unit_obj)
                        .order_by('-index').values_list('index', flat=True).first()) or 0
                rows = []
                for i, p in enumerate(parsed, start=base + 1):
                    p = dict(p); p['index'] = i
                    rows.append(_mk(p))
                GrammarProblem.objects.bulk_create(rows)
                n = len(rows)
            elif mode == 'merge':
                existing = {x.index: x for x in GrammarProblem.objects.filter(unit=unit_obj)}
                to_create, to_update = [], []
                for p in parsed:
                    x = existing.get(p['index'])
                    if x is None:
                        to_create.append(_mk(p))
                    else:
                        x.sentence, x.answer, x.sub_unit = p['sentence'], p['answer'], p['sub_unit']
                        to_update.append(x)
                if to_create:
                    GrammarProblem.objects.bulk_create(to_create)
                if to_update:
                    GrammarProblem.objects.bulk_update(to_update, ['sentence', 'answer', 'sub_unit'])
                n = len(to_create) + len(to_update)
            else:  # replace — 그 단원 문항 전체 지우고 새로
                GrammarProblem.objects.filter(unit=unit_obj).delete()
                GrammarProblem.objects.bulk_create([_mk(p) for p in parsed])
                n = len(parsed)
            created_total += n
            results.append({'unit_id': unit_obj.id, 'unit': unit_name, 'created': n})

    # 학교·학년 자동배정 + 명시 배정
    auto_assigned = 0
    for u in created_units:
        auto_assigned += auto_assign_unit(u, school, GrammarAssignment)
    assigned_many = None
    if assign_to_list:
        ok_names, fail = [], []
        for nm in assign_to_list:
            student = _find_student(nm, '')
            if student is None:
                fail.append(nm)
                continue
            for u in created_units:
                GrammarAssignment.objects.get_or_create(student=student, unit=u)
            ok_names.append(student.username)
        assigned_many = {'assigned': ok_names, 'failed': fail}

    return JsonResponse({
        'success': True, 'school': school, 'units': results,
        'created': created_total, 'auto_assigned': auto_assigned,
        'assigned_many': assigned_many,
    })


@csrf_exempt
@require_POST
def range_import_api(request):
    """오늘 볼 어법TEST 범위 등록 (학생관리표 '어법TEST' 열 → 동기화).

    body: {token, items:[{name, login_id?, school, start, end,
                          source?, threshold?}]}
    학생은 이름/ID, 단원은 school(학교학년)로 매칭. 같은 (학생,source) 기존 활성은 비활성화.
    """
    ok, reason = _check_token(request)
    if not ok:
        return JsonResponse({'success': False, 'error': reason}, status=403)
    try:
        data = json.loads(request.body or '{}')
        items = data.get('items') or []
    except (json.JSONDecodeError, TypeError):
        return HttpResponseBadRequest('Invalid JSON')

    created, skipped = 0, []
    for it in items:
        name = str(it.get('name', '')).strip()
        login_id = str(it.get('login_id', '')).strip()
        school = str(it.get('school', '')).strip()
        source = str(it.get('source') or '어법TEST').strip()
        try:
            start = int(it['start']); end = int(it['end'])
        except (KeyError, ValueError, TypeError):
            skipped.append(f'{name or login_id}: 범위 숫자 오류')
            continue
        student = _find_student(name, login_id)
        if not student:
            skipped.append(f'{name or login_id}: 학생 없음')
            continue
        unit = GrammarUnit.objects.filter(school=school, is_active=True).order_by('-created_at').first()
        if not unit:
            skipped.append(f'{name}: 어법 단원 없음(학교={school})')
            continue
        GrammarAssignment.objects.get_or_create(student=student, unit=unit)
        GrammarRangeTest.objects.filter(student=student, source_label=source, is_active=True).update(is_active=False)
        GrammarRangeTest.objects.create(
            student=student, unit=unit, start_index=start, end_index=end,
            source_label=source, pass_threshold=int(it.get('threshold') or 90))
        created += 1

    return JsonResponse({'success': True, 'created': created,
                         'skipped': skipped, 'skipped_count': len(skipped)})


# ─────────────────────────────────────────────
# 교사 — 단원 목록 (Phase 1 임시 랜딩; 응시/채점은 Phase 2)
# ─────────────────────────────────────────────

@teacher_required
def unit_list(request):
    units = list(GrammarUnit.objects.order_by('-created_at'))
    for u in units:
        u._pc = u.problem_count
    return render(request, 'grammar/unit_list.html', {'units': units})
