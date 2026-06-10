import json
import re

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.http import JsonResponse, HttpResponseBadRequest
from django.conf import settings
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

# 동일 접근제어 헬퍼 재사용 (writing 미러 — vocab/views.py:15-18 과 동일 패턴)
from writing.views import is_teacher, teacher_required

from .models import (
    SummaryUnit, SummaryProblem, SummaryAssignment,
    SummarySession, SummaryBlankAnswer,
)


# ─────────────────────────────────────────────
# 공통
# ─────────────────────────────────────────────

_PUNCT = ',.!?;:"\'()[]{}'


def _norm(s):
    """자동 1차 판정용 정규화 — 소문자 + 양끝 공백/문장부호 제거 + 내부 공백 단일화."""
    s = (s or '').strip().lower()
    s = s.strip(_PUNCT).strip()
    s = re.sub(r'\s+', ' ', s)
    return s


BLANK_LABEL = {'a': 'ⓐ', 'b': 'ⓑ'}

# 시험은 10문제 단위 청크로 끊어 본다 (전체 업로드 후 10개씩).
CHUNK_SIZE = 10


def _chunks_from_indices(idxs):
    """정렬된 문항 index 리스트 → 10개 단위 청크 메타.

    [{num, start, end, count}] — start/end 는 실제 문항 index 경계(연속 아니어도 안전).
    """
    chunks = []
    for i in range(0, len(idxs), CHUNK_SIZE):
        seg = idxs[i:i + CHUNK_SIZE]
        if not seg:
            continue
        chunks.append({
            'num': i // CHUNK_SIZE + 1,
            'start': seg[0], 'end': seg[-1], 'count': len(seg),
        })
    return chunks


def _ranged_problems(session):
    """세션의 시험 범위에 해당하는 문항 queryset (범위 없으면 단원 전체)."""
    qs = session.unit.problems.all().order_by('index')
    if session.start_index is not None:
        qs = qs.filter(index__gte=session.start_index)
    if session.end_index is not None:
        qs = qs.filter(index__lte=session.end_index)
    return qs


# ─────────────────────────────────────────────
# 학생 화면
# ─────────────────────────────────────────────

@login_required
def student_home(request):
    """요약문완성훈련 학생 홈 — 배정된 단원 목록 (선생님은 전체)."""
    if not is_teacher(request.user) and not getattr(request.user, 'is_approved', False):
        return render(request, 'summary/student_pending.html', {})

    if is_teacher(request.user):
        units = list(SummaryUnit.objects.filter(is_active=True).order_by('-created_at'))
        is_assigned_view = False
    else:
        assignments = (SummaryAssignment.objects
                       .filter(student=request.user)
                       .select_related('unit'))
        units = [a.unit for a in assignments if a.unit.is_active]
        is_assigned_view = True

    unit_ids = [u.id for u in units]
    # 단원별 문항 index 모음 (1쿼리) → 문항 수 + 10개 단위 청크 버튼
    from collections import defaultdict
    idx_map = defaultdict(list)
    for uid, idx in (SummaryProblem.objects.filter(unit_id__in=unit_ids)
                     .order_by('index').values_list('unit_id', 'index')):
        idx_map[uid].append(idx)
    for u in units:
        u._problem_count = len(idx_map.get(u.id, []))
        u.chunks = _chunks_from_indices(idx_map.get(u.id, []))

    return render(request, 'summary/home.html', {
        'units': units,
        'is_assigned_view': is_assigned_view,
    })


@login_required
def start_session(request, unit_id):
    """단원 TEST 시작 — SummarySession 생성 후 풀이 화면으로."""
    unit = get_object_or_404(SummaryUnit, pk=unit_id, is_active=True)

    if not is_teacher(request.user):
        if not SummaryAssignment.objects.filter(student=request.user, unit=unit).exists():
            messages.error(request, '이 단원은 배정되지 않았습니다. 선생님께 문의하세요.')
            return redirect('summary:home')

    idxs = list(unit.problems.order_by('index').values_list('index', flat=True))
    if not idxs:
        messages.error(request, '이 단원에 문제가 없습니다.')
        return redirect('summary:home')

    # chunk=N 이면 그 10문제 범위만, 없으면 단원 전체.
    start_i = end_i = None
    chunk = request.GET.get('chunk')
    if chunk:
        try:
            c = int(chunk)
        except (TypeError, ValueError):
            c = 1
        seg = idxs[(c - 1) * CHUNK_SIZE: c * CHUNK_SIZE]
        if not seg:
            messages.error(request, '해당 시험 범위가 없습니다.')
            return redirect('summary:home')
        start_i, end_i = seg[0], seg[-1]

    session = SummarySession.objects.create(
        student=request.user, unit=unit, start_index=start_i, end_index=end_i,
    )
    return redirect('summary:session', session_id=session.id)


@login_required
def session_view(request, session_id):
    """실제 풀이 화면 — 요약문완성 TEST."""
    session = get_object_or_404(SummarySession, pk=session_id)
    if session.student != request.user:
        messages.error(request, '본인 세션이 아닙니다.')
        return redirect('summary:home')
    if session.status != SummarySession.STATUS_IN_PROGRESS:
        return redirect('summary:result', session_id=session.id)

    problems = list(_ranged_problems(session))
    # 클라이언트엔 정답/한글뜻을 보내지 않음 (check-blank API 로만 노출)
    problems_data = [{
        'id': p.id,
        'index': p.index,
        'sub_unit': p.sub_unit,
        'sentence1_template': p.sentence1_template,
        'sentence2_template': p.sentence2_template,
    } for p in problems]

    return render(request, 'summary/session.html', {
        'session': session,
        'unit': session.unit,
        'problems_json': json.dumps(problems_data, ensure_ascii=False),
        'total_problems': len(problems),
    })


@login_required
def result_view(request, session_id):
    """결과 화면 — 제출 완료 / 채점 대기 / 채점 완료."""
    session = get_object_or_404(
        SummarySession.objects.select_related('unit'), pk=session_id,
    )
    if session.student != request.user and not is_teacher(request.user):
        return redirect('summary:home')
    return render(request, 'summary/result.html', {'session': session})


# ─────────────────────────────────────────────
# 학생 — AJAX
# ─────────────────────────────────────────────

@login_required
@require_POST
def check_blank_api(request):
    """빈칸 1칸 자동 1차 판정 + 오답 시 한글뜻 1회 노출.

    body: {session_id, problem_id, blank: 'a'|'b', input, attempt: 1|2}
    - attempt 1: first_input 저장, 정규화 exact 비교.
        정답 → {correct:true, locked:true}
        오답 → korean_shown=True, {correct:false, korean, show_korean:true}
    - attempt 2: second_input 저장, 정오 숨김(관리자 채점용 봉인) → {recorded:true}
    """
    try:
        data = json.loads(request.body or '{}')
        session_id = int(data['session_id'])
        problem_id = int(data['problem_id'])
        blank = str(data.get('blank', '')).strip().lower()
        value = str(data.get('input', ''))
        attempt = int(data.get('attempt', 1))
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return HttpResponseBadRequest('Invalid')

    if blank not in ('a', 'b'):
        return HttpResponseBadRequest('blank must be a or b')

    session = get_object_or_404(
        SummarySession, pk=session_id, student=request.user,
        status=SummarySession.STATUS_IN_PROGRESS,
    )
    problem = get_object_or_404(SummaryProblem, pk=problem_id, unit=session.unit)
    answer = problem.answer_for(blank)
    korean = problem.korean_for(blank)

    ba, _ = SummaryBlankAnswer.objects.get_or_create(
        session=session, problem=problem, blank=blank,
        defaults={'correct_answer': answer},
    )
    if not ba.correct_answer:
        ba.correct_answer = answer

    norm_ans = _norm(answer)

    if attempt <= 1:
        # 1차 입력 — 자동 판정. 정답이면 O 확정, 오답이면 한글뜻 힌트.
        ba.first_input = value
        ba.first_auto_correct = bool(_norm(value)) and _norm(value) == norm_ans
        if ba.first_auto_correct:
            ba.save()
            return JsonResponse({'success': True, 'correct': True, 'locked': True},
                                json_dumps_params={'ensure_ascii': False})
        ba.korean_shown = True
        ba.save()
        return JsonResponse({
            'success': True, 'correct': False, 'hint_type': 'korean',
            'korean': korean or '(뜻 정보 없음)',
        }, json_dumps_params={'ensure_ascii': False})

    if attempt == 2:
        # 2차 입력 — 자동 판정. 정답이면 O 확정, 오답이면 영어 첫 글자 힌트.
        ba.second_input = value
        is_ok = bool(_norm(value)) and _norm(value) == norm_ans
        ba.save()
        if is_ok:
            return JsonResponse({'success': True, 'correct': True, 'locked': True},
                                json_dumps_params={'ensure_ascii': False})
        first_letter = (answer[0] + '_' * (len(answer) - 1)) if answer else ''
        return JsonResponse({
            'success': True, 'correct': False, 'hint_type': 'first_letter',
            'first_letter': first_letter,
        }, json_dumps_params={'ensure_ascii': False})

    # attempt 3 — 최종 입력 봉인. 정답 일치 시 제출 단계에서 관리자 판정 O 자동.
    ba.second_input = value
    ba.save()
    return JsonResponse({'success': True, 'recorded': True},
                        json_dumps_params={'ensure_ascii': False})


@login_required
@require_POST
def submit_session_api(request):
    """세션 제출 → 채점 대기 큐로. body: {session_id}.

    모든 (문항×빈칸)에 대해 SummaryBlankAnswer 행을 보장(미입력칸 포함)하고
    correct_answer 스냅샷을 채운다. 자동 정답은 admin_verdict='O' 기본값으로 선반영.
    """
    try:
        data = json.loads(request.body or '{}')
        session_id = int(data['session_id'])
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return HttpResponseBadRequest('Invalid')

    session = get_object_or_404(
        SummarySession, pk=session_id, student=request.user,
        status=SummarySession.STATUS_IN_PROGRESS,
    )
    problems = list(_ranged_problems(session))
    existing = {
        (ba.problem_id, ba.blank): ba
        for ba in session.blank_answers.all()
    }

    with transaction.atomic():
        to_create = []
        to_update = []
        for p in problems:
            for blank in ('a', 'b'):
                ba = existing.get((p.id, blank))
                ans = p.answer_for(blank)
                if ba is None:
                    to_create.append(SummaryBlankAnswer(
                        session=session, problem=p, blank=blank,
                        correct_answer=ans,
                        admin_verdict=None,
                    ))
                else:
                    if not ba.correct_answer:
                        ba.correct_answer = ans
                    # 학생 최종입력이 정답과 같으면 관리자 판정 기본값 O 로 선반영
                    # (1차 자동정답 + 한글뜻/첫글자 힌트 후 맞힌 재입력 모두 포함)
                    final_val = _norm(ba.second_input or ba.first_input)
                    if ba.admin_verdict is None and final_val and final_val == _norm(ans):
                        ba.admin_verdict = 'O'
                    to_update.append(ba)
        if to_create:
            # 새로 만드는 칸 중 자동정답인 경우는 없음(입력이 없었으므로) → verdict None
            SummaryBlankAnswer.objects.bulk_create(to_create)
        if to_update:
            SummaryBlankAnswer.objects.bulk_update(
                to_update, ['correct_answer', 'admin_verdict'])

        session.total_blanks = len(problems) * 2
        session.status = SummarySession.STATUS_SUBMITTED
        session.submitted_at = timezone.now()
        session.save(update_fields=['total_blanks', 'status', 'submitted_at'])

    return JsonResponse({
        'success': True,
        'redirect_url': f'/training/summary/result/{session.id}/',
    }, json_dumps_params={'ensure_ascii': False})


# ─────────────────────────────────────────────
# 선생님 / 관리자 — 채점 큐
# ─────────────────────────────────────────────

@teacher_required
def grade_list(request):
    """제출된 세션 목록 — 채점 대기/완료."""
    show = request.GET.get('show', 'pending')  # pending|all
    qs = (SummarySession.objects
          .exclude(status=SummarySession.STATUS_IN_PROGRESS)
          .select_related('student', 'unit')
          .order_by('-submitted_at'))
    if show == 'pending':
        qs = qs.filter(status=SummarySession.STATUS_SUBMITTED)
    sessions = list(qs[:300])
    return render(request, 'summary/grade_list.html', {
        'sessions': sessions, 'show': show,
    })


@teacher_required
def grade_detail(request, session_id):
    """세션 1건 채점 — 빈칸별 학생답 vs 정답 + O/X."""
    session = get_object_or_404(
        SummarySession.objects.select_related('student', 'unit'), pk=session_id,
    )
    answers = list(
        session.blank_answers
        .select_related('problem')
        .order_by('problem__index', 'blank')
    )
    rows = []
    for ba in answers:
        # 기본 판정값: 이미 판정됐으면 그것, 아니면 학생 최종입력==정답 여부
        if ba.admin_verdict:
            default_o = ba.admin_verdict == 'O'
        else:
            final_val = _norm(ba.second_input or ba.first_input)
            default_o = bool(final_val) and final_val == _norm(ba.correct_answer)
        rows.append({
            'ba': ba,
            'label': BLANK_LABEL.get(ba.blank, ba.blank),
            'default_o': default_o,
        })
    return render(request, 'summary/grade_detail.html', {
        'session': session, 'rows': rows,
    })


@teacher_required
@require_POST
def grade_update_api(request, session_id):
    """채점 반영 — 빈칸별 O/X 저장 + 점수 재계산 + 확정.

    body: {verdicts: {blank_answer_id: 'O'|'X'}, finalize: bool}
    """
    session = get_object_or_404(SummarySession, pk=session_id)
    try:
        data = json.loads(request.body or '{}')
        verdicts = data.get('verdicts') or {}
        finalize = bool(data.get('finalize'))
    except (json.JSONDecodeError, TypeError):
        return HttpResponseBadRequest('Invalid')

    answers = {ba.id: ba for ba in session.blank_answers.all()}
    changed = []
    for aid_str, v in verdicts.items():
        try:
            ba = answers.get(int(aid_str))
        except (ValueError, TypeError):
            continue
        if ba is None:
            continue
        nv = 'O' if str(v).upper() == 'O' else 'X'
        if ba.admin_verdict != nv:
            ba.admin_verdict = nv
            changed.append(ba)
    if changed:
        SummaryBlankAnswer.objects.bulk_update(changed, ['admin_verdict'])

    all_answers = list(session.blank_answers.all())
    session.correct_count = sum(1 for ba in all_answers if ba.admin_verdict == 'O')
    session.total_blanks = len(all_answers)
    fields = ['correct_count', 'total_blanks']
    if finalize:
        session.status = SummarySession.STATUS_GRADED
        session.graded_at = timezone.now()
        session.graded_by = request.user
        fields += ['status', 'graded_at', 'graded_by']
    session.save(update_fields=fields)

    return JsonResponse({
        'success': True,
        'correct': session.correct_count,
        'total': session.total_blanks,
        'percent': session.percent,
        'status': session.status,
    }, json_dumps_params={'ensure_ascii': False})


# ─────────────────────────────────────────────
# 선생님 / 관리자 — 단원 관리 + 배정
# ─────────────────────────────────────────────

@teacher_required
def unit_list(request):
    """요약문 단원 목록 — 문항 수 · 배정 학생 수."""
    units = list(SummaryUnit.objects.select_related('created_by').order_by('school', 'unit', 'title'))
    unit_ids = [u.id for u in units]
    prob_counts = dict(
        SummaryProblem.objects.filter(unit_id__in=unit_ids)
        .values('unit_id').annotate(c=Count('id')).values_list('unit_id', 'c')
    )
    assign_counts = dict(
        SummaryAssignment.objects.filter(unit_id__in=unit_ids)
        .values('unit_id').annotate(c=Count('id')).values_list('unit_id', 'c')
    )
    for u in units:
        u._problem_count = prob_counts.get(u.id, 0)
        u.assigned_count = assign_counts.get(u.id, 0)
    return render(request, 'summary/unit_list.html', {'units': units})


@teacher_required
@require_POST
def unit_delete(request):
    """체크한 단원들을 cascade(문항·배정·세션) 함께 삭제."""
    try:
        ids = [int(x) for x in request.POST.getlist('unit_ids') if x]
    except ValueError:
        ids = []
    if not ids:
        messages.warning(request, '삭제할 단원을 선택해주세요.')
        return redirect('summary:unit_list')
    qs = SummaryUnit.objects.filter(pk__in=ids)
    count = qs.count()
    qs.delete()
    messages.success(request, f'단원 {count}개 삭제 완료.')
    return redirect('summary:unit_list')


@teacher_required
@require_GET
def assignment_list(request, unit_id):
    """단원 1개의 배정 현황 + 전체 학생 — 단원별 배정 모달용."""
    unit = get_object_or_404(SummaryUnit, pk=unit_id)
    User = get_user_model()
    assigned_ids = set(
        SummaryAssignment.objects.filter(unit=unit).values_list('student_id', flat=True)
    )
    students = []
    for s in (User.objects.exclude(is_staff=True).exclude(is_superuser=True)
              .order_by('login_id', 'username')):
        if is_teacher(s):
            continue
        students.append({
            'id': s.id,
            'login_id': getattr(s, 'login_id', '') or '',
            'name': s.username or '',
            'is_assigned': s.id in assigned_ids,
        })
    return JsonResponse({
        'unit': {'id': unit.id, 'title': unit.title, 'school': unit.school},
        'students': students,
        'assigned_count': len(assigned_ids),
    }, json_dumps_params={'ensure_ascii': False})


@teacher_required
@require_POST
def assignment_update(request, unit_id):
    """단원의 배정 학생을 body.student_ids 로 통째 갱신."""
    unit = get_object_or_404(SummaryUnit, pk=unit_id)
    User = get_user_model()
    try:
        data = json.loads(request.body)
        target_ids = {int(x) for x in data.get('student_ids', [])}
    except (json.JSONDecodeError, ValueError, TypeError):
        return HttpResponseBadRequest('Invalid')

    valid_ids = set(
        User.objects.filter(pk__in=target_ids)
        .exclude(is_staff=True).exclude(is_superuser=True)
        .values_list('id', flat=True)
    )
    current_ids = set(
        SummaryAssignment.objects.filter(unit=unit).values_list('student_id', flat=True)
    )
    to_add = valid_ids - current_ids
    to_remove = current_ids - valid_ids
    if to_add:
        SummaryAssignment.objects.bulk_create([
            SummaryAssignment(student_id=sid, unit=unit, assigned_by=request.user)
            for sid in to_add
        ], ignore_conflicts=True)
    if to_remove:
        SummaryAssignment.objects.filter(unit=unit, student_id__in=to_remove).delete()
    return JsonResponse({
        'success': True,
        'assigned_count': SummaryAssignment.objects.filter(unit=unit).count(),
        'added': len(to_add), 'removed': len(to_remove),
    })


# ─────────────────────────────────────────────
# 외부(AI 자동화 요약문 생성) 연동 — 토큰 인증 API
# ─────────────────────────────────────────────

def _check_api_token(request):
    """공유 시크릿 토큰 검증. 헤더 X-Summary-Token 또는 body/GET token."""
    expected = getattr(settings, 'SUMMARY_IMPORT_TOKEN', '')
    if not expected:
        return False, '서버에 SUMMARY_IMPORT_TOKEN 미설정'
    got = (request.headers.get('X-Summary-Token')
           or request.GET.get('token') or '')
    if not got and request.body:
        try:
            got = (json.loads(request.body) or {}).get('token', '')
        except (json.JSONDecodeError, TypeError):
            got = ''
    if got != expected:
        return False, '토큰 불일치'
    return True, ''


def _grade_from_school(school):
    """학교학년 문자열(예: 백현고1)에서 학년(고1/중2 등) 추출. 실패 시 '기타'."""
    m = re.search(r'(고|중|초)\s*([1-3])', school or '')
    if m:
        g = m.group(1) + m.group(2)
        valid = {c[0] for c in SummaryUnit.GRADE_CHOICES}
        if g in valid:
            return g
    return '기타'


def _find_student_for_assign(name, login_id):
    """이름(username) 또는 login_id 로 학생 1명 찾기. 모호하면 (None, 사유)."""
    User = get_user_model()
    base = User.objects.exclude(is_staff=True).exclude(is_superuser=True)
    login_id = (login_id or '').strip()
    name = (name or '').strip()
    if login_id:
        u = base.filter(login_id=login_id).first()
        if u:
            return u, ''
    if name:
        qs = list(base.filter(username=name)[:2])
        if len(qs) == 1:
            return qs[0], ''
        if len(qs) > 1:
            return None, f'동명이인 {len(qs)}명 (login_id 필요)'
    return None, '학생 없음'


@csrf_exempt
@require_POST
def import_api(request):
    """요약문완성 문항 일괄 등록 (AI 자동화 요약문 생성 푸시).

    body: {token, school, unit?, assign_to?, assign_login_id?, items: [
        {idx, unit?, sub_unit?, sentence1_template, sentence1_answer, korean1,
         sentence2_template, sentence2_answer, korean2}, ...]}

    (school, unit) 별로 그룹핑하여 SummaryUnit upsert + 기존 SummaryProblem 교체(replace-on-reimport).
    assign_to(학생 이름) 또는 assign_login_id 지정 시 등록된 단원을 그 학생에게 배정.
    assign_to_list(이름 리스트) 지정 시 여러 학생에게 한꺼번에 배정(학교단위 단원 1개 → 학생 전원).
    """
    ok, reason = _check_api_token(request)
    if not ok:
        return JsonResponse({'success': False, 'error': reason}, status=403)
    try:
        data = json.loads(request.body or '{}')
        items = data.get('items') or []
        school = str(data.get('school', '')).strip()
        top_unit = str(data.get('unit', '')).strip()
        assign_to = str(data.get('assign_to', '') or '').strip()
        assign_login_id = str(data.get('assign_login_id', '') or '').strip()
        assign_to_list = [str(x).strip() for x in (data.get('assign_to_list') or []) if str(x).strip()]
    except (json.JSONDecodeError, TypeError):
        return HttpResponseBadRequest('Invalid JSON')

    if not items:
        return JsonResponse({'success': False, 'error': 'items 비어있음'}, status=400)

    # (unit) 별 그룹핑
    groups = {}
    for it in items:
        u = str(it.get('unit') or top_unit or '').strip()
        groups.setdefault(u, []).append(it)

    results = []
    created_total = 0
    created_units = []
    grade = _grade_from_school(school)
    with transaction.atomic():
        for unit_name, group in groups.items():
            unit_obj, _ = SummaryUnit.objects.update_or_create(
                school=school, unit=unit_name,
                defaults={
                    'title': (f'{school} {unit_name}').strip() or school or unit_name or '요약문 단원',
                    'grade': grade,
                    'is_active': True,
                },
            )
            created_units.append(unit_obj)
            SummaryProblem.objects.filter(unit=unit_obj).delete()
            rows = []
            for it in group:
                try:
                    idx = int(it.get('idx'))
                except (TypeError, ValueError):
                    idx = len(rows) + 1
                rows.append(SummaryProblem(
                    unit=unit_obj,
                    index=idx,
                    sub_unit=str(it.get('sub_unit', '') or '').strip(),
                    sentence1_template=str(it.get('sentence1_template', '') or ''),
                    sentence1_answer=str(it.get('sentence1_answer', '') or '').strip(),
                    korean1=str(it.get('korean1', '') or '').strip(),
                    sentence2_template=str(it.get('sentence2_template', '') or ''),
                    sentence2_answer=str(it.get('sentence2_answer', '') or '').strip(),
                    korean2=str(it.get('korean2', '') or '').strip(),
                ))
            SummaryProblem.objects.bulk_create(rows)
            created_total += len(rows)
            results.append({'unit_id': unit_obj.id, 'unit': unit_name, 'created': len(rows)})

    # 학생 배정 — 단일(assign_to/assign_login_id) + 다수(assign_to_list)
    assigned = None
    assigned_many = None
    if assign_to or assign_login_id:
        student, why = _find_student_for_assign(assign_to, assign_login_id)
        if student is None:
            assigned = {'ok': False, 'reason': why, 'name': assign_to or assign_login_id}
        else:
            n = 0
            for u in created_units:
                _, made = SummaryAssignment.objects.get_or_create(student=student, unit=u)
                if made:
                    n += 1
            assigned = {'ok': True, 'student': student.username, 'units': len(created_units), 'newly': n}

    if assign_to_list:
        ok_names, fail = [], []
        for nm in assign_to_list:
            student, why = _find_student_for_assign(nm, '')
            if student is None:
                fail.append({'name': nm, 'reason': why})
                continue
            for u in created_units:
                SummaryAssignment.objects.get_or_create(student=student, unit=u)
            ok_names.append(student.username)
        assigned_many = {'assigned': ok_names, 'failed': fail, 'units': len(created_units)}

    return JsonResponse({
        'success': True,
        'school': school,
        'units': results,
        'created': created_total,
        'assigned': assigned,
        'assigned_many': assigned_many,
        'skipped': [], 'skipped_count': 0,
    }, json_dumps_params={'ensure_ascii': False})
