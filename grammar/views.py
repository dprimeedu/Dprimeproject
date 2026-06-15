"""어법 앱 — Phase 1: import API(문항 등록) + range import(오늘 볼 어법TEST).
학생 응시/채점 UI는 Phase 2.
"""
import json
import random
from collections import OrderedDict, defaultdict

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import (
    GrammarUnit, GrammarProblem, GrammarAssignment, GrammarRangeTest,
    GrammarSession, GrammarAnswer, GrammarWrongAnswer,
)
from .services import grade_from_school, auto_grade
from member.auto_assign import auto_assign_unit

# 한 세트 문항 수 (어법은 40개씩)
SET_SIZE = 40


def _student_sets(student_id, unit_id, idxs, size=SET_SIZE):
    """시험범위 idxs를 학생별로 '고정 셔플' 후 size씩 분할(비겹침·골고루 랜덤).
    같은 학생·단원·범위면 항상 같은 세트 → '세트1'은 늘 같은 40문항."""
    if not idxs:
        return []
    shuffled = list(idxs)
    seed = f'{student_id}-{unit_id}-{idxs[0]}-{idxs[-1]}-{len(idxs)}'
    random.Random(seed).shuffle(shuffled)
    return [shuffled[i:i + size] for i in range(0, len(shuffled), size)]


def _range_indices(all_idx, rt):
    """오늘 볼 어법TEST(rt) 범위가 있으면 그 안의 번호만, 없으면 전체."""
    if rt and rt.start_index and rt.end_index:
        return [i for i in all_idx if rt.start_index <= i <= rt.end_index]
    return all_idx


def _target_set_count(rt):
    """학생관리자료에서 온 오늘볼TEST(rt) → 오늘 목표 세트 수.
    rt 범위 문항수를 40으로 나눠 올림(예: 1~100 → 3세트). 없으면 0(제한 없음)."""
    if rt and rt.start_index and rt.end_index:
        n = rt.end_index - rt.start_index + 1
        if n > 0:
            return -(-n // SET_SIZE)  # 올림
    return 0


def _ranged_problems(session):
    """세션이 실제 출제한 문항 목록(출제 순서 유지). problem_indices 있으면 그것, 없으면 범위."""
    if session.problem_indices:
        try:
            idxs = json.loads(session.problem_indices)
        except (ValueError, TypeError):
            idxs = []
        if idxs:
            by_idx = {p.index: p for p in session.unit.problems.filter(index__in=idxs)}
            return [by_idx[i] for i in idxs if i in by_idx]
    qs = session.unit.problems.all().order_by('index')
    if session.start_index is not None:
        qs = qs.filter(index__gte=session.start_index)
    if session.end_index is not None:
        qs = qs.filter(index__lte=session.end_index)
    return list(qs)


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
# 학생 — 홈 / 응시 / 제출(자동채점) / 결과
# ─────────────────────────────────────────────

@login_required
def student_home(request):
    """어법훈련 학생 홈 — 배정 단원 + 차시 버튼."""
    if not is_teacher(request.user) and not getattr(request.user, 'is_approved', False):
        return render(request, 'grammar/student_pending.html', {})
    if is_teacher(request.user):
        units = list(GrammarUnit.objects.filter(is_active=True).order_by('-created_at'))
        is_assigned_view = False
    else:
        units = [a.unit for a in GrammarAssignment.objects.filter(student=request.user).select_related('unit') if a.unit.is_active]
        is_assigned_view = True

    unit_ids = [u.id for u in units]
    idx_map = defaultdict(list)
    for uid, idx in (GrammarProblem.objects.filter(unit_id__in=unit_ids)
                     .order_by('index').values_list('unit_id', 'index')):
        idx_map[uid].append(idx)
    rt_map = {}
    if is_assigned_view:
        for rt in (GrammarRangeTest.objects.filter(student=request.user, is_active=True, unit_id__in=unit_ids)
                   .order_by('unit_id', '-created_at')):
            rt_map.setdefault(rt.unit_id, rt)
    for u in units:
        all_idx = idx_map.get(u.id, [])
        u.num_problems = len(all_idx)
        rt = rt_map.get(u.id)
        u.range_test = rt
        # 단어/요약문/영작처럼: 학생관리자료에서 지정한 그날 시험범위(rt)를 40개씩 끊어 세트로.
        u.has_range = bool(rt)
        u.range_label = rt.range_label if rt else ''
        if is_assigned_view and rt:
            rng = _range_indices(all_idx, rt)        # 시험범위 안 문항만
            sets = _student_sets(request.user.id, u.id, rng)
            u.sets = [{'no': i + 1, 'count': len(s)} for i, s in enumerate(sets)]
        else:
            u.sets = []

    # 다시 풀 차시 — 본인 세션 중 (1) 진행중인 2차시+ 이어풀기, (2) 채점완료 후 틀린 문제 재시험 대기
    retries = []
    if is_assigned_view:
        my = (GrammarSession.objects.filter(student=request.user, unit_id__in=unit_ids)
              .exclude(status=GrammarSession.STATUS_SUBMITTED)
              .select_related('unit').prefetch_related('answers', 'retries').order_by('-started_at'))
        for s in my:
            if s.status == GrammarSession.STATUS_IN_PROGRESS and s.round_no > 1:
                retries.append({'session': s, 'kind': 'continue',
                                'unit': s.unit.title, 'label': s.range_label,
                                'count': len(s.problem_indices and json.loads(s.problem_indices) or [])})
            elif s.status == GrammarSession.STATUS_GRADED and not s.retries.all():
                wrong = sum(1 for a in s.answers.all() if not a.is_correct)
                if wrong:
                    retries.append({'session': s, 'kind': 'retry',
                                    'unit': s.unit.title, 'label': s.range_label,
                                    'count': wrong, 'next_round': s.round_no + 1})
    return render(request, 'grammar/home.html', {
        'units': units, 'is_assigned_view': is_assigned_view, 'retries': retries})


@login_required
def start_session(request, unit_id):
    """세트 출제 — 시험범위를 학생별 고정 셔플 후 40개씩 비겹침. ?set=N (없으면 1)."""
    unit = get_object_or_404(GrammarUnit, pk=unit_id, is_active=True)
    if not is_teacher(request.user):
        if not GrammarAssignment.objects.filter(student=request.user, unit=unit).exists():
            messages.error(request, '이 단원은 배정되지 않았습니다.')
            return redirect('grammar:home')
    all_idx = list(unit.problems.order_by('index').values_list('index', flat=True))
    if not all_idx:
        messages.error(request, '이 단원에 문항이 없습니다.')
        return redirect('grammar:home')

    # 세트 = 학생관리자료에서 지정한 그날 시험범위(rt)를 40개씩 끊은 것. 범위 없으면 출제 불가.
    rt = (GrammarRangeTest.objects.filter(student=request.user, unit=unit, is_active=True)
          .order_by('-created_at').first()) if not is_teacher(request.user) else None
    rng = _range_indices(all_idx, rt) if rt else all_idx
    sets = _student_sets(request.user.id, unit.id, rng)
    if not sets:
        messages.error(request, '오늘 시험범위가 지정되지 않았습니다. 선생님께 문의하세요.')
        return redirect('grammar:home')
    try:
        n = int(request.GET.get('set') or request.GET.get('chunk') or 1)
    except (TypeError, ValueError):
        n = 1
    if n < 1 or n > len(sets):
        n = 1
    chosen = sets[n - 1]

    session = GrammarSession.objects.create(
        student=request.user, unit=unit,
        start_index=min(chosen), end_index=max(chosen),
        problem_indices=json.dumps(chosen), set_no=n)
    return redirect('grammar:session', session_id=session.id)


def _wrong_problems(session):
    """채점 완료된 세션에서 교사가 X(오답) 준 문항 목록(번호순)."""
    answers = session.answers.select_related('problem').order_by('problem__index')
    return [a.problem for a in answers if not a.is_correct]


@login_required
def start_retry(request, session_id):
    """다음 차시 — 교사가 X 준 문항만 다시 풀기. 부모 세션은 채점 완료여야 함."""
    parent = get_object_or_404(GrammarSession.objects.select_related('unit'), pk=session_id)
    if parent.student != request.user:
        messages.error(request, '본인 세션이 아닙니다.')
        return redirect('grammar:home')
    if parent.status != GrammarSession.STATUS_GRADED:
        messages.info(request, '선생님 채점이 끝난 뒤 다시 풀 수 있어요.')
        return redirect('grammar:result', session_id=parent.id)
    # 이미 다음 차시가 있으면 그것으로 이동(중복 생성 방지)
    existing = parent.retries.order_by('-started_at').first()
    if existing:
        return redirect('grammar:session' if existing.status == GrammarSession.STATUS_IN_PROGRESS
                        else 'grammar:result', session_id=existing.id)
    wrong = _wrong_problems(parent)
    if not wrong:
        messages.success(request, '틀린 문제가 없어요. 다시 풀 필요가 없습니다!')
        return redirect('grammar:result', session_id=parent.id)
    idxs = [p.index for p in wrong]
    retry = GrammarSession.objects.create(
        student=request.user, unit=parent.unit,
        start_index=min(idxs), end_index=max(idxs),
        problem_indices=json.dumps(idxs), set_no=parent.set_no,
        round_no=parent.round_no + 1, parent=parent)
    return redirect('grammar:session', session_id=retry.id)


@login_required
def session_view(request, session_id):
    session = get_object_or_404(GrammarSession, pk=session_id)
    if session.student != request.user:
        messages.error(request, '본인 세션이 아닙니다.')
        return redirect('grammar:home')
    if session.status != GrammarSession.STATUS_IN_PROGRESS:
        return redirect('grammar:result', session_id=session.id)
    problems = list(_ranged_problems(session))
    # 정답은 클라이언트에 안 보냄 (제출 시 서버 자동채점)
    problems_data = [{'id': p.id, 'index': p.index, 'sentence': p.sentence, 'sub_unit': p.sub_unit} for p in problems]
    return render(request, 'grammar/session.html', {
        'session': session, 'unit': session.unit,
        'problems_json': json.dumps(problems_data, ensure_ascii=False),
        'total_problems': len(problems),
    })


@login_required
@require_POST
def submit_session_api(request):
    """제출 → 서버 자동채점. body: {session_id, answers:{problem_id: 학생입력}}."""
    try:
        data = json.loads(request.body or '{}')
        session_id = int(data['session_id'])
        answers = data.get('answers') or {}
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return HttpResponseBadRequest('Invalid')
    session = get_object_or_404(
        GrammarSession, pk=session_id, student=request.user,
        status=GrammarSession.STATUS_IN_PROGRESS)
    problems = list(_ranged_problems(session))

    correct = 0
    with transaction.atomic():
        rows = []
        for p in problems:
            student_input = str(answers.get(str(p.id), '') or '').strip()
            ok = auto_grade(student_input, p.answer)   # True/False/None
            ac = bool(ok)
            if ac:
                correct += 1
            rows.append(GrammarAnswer(
                session=session, problem=p, student_input=student_input,
                auto_correct=ac, correct_answer=p.answer,
                admin_verdict='O' if ac else None))   # 자동 O는 미리 반영, X는 교사 검수 대상
        GrammarAnswer.objects.bulk_create(rows)
        session.total_count = len(problems)
        session.correct_count = correct
        session.status = GrammarSession.STATUS_SUBMITTED
        session.submitted_at = timezone.now()
        session.save(update_fields=['total_count', 'correct_count', 'status', 'submitted_at'])
    return JsonResponse({'success': True, 'redirect_url': f'/training/grammar/result/{session.id}/'},
                        json_dumps_params={'ensure_ascii': False})


@login_required
def result_view(request, session_id):
    session = get_object_or_404(GrammarSession.objects.select_related('unit'), pk=session_id)
    if session.student != request.user and not is_teacher(request.user):
        return redirect('grammar:home')
    answers = list(session.answers.select_related('problem').order_by('problem__index'))
    wrong_n = sum(1 for a in answers if not a.is_correct)
    # 다음 차시: 채점완료 + 틀린 문제 있음 + 아직 다음 차시 미생성
    next_round = session.round_no + 1
    can_retry = (session.status == GrammarSession.STATUS_GRADED and wrong_n > 0
                 and not session.retries.exists())
    retry_existing = session.retries.order_by('-started_at').first()
    return render(request, 'grammar/result.html', {
        'session': session, 'answers': answers, 'wrong_n': wrong_n,
        'can_retry': can_retry, 'next_round': next_round, 'retry_existing': retry_existing})


# ─────────────────────────────────────────────
# 교사 — 단원 목록 + 채점(자동채점 후 X 위주 검수)
# ─────────────────────────────────────────────

@teacher_required
def unit_list(request):
    units = list(GrammarUnit.objects.order_by('-created_at'))
    for u in units:
        u.pc = u.problem_count
    return render(request, 'grammar/unit_list.html', {'units': units})


@teacher_required
def grade_list(request):
    """제출/채점 세션 — 학생별 그룹(차시 칩). 채점대기 많은 학생 먼저."""
    show = request.GET.get('show', 'pending')
    qs = (GrammarSession.objects.exclude(status=GrammarSession.STATUS_IN_PROGRESS)
          .select_related('student', 'unit').order_by('-submitted_at'))
    if show == 'pending':
        qs = qs.filter(status=GrammarSession.STATUS_SUBMITTED)
    sessions = list(qs[:300])
    groups = OrderedDict()
    for s in sessions:
        g = groups.setdefault(s.student_id, {'student': s.student, 'sessions': []})
        g['sessions'].append(s)
    for g in groups.values():
        g['sessions'].sort(key=lambda x: (x.unit_id, x.start_index or 0, x.started_at))
        g['pending'] = sum(1 for x in g['sessions'] if x.status == GrammarSession.STATUS_SUBMITTED)
    grouped = sorted(groups.values(), key=lambda g: (-g['pending'], g['student'].username or ''))
    return render(request, 'grammar/grade_list.html', {'grouped': grouped, 'show': show})


@teacher_required
def grade_detail(request, session_id):
    """세션 1건 채점 — 자동채점 결과 + X 위주(틀린 것 먼저) O/X 보정."""
    session = get_object_or_404(GrammarSession.objects.select_related('student', 'unit'), pk=session_id)
    answers = list(session.answers.select_related('problem').order_by('problem__index'))
    rows = []
    for a in answers:
        verdict = a.admin_verdict if a.admin_verdict else ('O' if a.auto_correct else 'X')
        rows.append({'a': a, 'verdict': verdict, 'wrong': verdict == 'X'})
    # X(틀림) 먼저 정렬 — 교사 검수 집중
    rows.sort(key=lambda r: (not r['wrong'], r['a'].problem.index))
    wrong_count = sum(1 for r in rows if r['wrong'])
    return render(request, 'grammar/grade_detail.html', {
        'session': session, 'rows': rows, 'wrong_count': wrong_count})


@teacher_required
@require_POST
def grade_update_api(request, session_id):
    """채점 반영 — {verdicts:{answer_id:'O'|'X'}, finalize:bool}."""
    session = get_object_or_404(GrammarSession, pk=session_id)
    try:
        data = json.loads(request.body or '{}')
        verdicts = data.get('verdicts') or {}
        finalize = bool(data.get('finalize'))
    except (json.JSONDecodeError, TypeError):
        return HttpResponseBadRequest('Invalid')
    by_id = {a.id: a for a in session.answers.all()}
    changed = []
    for aid_str, v in verdicts.items():
        try:
            a = by_id.get(int(aid_str))
        except (ValueError, TypeError):
            continue
        if a is None:
            continue
        nv = 'O' if str(v).upper() == 'O' else 'X'
        if a.admin_verdict != nv:
            a.admin_verdict = nv
            changed.append(a)
    if changed:
        GrammarAnswer.objects.bulk_update(changed, ['admin_verdict'])

    was_graded = session.status == GrammarSession.STATUS_GRADED
    all_a = list(session.answers.select_related('problem').all())
    session.correct_count = sum(1 for a in all_a if a.is_correct)
    session.total_count = len(all_a)
    fields = ['correct_count', 'total_count']
    wrong_saved = 0
    if finalize:
        session.status = GrammarSession.STATUS_GRADED
        session.graded_at = timezone.now()
        session.graded_by = request.user
        fields += ['status', 'graded_at', 'graded_by']
    session.save(update_fields=fields)

    # 최초 검수완료에만 개인 오답 누적(재검수 시 중복 카운트 방지) — 구글 '틀린횟수' 패턴
    if finalize and not was_graded:
        for a in all_a:
            if not a.is_correct:
                wa, _ = GrammarWrongAnswer.objects.get_or_create(
                    student=session.student, problem=a.problem, defaults={'wrong_count': 0})
                wa.wrong_count = (wa.wrong_count or 0) + 1
                wa.resolved = False
                wa.save(update_fields=['wrong_count', 'resolved', 'last_wrong_at'])
                wrong_saved += 1
            else:
                # 맞춘 문항이 기존 오답이면 해결 표시(누적 횟수는 보존)
                GrammarWrongAnswer.objects.filter(
                    student=session.student, problem=a.problem).update(resolved=True)

    return JsonResponse({'success': True, 'correct': session.correct_count,
                         'total': session.total_count, 'percent': session.percent,
                         'status': session.status, 'wrong_saved': wrong_saved},
                        json_dumps_params={'ensure_ascii': False})
