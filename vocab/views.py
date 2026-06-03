import json
import os

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET

# 동일 접근제어·헬퍼·학생 일괄등록 로직 재사용 (writing 미러)
from writing.views import (
    is_teacher, teacher_required,
    DEFAULT_STUDENT_PASSWORD, _xlsx_response, _style_header_row,
)
from writing.services.students_excel import parse_students_excel

from .models import (
    VocabUnit, VocabWord, VocabAssignment, StudentWordStar,
    VocabSession, VocabAttempt, VocabRangeTest,
)
from .services import grade_meaning, select_test_words


# ─────────────────────────────────────────────
# 학생 화면
# ─────────────────────────────────────────────

@login_required
def student_home(request):
    """단어훈련 학생 홈 — 배정된 단원 목록 (선생님은 전체)."""
    # 일반 학생인데 학원이 재원생으로 승인 안 했으면 안내
    if not is_teacher(request.user) and not getattr(request.user, 'is_approved', False):
        return render(request, 'vocab/student_pending.html', {})

    if is_teacher(request.user):
        units = list(VocabUnit.objects.filter(is_active=True).order_by('-created_at'))
        is_assigned_view = False
    else:
        assignments = (VocabAssignment.objects
                       .filter(student=request.user)
                       .select_related('unit'))
        units = [a.unit for a in assignments if a.unit.is_active]
        is_assigned_view = True

    unit_ids = [u.id for u in units]

    # 단원별 단어 수 일괄 조회 (N+1 방지)
    word_count_map = {
        row['unit_id']: row['c']
        for row in VocabWord.objects.filter(unit_id__in=unit_ids)
        .values('unit_id').annotate(c=Count('id'))
    }
    # 학생의 단원별 별표 개수 일괄 조회
    star_count_map = {
        row['word__unit_id']: row['c']
        for row in StudentWordStar.objects
        .filter(student=request.user, word__unit_id__in=unit_ids)
        .values('word__unit_id').annotate(c=Count('id'))
    }

    # 단원별 학생의 활성 시험범위(내신단어TEST) — 단원 카드 '테스트' 버튼이 시험을 띄움
    range_test_map = {}
    if is_assigned_view:
        for rt in (VocabRangeTest.objects
                   .filter(student=request.user, is_active=True, unit_id__in=unit_ids)
                   .order_by('unit_id', '-created_at')):
            range_test_map.setdefault(rt.unit_id, rt)  # 단원별 최신 1건

    unit_info = []
    for unit in units:
        unit._word_count = word_count_map.get(unit.id, 0)
        rt = range_test_map.get(unit.id)
        unit_info.append({
            'unit': unit,
            'word_count': word_count_map.get(unit.id, 0),
            'star_count': star_count_map.get(unit.id, 0),
            'range_test': rt,
        })

    return render(request, 'vocab/home.html', {
        'unit_info': unit_info,
        'is_assigned_view': is_assigned_view,
    })


@login_required
def flashcard_view(request, unit_id):
    """플래시카드 학습 — 단어 ↔ 뜻 뒤집기 + 별표(서버 저장) 집중훈련."""
    unit = get_object_or_404(VocabUnit, pk=unit_id, is_active=True)
    if not is_teacher(request.user):
        if not VocabAssignment.objects.filter(student=request.user, unit=unit).exists():
            messages.error(request, '이 단원은 배정되지 않았습니다.')
            return redirect('vocab:home')

    words = list(unit.words.all().order_by('index'))
    starred_ids = set(
        StudentWordStar.objects
        .filter(student=request.user, word__unit=unit)
        .values_list('word_id', flat=True)
    )
    cards = [{
        'id': w.id,
        'index': w.index,
        'word': w.word,
        'meaning': w.meaning,
        'sub_unit': w.sub_unit,
        'starred': w.id in starred_ids,
    } for w in words]

    return render(request, 'vocab/flashcard.html', {
        'unit': unit,
        'cards_json': json.dumps(cards, ensure_ascii=False),
        'total': len(cards),
        'star_count': len(starred_ids),
    })


@login_required
@require_POST
def star_toggle_api(request):
    """별표 토글 — StudentWordStar 생성/삭제. body: {word_id, starred}."""
    try:
        data = json.loads(request.body or '{}')
        word_id = int(data['word_id'])
        want_starred = bool(data['starred'])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'error': '잘못된 요청'}, status=400)

    word = get_object_or_404(VocabWord, pk=word_id)

    # 배정 검증 (선생님은 통과)
    if not is_teacher(request.user):
        if not VocabAssignment.objects.filter(student=request.user, unit=word.unit).exists():
            return JsonResponse({'success': False, 'error': '권한 없음'}, status=403)

    if want_starred:
        StudentWordStar.objects.get_or_create(student=request.user, word=word)
    else:
        StudentWordStar.objects.filter(student=request.user, word=word).delete()

    return JsonResponse({'success': True, 'word_id': word_id, 'starred': want_starred})


# ─────────────────────────────────────────────
# 학생 화면 — 영→한 시험 (채점 공통: 정식 시험·연습 공용 answer/finish)
# ─────────────────────────────────────────────

@login_required
@require_POST
def test_answer_api(request):
    """단어 1개 채점 + 시도 기록 저장. 틀리면 자동 별표(모르는 단어).

    body: {session_id, word_id, input, time}
    return: {correct, correct_meaning, word}
    """
    try:
        data = json.loads(request.body or '{}')
        session_id = int(data['session_id'])
        word_id = int(data['word_id'])
        student_input = str(data.get('input', ''))
        time_taken = int(data.get('time', 0))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'error': '잘못된 요청'}, status=400)

    session = get_object_or_404(
        VocabSession, pk=session_id, student=request.user, finished_at__isnull=True,
    )
    word = get_object_or_404(VocabWord, pk=word_id, unit=session.unit)

    is_correct = grade_meaning(student_input, word.meaning)
    VocabAttempt.objects.update_or_create(
        session=session, word=word,
        defaults={
            'input_value': student_input[:200],
            'is_correct': is_correct,
            'time_taken_seconds': max(0, time_taken),
            'score_earned': 10 if is_correct else 0,
        },
    )

    # 정식 시험: 자동채점만 저장하고 정오는 숨김 (사람 검수 후 확정).
    if session.mode == VocabSession.MODE_TEST:
        return JsonResponse({'success': True, 'recorded': True})

    # 연습 모드: 틀린 단어 자동 별표 → 플래시카드 '별표만' 집중훈련으로 흐름 연결
    if not is_correct:
        StudentWordStar.objects.get_or_create(student=request.user, word=word)

    return JsonResponse({
        'success': True,
        'correct': is_correct,
        'correct_meaning': word.meaning,
        'word': word.word,
    }, json_dumps_params={'ensure_ascii': False})


@login_required
@require_POST
def test_finish_api(request):
    """세션 종료 + 집계. 오답 목록(정답 뜻 포함) 반환.

    body: {session_id}
    """
    try:
        data = json.loads(request.body or '{}')
        session_id = int(data['session_id'])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'error': '잘못된 요청'}, status=400)

    session = get_object_or_404(VocabSession, pk=session_id, student=request.user)
    attempts = list(
        session.attempts.select_related('word').order_by('word__index')
    )
    correct = sum(1 for a in attempts if a.is_correct)
    total = len(attempts)

    if not session.finished_at:
        session.finished_at = timezone.now()
        session.correct_count = correct
        session.total_count = total
        session.total_score = sum(a.score_earned for a in attempts)
        session.save(update_fields=[
            'finished_at', 'correct_count', 'total_count', 'total_score',
        ])

    percent = round(correct / total * 100) if total else 0

    # 정식 시험: 검수 대기. 정답/오답 상세는 검수 전까지 비공개.
    if session.mode == VocabSession.MODE_TEST:
        return JsonResponse({
            'success': True,
            'mode': 'test',
            'provisional_percent': percent,
            'total': total,
            'needs_review': not session.is_reviewed,
        })

    wrong = [
        {'word': a.word.word, 'meaning': a.word.meaning, 'input': a.input_value}
        for a in attempts if not a.is_correct
    ]
    return JsonResponse({
        'success': True,
        'correct': correct,
        'total': total,
        'percent': percent,
        'wrong': wrong,
    }, json_dumps_params={'ensure_ascii': False})


# ─────────────────────────────────────────────
# 학생 화면 — 개인별 시험 범위(내신단어TEST)
# ─────────────────────────────────────────────

@login_required
def range_test_take(request, range_test_id):
    """정식 시험 응시 화면 셸. 출제는 range_start API로 받아온다."""
    rt = get_object_or_404(
        VocabRangeTest.objects.select_related('unit'),
        pk=range_test_id, student=request.user, is_active=True,
    )
    return render(request, 'vocab/range_test.html', {'rt': rt})


@login_required
@require_POST
def range_test_start_api(request):
    """정식 시험 세션 생성 + 출제 단어(뜻 제외) 반환.

    body: {range_test_id}
    return: {session_id, words, time_limit_seconds, question_count}
    """
    try:
        data = json.loads(request.body or '{}')
        rt_id = int(data['range_test_id'])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'error': '잘못된 요청'}, status=400)

    rt = get_object_or_404(VocabRangeTest, pk=rt_id, student=request.user, is_active=True)
    words = select_test_words(
        request.user, rt.unit, rt.start_index, rt.end_index, count=rt.question_count,
    )
    if not words:
        return JsonResponse({'success': False, 'error': '출제할 단어가 없습니다.'}, status=400)

    session = VocabSession.objects.create(
        student=request.user, unit=rt.unit, mode=VocabSession.MODE_TEST,
        range_test=rt, total_count=len(words),
    )
    return JsonResponse({
        'success': True,
        'session_id': session.id,
        'time_limit_seconds': rt.time_limit_seconds,
        'question_count': len(words),
        'words': [
            {'id': w.id, 'index': w.index, 'word': w.word, 'sub_unit': w.sub_unit}
            for w in words
        ],
    }, json_dumps_params={'ensure_ascii': False})


@login_required
def range_flashcard_view(request, range_test_id):
    """시험 범위만 떼어 플래시카드(quizlet)로 훈련 — flashcard.html 재사용."""
    rt = get_object_or_404(
        VocabRangeTest, pk=range_test_id, is_active=True,
    )
    if not is_teacher(request.user) and rt.student_id != request.user.id:
        messages.error(request, '본인 시험 범위만 훈련할 수 있습니다.')
        return redirect('vocab:home')

    words = list(
        rt.unit.words.filter(index__gte=rt.start_index, index__lte=rt.end_index)
        .order_by('index')
    )
    # 별표는 항상 '범위 주인 학생' 기준 — 교사가 열면 그 학생이 어려워한 단어가 보인다.
    starred_ids = set(
        StudentWordStar.objects
        .filter(student=rt.student, word__in=words)
        .values_list('word_id', flat=True)
    )
    cards = [{
        'id': w.id, 'index': w.index, 'word': w.word, 'meaning': w.meaning,
        'sub_unit': w.sub_unit, 'starred': w.id in starred_ids,
    } for w in words]

    is_teacher_view = is_teacher(request.user) and rt.student_id != request.user.id
    return render(request, 'vocab/flashcard.html', {
        'unit': rt.unit,
        'range_title': f'{rt.source_label} {rt.start_index}~{rt.end_index}',
        'viewing_student': rt.student.username if is_teacher_view else '',
        'cards_json': json.dumps(cards, ensure_ascii=False),
        'total': len(cards),
        'star_count': len(starred_ids),
    })


# ─────────────────────────────────────────────
# 선생님 / 관리자 — 시험 검수
# ─────────────────────────────────────────────

@teacher_required
def review_list(request):
    """정식 시험 세션 목록 — 검수 대기/완료, 학생·범위·점수."""
    show = request.GET.get('show', 'pending')  # pending|all
    qs = (VocabSession.objects
          .filter(mode=VocabSession.MODE_TEST, finished_at__isnull=False)
          .select_related('student', 'unit', 'range_test')
          .order_by('-finished_at'))
    if show == 'pending':
        qs = qs.filter(is_reviewed=False)
    sessions = list(qs[:300])
    return render(request, 'vocab/review_list.html', {
        'sessions': sessions, 'show': show,
    })


@teacher_required
def review_detail(request, session_id):
    """시험 1건 검수 — 단어별 학생입력·자동 O/X, 뒤집기."""
    session = get_object_or_404(
        VocabSession.objects.select_related('student', 'unit', 'range_test'),
        pk=session_id, mode=VocabSession.MODE_TEST,
    )
    attempts = list(session.attempts.select_related('word').order_by('word__index'))
    return render(request, 'vocab/review_detail.html', {
        'session': session, 'attempts': attempts,
    })


@teacher_required
@require_POST
def review_update_api(request, session_id):
    """검수 반영 — 단어별 정오 뒤집기 + 점수 재계산 + 검수 완료.

    body: {flips: {attempt_id: bool}, finalize: bool}
    """
    session = get_object_or_404(VocabSession, pk=session_id, mode=VocabSession.MODE_TEST)
    try:
        data = json.loads(request.body or '{}')
        flips = data.get('flips') or {}
        finalize = bool(data.get('finalize'))
    except (json.JSONDecodeError, TypeError):
        return HttpResponseBadRequest('Invalid')

    attempts = {a.id: a for a in session.attempts.select_related('word')}
    changed = []
    for aid_str, val in flips.items():
        try:
            a = attempts.get(int(aid_str))
        except (ValueError, TypeError):
            continue
        if a is None:
            continue
        new_correct = bool(val)
        if a.is_correct != new_correct:
            a.is_correct = new_correct
            a.score_earned = 10 if new_correct else 0
            changed.append(a)
    if changed:
        VocabAttempt.objects.bulk_update(changed, ['is_correct', 'score_earned'])

    # 재계산
    all_attempts = list(session.attempts.all())
    session.correct_count = sum(1 for a in all_attempts if a.is_correct)
    session.total_count = len(all_attempts)
    session.total_score = sum(a.score_earned for a in all_attempts)
    fields = ['correct_count', 'total_count', 'total_score']
    if finalize:
        session.is_reviewed = True
        session.reviewed_at = timezone.now()
        session.reviewed_by = request.user
        fields += ['is_reviewed', 'reviewed_at', 'reviewed_by']
        # 검수 확정 시: 틀린 단어 자동 별표 (후속 훈련 연결)
        wrong_word_ids = [a.word_id for a in all_attempts if not a.is_correct]
        for wid in wrong_word_ids:
            StudentWordStar.objects.get_or_create(student=session.student, word_id=wid)
    session.save(update_fields=fields)

    return JsonResponse({
        'success': True,
        'correct': session.correct_count,
        'total': session.total_count,
        'percent': session.percent,
        'passed': session.passed,
        'is_reviewed': session.is_reviewed,
    })


@teacher_required
@require_POST
def range_threshold_api(request):
    """시험 범위의 합격 기준 점수 개인별 조정. body: {range_test_id, pass_threshold}."""
    try:
        data = json.loads(request.body or '{}')
        rt_id = int(data['range_test_id'])
        threshold = int(data['pass_threshold'])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'error': '잘못된 요청'}, status=400)
    threshold = max(0, min(100, threshold))
    rt = get_object_or_404(VocabRangeTest, pk=rt_id)
    rt.pass_threshold = threshold
    rt.save(update_fields=['pass_threshold'])
    return JsonResponse({'success': True, 'pass_threshold': threshold})


# ─────────────────────────────────────────────
# 선생님 / 관리자 — 단어 단원 관리
# ─────────────────────────────────────────────

@teacher_required
def unit_list(request):
    """단어 단원 목록 — 단어 수 · 배정 학생 수."""
    units = list(VocabUnit.objects.select_related('created_by').order_by('school', 'title'))
    unit_ids = [u.id for u in units]
    word_counts = dict(
        VocabWord.objects.filter(unit_id__in=unit_ids)
        .values('unit_id').annotate(c=Count('id')).values_list('unit_id', 'c')
    )
    assign_counts = dict(
        VocabAssignment.objects.filter(unit_id__in=unit_ids)
        .values('unit_id').annotate(c=Count('id')).values_list('unit_id', 'c')
    )
    for u in units:
        u._word_count = word_counts.get(u.id, 0)
        u.assigned_count = assign_counts.get(u.id, 0)
    return render(request, 'vocab/unit_list.html', {'units': units})


@teacher_required
@require_POST
def unit_delete(request):
    """체크한 단원들을 cascade(단어·배정·세션) 함께 삭제."""
    try:
        ids = [int(x) for x in request.POST.getlist('unit_ids') if x]
    except ValueError:
        ids = []
    if not ids:
        messages.warning(request, '삭제할 단원을 선택해주세요.')
        return redirect('vocab:unit_list')
    qs = VocabUnit.objects.filter(pk__in=ids)
    count = qs.count()
    qs.delete()
    messages.success(request, f'단원 {count}개 삭제 완료.')
    return redirect('vocab:unit_list')


@teacher_required
@require_GET
def assignment_list(request, unit_id):
    """단원 1개의 배정 현황 + 전체 학생 — 단원별 배정 모달용."""
    unit = get_object_or_404(VocabUnit, pk=unit_id)
    User = get_user_model()
    assigned_ids = set(
        VocabAssignment.objects.filter(unit=unit).values_list('student_id', flat=True)
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
    unit = get_object_or_404(VocabUnit, pk=unit_id)
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
        VocabAssignment.objects.filter(unit=unit).values_list('student_id', flat=True)
    )
    to_add = valid_ids - current_ids
    to_remove = current_ids - valid_ids
    if to_add:
        VocabAssignment.objects.bulk_create([
            VocabAssignment(student_id=sid, unit=unit, assigned_by=request.user)
            for sid in to_add
        ], ignore_conflicts=True)
    if to_remove:
        VocabAssignment.objects.filter(unit=unit, student_id__in=to_remove).delete()
    return JsonResponse({
        'success': True,
        'assigned_count': VocabAssignment.objects.filter(unit=unit).count(),
        'added': len(to_add), 'removed': len(to_remove),
    })


# ─────────────────────────────────────────────
# 선생님 / 관리자 — 학생 관리 + 배정
# ─────────────────────────────────────────────

@teacher_required
def student_admin(request):
    """단어훈련 학생 관리 — 전체 학생 + 단어 단원 배정 수."""
    User = get_user_model()
    qs = User.objects.exclude(is_staff=True).exclude(is_superuser=True).order_by('login_id', '-date_joined')
    students = []
    sid_list = []
    for s in qs:
        if is_teacher(s):
            continue
        students.append(s)
        sid_list.append(s.id)
    assign_counts = dict(
        VocabAssignment.objects.filter(student_id__in=sid_list)
        .values('student_id').annotate(c=Count('id')).values_list('student_id', 'c')
    )
    # 학생별 활성 시험범위(내신단어TEST) — 교사가 플래시카드로 직접 보며 점검
    range_map = {}
    for rt in (VocabRangeTest.objects
               .filter(student_id__in=sid_list, is_active=True)
               .select_related('unit').order_by('student_id', '-created_at')):
        range_map.setdefault(rt.student_id, []).append({
            'id': rt.id,
            'label': f'{rt.source_label} {rt.start_index}~{rt.end_index}',
            'school': rt.unit.school,
        })
    for s in students:
        s.vocab_assigned_count = assign_counts.get(s.id, 0)
        s.range_tests = range_map.get(s.id, [])
    return render(request, 'vocab/student_list.html', {
        'students': students,
        'default_password': DEFAULT_STUDENT_PASSWORD,
    })


@teacher_required
def student_upload(request):
    """엑셀로 학생 일괄 등록 (writing과 동일 계정 풀). 컬럼: 1열 색인 · 2열 ID · 3열 이름."""
    if request.method != 'POST':
        return render(request, 'vocab/student_upload.html', {'default_password': DEFAULT_STUDENT_PASSWORD})

    f = request.FILES.get('excel_file')
    if not f:
        messages.error(request, '엑셀 파일을 선택해주세요.')
        return render(request, 'vocab/student_upload.html', {'default_password': DEFAULT_STUDENT_PASSWORD})
    if not f.name.lower().endswith(('.xlsx', '.xls')):
        messages.error(request, 'xlsx 또는 xls 파일만 가능합니다.')
        return render(request, 'vocab/student_upload.html', {'default_password': DEFAULT_STUDENT_PASSWORD})

    result = parse_students_excel(f)
    if not result['success']:
        for err in result['errors']:
            messages.error(request, err)
        return render(request, 'vocab/student_upload.html', {'default_password': DEFAULT_STUDENT_PASSWORD})

    User = get_user_model()
    created = 0
    skipped = []
    for s in result['students']:
        login_id, name = s['login_id'], s['name']
        if User.objects.filter(login_id=login_id).exists():
            skipped.append(login_id)
            continue
        try:
            user = User(
                login_id=login_id, username=name, email=None,
                member_type='user', is_active=True, is_approved=True, is_academy=False,
            )
            user.set_password(DEFAULT_STUDENT_PASSWORD)
            user.save()
            created += 1
        except Exception as e:
            skipped.append(f'{login_id} ({e})')

    parts = [f'{created}명 등록 완료', f'기본 비번: {DEFAULT_STUDENT_PASSWORD}']
    if skipped:
        sample = ', '.join(skipped[:5])
        more = '…' if len(skipped) > 5 else ''
        parts.append(f'중복/실패 {len(skipped)}건 skip ({sample}{more})')
    messages.success(request, ' · '.join(parts))
    return redirect('vocab:student_admin')


@teacher_required
def student_template_xlsx(request):
    """학생 일괄 등록용 빈 양식. 1열 색인 · 2열 ID · 3열 이름."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '학생 명단'
    ws.append(['색인', 'ID', '이름'])
    ws.append([1, 'primeedu100', '홍길동'])
    ws.append([2, 'primeedu101', '김철수'])
    ws.column_dimensions['A'].width = 8
    ws.column_dimensions['B'].width = 20
    ws.column_dimensions['C'].width = 18
    _style_header_row(ws)
    return _xlsx_response(wb, 'vocab_students_template.xlsx')


@teacher_required
@require_POST
def student_action(request):
    """학생 일괄 액션 — approve|unapprove|activate|deactivate|delete."""
    try:
        ids = [int(x) for x in request.POST.getlist('student_ids') if x]
    except ValueError:
        ids = []
    action = request.POST.get('action')
    if not ids or action not in ('approve', 'unapprove', 'activate', 'deactivate', 'delete'):
        messages.warning(request, '학생과 액션을 선택해주세요.')
        return redirect('vocab:student_admin')

    User = get_user_model()
    qs = User.objects.filter(pk__in=ids).exclude(is_staff=True).exclude(is_superuser=True)
    if action == 'approve':
        n = qs.update(is_approved=True); messages.success(request, f'{n}명 재원생 승인 완료.')
    elif action == 'unapprove':
        n = qs.update(is_approved=False); messages.success(request, f'{n}명 재원생 승인 취소.')
    elif action == 'activate':
        n = qs.update(is_active=True); messages.success(request, f'{n}명 계정 활성화.')
    elif action == 'deactivate':
        n = qs.update(is_active=False); messages.success(request, f'{n}명 계정 비활성화.')
    elif action == 'delete':
        n = qs.count(); qs.delete()
        messages.success(request, f'{n}명 삭제 완료. (단어 배정·기록도 함께 삭제)')
    return redirect('vocab:student_admin')


@teacher_required
@require_GET
def student_assignments(request, student_id):
    """학생 1명의 단어 단원 배정 현황 + 전체 단원 — 학생별 배정 모달용."""
    User = get_user_model()
    student = get_object_or_404(
        User.objects.exclude(is_staff=True).exclude(is_superuser=True), pk=student_id,
    )
    assigned_ids = set(
        VocabAssignment.objects.filter(student=student).values_list('unit_id', flat=True)
    )
    units = []
    for u in VocabUnit.objects.filter(is_active=True).order_by('school', 'title'):
        units.append({
            'id': u.id, 'title': u.title, 'school': u.school, 'grade': u.grade,
            'word_count': u.words.count(), 'is_assigned': u.id in assigned_ids,
        })
    return JsonResponse({
        'student': {
            'id': student.id, 'username': student.username,
            'login_id': getattr(student, 'login_id', '') or '',
        },
        'units': units, 'assigned_count': len(assigned_ids),
    }, json_dumps_params={'ensure_ascii': False})


@teacher_required
@require_POST
def student_assignments_update(request, student_id):
    """학생의 단어 단원 배정을 body.unit_ids 로 통째 갱신."""
    User = get_user_model()
    student = get_object_or_404(
        User.objects.exclude(is_staff=True).exclude(is_superuser=True), pk=student_id,
    )
    try:
        data = json.loads(request.body)
        target_ids = {int(x) for x in data.get('unit_ids', [])}
    except (json.JSONDecodeError, ValueError, TypeError):
        return HttpResponseBadRequest('Invalid')

    valid_ids = set(VocabUnit.objects.filter(pk__in=target_ids).values_list('id', flat=True))
    current_ids = set(
        VocabAssignment.objects.filter(student=student).values_list('unit_id', flat=True)
    )
    to_add = valid_ids - current_ids
    to_remove = current_ids - valid_ids
    if to_add:
        VocabAssignment.objects.bulk_create([
            VocabAssignment(student=student, unit_id=uid, assigned_by=request.user)
            for uid in to_add
        ], ignore_conflicts=True)
    if to_remove:
        VocabAssignment.objects.filter(student=student, unit_id__in=to_remove).delete()
    return JsonResponse({
        'success': True,
        'assigned_count': VocabAssignment.objects.filter(student=student).count(),
        'added': len(to_add), 'removed': len(to_remove),
    })


# ─────────────────────────────────────────────
# 외부(로컬 자동화 스크립트) 연동 — 토큰 인증 API
# 개별단어장생성.py 가 실행될 때 시험범위를 밀어넣고, 결과를 되읽어 N열에 기록.
# ─────────────────────────────────────────────

def _check_api_token(request):
    """공유 시크릿 토큰 검증. 헤더 X-Vocab-Token 또는 body/GET token."""
    from django.conf import settings
    expected = getattr(settings, 'VOCAB_IMPORT_TOKEN', '')
    if not expected:
        return False, '서버에 VOCAB_IMPORT_TOKEN 미설정'
    got = (request.headers.get('X-Vocab-Token')
           or request.GET.get('token') or '')
    if not got and request.body:
        try:
            got = (json.loads(request.body) or {}).get('token', '')
        except (json.JSONDecodeError, TypeError):
            got = ''
    if got != expected:
        return False, '토큰 불일치'
    return True, ''


def _find_student(User, name, login_id):
    """이름(username) 또는 login_id로 학생 1명 찾기. 모호하면 None + 사유."""
    base = User.objects.exclude(is_staff=True).exclude(is_superuser=True)
    if login_id:
        u = base.filter(login_id=login_id).first()
        if u:
            return u, ''
    if name:
        qs = list(base.filter(username=name)[:2])
        if len(qs) == 1:
            return qs[0], ''
        if len(qs) > 1:
            return None, f'동명이인 {len(qs)}명'
    return None, '학생 없음'


@csrf_exempt
@require_POST
def range_import_api(request):
    """시험범위 일괄 등록 (학생관리표 '내신단어TEST' 행).

    body: {token, items: [{name, login_id?, school, start, end,
                           source?, threshold?, question_count?, time_limit_seconds?}]}
    학생은 이름/ID로, 단원은 school(학교학년)로 매칭. 같은 (학생, source)의 기존 활성 범위는 비활성화.
    """
    ok, reason = _check_api_token(request)
    if not ok:
        return JsonResponse({'success': False, 'error': reason}, status=403)
    try:
        data = json.loads(request.body or '{}')
        items = data.get('items') or []
    except (json.JSONDecodeError, TypeError):
        return HttpResponseBadRequest('Invalid JSON')

    User = get_user_model()
    created, skipped = 0, []
    for it in items:
        name = str(it.get('name', '')).strip()
        login_id = str(it.get('login_id', '')).strip()
        school = str(it.get('school', '')).strip()
        source = str(it.get('source') or '내신단어TEST').strip()
        try:
            start = int(it['start']); end = int(it['end'])
        except (KeyError, ValueError, TypeError):
            skipped.append(f'{name or login_id}: 범위 숫자 오류')
            continue

        student, why = _find_student(User, name, login_id)
        if not student:
            skipped.append(f'{name or login_id}: {why}')
            continue

        unit = VocabUnit.objects.filter(school=school, is_active=True).first()
        if not unit:
            skipped.append(f'{name}: 단원 없음(학교={school})')
            continue

        # 배정도 보장 (학생 홈/접근권한)
        VocabAssignment.objects.get_or_create(student=student, unit=unit)

        # 같은 학생·source 기존 활성 범위 비활성화 후 새로 생성
        VocabRangeTest.objects.filter(
            student=student, source_label=source, is_active=True,
        ).update(is_active=False)
        rt = VocabRangeTest.objects.create(
            student=student, unit=unit, start_index=start, end_index=end,
            source_label=source,
            question_count=int(it.get('question_count', 40)),
            time_limit_seconds=int(it.get('time_limit_seconds', 1200)),
            pass_threshold=int(it.get('threshold', 90)),
        )
        created += 1
    return JsonResponse({
        'success': True, 'created': created,
        'skipped': skipped, 'skipped_count': len(skipped),
    }, json_dumps_params={'ensure_ascii': False})


@csrf_exempt
@require_GET
def range_results_api(request):
    """검수 완료된 최신 시험 결과 조회 (엑셀 N열 되쓰기용).

    GET ?token=...&source=내신단어TEST
    return: {results: [{name, login_id, school, source, start, end,
                        percent, passed, reviewed}]}  (활성 범위별 최신 시험)
    """
    ok, reason = _check_api_token(request)
    if not ok:
        return JsonResponse({'success': False, 'error': reason}, status=403)
    source = request.GET.get('source', '내신단어TEST')

    rts = (VocabRangeTest.objects
           .filter(is_active=True, source_label=source)
           .select_related('student', 'unit'))
    results = []
    for rt in rts:
        sess = (rt.sessions.filter(mode=VocabSession.MODE_TEST, finished_at__isnull=False)
                .order_by('-finished_at').first())
        results.append({
            'name': rt.student.username,
            'login_id': getattr(rt.student, 'login_id', '') or '',
            'school': rt.unit.school,
            'source': rt.source_label,
            'start': rt.start_index, 'end': rt.end_index,
            'percent': sess.percent if sess else None,
            'passed': sess.passed if sess else None,
            'reviewed': sess.is_reviewed if sess else False,
            'tested_at': sess.finished_at.strftime('%Y-%m-%d %H:%M') if sess else None,
        })
    return JsonResponse({'success': True, 'results': results},
                        json_dumps_params={'ensure_ascii': False})
