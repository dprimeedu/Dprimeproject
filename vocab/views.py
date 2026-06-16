import json
import os

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Case, When, IntegerField, Value, Max
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

from django.urls import reverse

from .models import (
    VocabUnit, VocabWord, VocabAssignment, StudentWordStar,
    VocabSession, VocabAttempt, VocabRangeTest,
    WordCardSet, WordCard, WordCardStar, DictionaryCache, DictionaryEntry,
)
from member.auto_assign import auto_assign_unit
from .services import (
    grade_meaning, select_test_words,
    ensure_quizlet_ranges, remove_quizlet_ranges,
    split_range_into_chunks,
)


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
    quizlet_map = {}
    if is_assigned_view:
        for rt in (VocabRangeTest.objects
                   .filter(student=request.user, is_active=True, unit_id__in=unit_ids)
                   .order_by('unit_id', '-created_at', 'start_index')):
            if rt.source_label.startswith('퀴즈렛'):
                quizlet_map.setdefault(rt.unit_id, []).append(rt)
            else:
                range_test_map.setdefault(rt.unit_id, rt)  # 단원별 최신 1건
        # 퀴즈렛 범위는 start_index 순으로 정렬
        for uid in quizlet_map:
            quizlet_map[uid].sort(key=lambda r: r.start_index)

    unit_info = []
    for unit in units:
        unit._word_count = word_count_map.get(unit.id, 0)
        rt = range_test_map.get(unit.id)
        unit_info.append({
            'unit': unit,
            'word_count': word_count_map.get(unit.id, 0),
            'star_count': star_count_map.get(unit.id, 0),
            'range_test': rt,
            'quizlet_ranges': quizlet_map.get(unit.id, []),
        })

    # 별표 모음 카드용 전체 개수 — 단원 별표 + 낱말카드 별표 합산
    total_star_count = (
        StudentWordStar.objects.filter(student=request.user).count()
        + WordCardStar.objects.filter(student=request.user).count())

    return render(request, 'vocab/home.html', {
        'unit_info': unit_info,
        'is_assigned_view': is_assigned_view,
        'total_star_count': total_star_count,
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
        'default_star_only': False,
        'default_shuffle': False,
        'star_enabled': True,
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


@login_required
@require_POST
def wordcard_star_toggle_api(request):
    """낱말카드 별표 토글 — WordCardStar 생성/삭제. body: {word_id, starred}."""
    try:
        data = json.loads(request.body or '{}')
        card_id = int(data['word_id'])
        want_starred = bool(data['starred'])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'error': '잘못된 요청'}, status=400)

    card = get_object_or_404(WordCard, pk=card_id, card_set__student=request.user)

    if want_starred:
        WordCardStar.objects.get_or_create(student=request.user, card=card)
    else:
        WordCardStar.objects.filter(student=request.user, card=card).delete()

    return JsonResponse({'success': True, 'word_id': card_id, 'starred': want_starred})


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
        # 번호 세트 = 플래시카드 시험: 카드섞기 + 별표만(별표 있을 때) 기본
        'default_star_only': len(starred_ids) > 0,
        'default_shuffle': True,
        'star_enabled': True,
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
def test_today(request):
    """오늘 단어 TEST — 활성 '내신단어TEST' 범위가 있는 학생만 모아 보여줌.

    학생관리자료의 '내신단어TEST' 가 동기화될 때마다 range_import_api 가 같은 (학생,
    source) 의 기존 활성 범위를 비활성화하고 새로 만든다. 따라서 '활성 내신단어TEST 범위'
    = '그날 봐야 할 시험'. 전체 배정/퀴즈렛 세트가 섞인 student_admin 과 달리 시험 볼 것만.
    """
    # 학생관리표 행 순서(sort_order)대로 — 미지정(0)은 뒤로, 같은 행 안은 시작번호순.
    rts = (VocabRangeTest.objects
           .filter(is_active=True, source_label='내신단어TEST')
           .select_related('student', 'unit')
           .annotate(_unset=Case(When(sort_order=0, then=Value(1)), default=Value(0),
                                 output_field=IntegerField()))
           .order_by('_unset', 'sort_order', 'student__username', 'start_index'))
    rows = []
    for rt in rts:
        sess = (rt.sessions
                .filter(mode=VocabSession.MODE_TEST, finished_at__isnull=False)
                .order_by('-finished_at').first())
        rows.append({
            'range_id': rt.id,
            'student_id': rt.student_id,
            'name': rt.student.username,
            'login_id': getattr(rt.student, 'login_id', '') or '',
            'school': rt.unit.school,
            'label': rt.source_label,
            'start': rt.start_index,
            'end': rt.end_index,
            'count': rt.end_index - rt.start_index + 1,
            'question_count': rt.question_count,
            'percent': sess.percent if sess else None,
            'passed': sess.passed if sess else None,
            'reviewed': sess.is_reviewed if sess else False,
            'tested_at': sess.finished_at.strftime('%m/%d %H:%M') if sess else None,
        })
    return render(request, 'vocab/test_today.html', {
        'rows': rows,
        'total': len(rows),
    })


# ─────────────────────────────────────────────
# 선생님 — 오늘 단어 TEST: 학생별 플래시카드 시험
#   영한 주관식 시험 폐지 → 전부 '플래시카드로 직접 시험'.
#   오늘 시험범위 / 배정 전체 범위 / 개인 단어 / 별표 모음 모두 플래시카드로.
# ─────────────────────────────────────────────

@teacher_required
def student_ranges(request, student_id):
    """[교사] 한 학생에게 배정된 모든 시험 범위(내신단어TEST·퀴즈렛 등).

    오늘 시험범위(예: 201~300)와 학생이 실제로 외워온 범위(예: 101~200)가 다를 때,
    여기서 학생이 외워온 범위를 골라 플래시카드로 바로 시험을 본다.
    """
    student = get_object_or_404(get_user_model(), pk=student_id)
    rts = (VocabRangeTest.objects
           .filter(student=student, is_active=True)
           .select_related('unit')
           .order_by('unit__title', 'start_index'))
    units = []
    cur = None
    for rt in rts:
        if cur is None or cur['unit'].id != rt.unit_id:
            cur = {'unit': rt.unit, 'ranges': []}
            units.append(cur)
        cur['ranges'].append(rt)
    return render(request, 'vocab/student_ranges.html', {
        'student': student, 'units': units,
    })


@teacher_required
def student_cards(request, student_id):
    """[교사] 한 학생이 개인적으로 모은 낱말카드 세트 → 플래시카드로 시험."""
    student = get_object_or_404(get_user_model(), pk=student_id)
    sets = (WordCardSet.objects
            .filter(student=student, status=WordCardSet.STATUS_PUBLISHED)
            .annotate(card_total=Count('cards'))
            .order_by('-updated_at'))
    return render(request, 'vocab/student_cards.html', {
        'student': student, 'sets': sets,
    })


@teacher_required
def student_cardset_flashcard(request, set_id):
    """[교사] 학생 개인 낱말카드 세트를 플래시카드로 시험 — flashcard.html 재사용."""
    s = get_object_or_404(WordCardSet, pk=set_id)
    word_cards = list(s.cards.exclude(word='').exclude(meaning='').order_by('index'))
    starred_ids = set(
        WordCardStar.objects.filter(student=s.student, card__in=word_cards)
        .values_list('card_id', flat=True)
    )
    cards = [
        {'id': c.id, 'index': c.index, 'word': c.word, 'meaning': c.meaning,
         'sub_unit': '', 'starred': c.id in starred_ids, 'card_type': 'wordcard'}
        for c in word_cards
    ]
    return render(request, 'vocab/flashcard.html', {
        'unit': s,
        'range_title': s.title,
        'viewing_student': s.student.username,
        'cards_json': json.dumps(cards, ensure_ascii=False),
        'total': len(cards),
        'star_count': len(starred_ids),
        'default_star_only': False,
        'default_shuffle': False,
        'star_enabled': False,  # 교사 점검용 — 별표는 학생 것만 표시(토글 X)
        'back_url': reverse('vocab:student_cards', args=[s.student_id]),
        'back_label': '개인 단어',
    })


@teacher_required
def student_star_flashcard(request, student_id):
    """[교사] 한 학생이 별표(모르는 단어)한 것만 모아 플래시카드로 시험."""
    student = get_object_or_404(get_user_model(), pk=student_id)
    vocab_stars = (StudentWordStar.objects
                   .filter(student=student).select_related('word')
                   .order_by('word__unit_id', 'word__index'))
    wc_stars = (WordCardStar.objects
                .filter(student=student).select_related('card')
                .order_by('card__card_set_id', 'card__index'))
    cards = []
    for st in vocab_stars:
        cards.append({
            'id': st.word.id, 'index': st.word.index,
            'word': st.word.word, 'meaning': st.word.meaning,
            'sub_unit': st.word.sub_unit or '', 'starred': True, 'card_type': 'vocab',
        })
    for st in wc_stars:
        cards.append({
            'id': st.card.id, 'index': st.card.index,
            'word': st.card.word, 'meaning': st.card.meaning,
            'sub_unit': '', 'starred': True, 'card_type': 'wordcard',
        })
    return render(request, 'vocab/flashcard.html', {
        'unit': None,
        'range_title': f'⭐ {student.username} 별표 모음',
        'viewing_student': student.username,
        'cards_json': json.dumps(cards, ensure_ascii=False),
        'total': len(cards),
        'star_count': len(cards),
        'default_star_only': False,
        'default_shuffle': True,
        'star_enabled': False,  # 교사 점검용 — 토글 비활성
        'back_url': reverse('vocab:test_today'),
        'back_label': '오늘 단어 TEST',
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
    updated_sg = 0
    skipped = []
    for s in result['students']:
        login_id, name = s['login_id'], s['name']
        school, grade = s.get('school', ''), s.get('grade', '')
        existing = User.objects.filter(login_id=login_id).first()
        if existing:
            if (school or grade) and (existing.school != school or existing.grade != grade):
                existing.school = school
                existing.grade = grade
                existing.save(update_fields=['school', 'grade'])
                updated_sg += 1
            skipped.append(login_id)
            continue
        try:
            user = User(
                login_id=login_id, username=name, email=None,
                member_type='user', is_active=True, is_approved=True, is_academy=False,
                school=school, grade=grade,
            )
            user.set_password(DEFAULT_STUDENT_PASSWORD)
            user.save()
            created += 1
        except Exception as e:
            skipped.append(f'{login_id} ({e})')

    parts = [f'{created}명 등록 완료', f'기본 비번: {DEFAULT_STUDENT_PASSWORD}']
    if updated_sg:
        parts.append(f'기존 학생 학교·학년 {updated_sg}명 갱신')
    if skipped:
        sample = ', '.join(skipped[:5])
        more = '…' if len(skipped) > 5 else ''
        parts.append(f'중복/실패 {len(skipped)}건 skip ({sample}{more})')
    messages.success(request, ' · '.join(parts))
    return redirect('vocab:student_admin')


@teacher_required
def student_template_xlsx(request):
    """학생 일괄 등록용 빈 양식. 1열 색인 · 2열 ID · 3열 이름 · 4열 학교학년(선택)."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '학생 명단'
    ws.append(['색인', 'ID', '이름', '학교학년'])
    ws.append([1, 'primeedu100', '홍길동', '동백중2'])
    ws.append([2, 'primeedu101', '김철수', '백현고1'])
    ws.column_dimensions['A'].width = 8
    ws.column_dimensions['B'].width = 20
    ws.column_dimensions['C'].width = 18
    ws.column_dimensions['D'].width = 14
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
    for u in (VocabUnit.objects.filter(is_active=True)
              .annotate(wc=Count('words')).order_by('category', 'school', 'title')):
        wc = u.wc
        units.append({
            'id': u.id, 'title': u.title, 'school': u.school, 'grade': u.grade,
            'category': u.category,
            'word_count': wc, 'is_assigned': u.id in assigned_ids,
            # 교재 단어장이면 100단어 세트 수 미리보기
            'set_count': ((wc + 99) // 100) if u.category == VocabUnit.CATEGORY_WORDBOOK else 0,
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

    # 교재 단어장(category='wordbook')은 배정 시 100단어 퀴즈렛 세트 자동 생성 / 해제 시 제거
    qz_sets = 0
    touched = to_add | to_remove
    if touched:
        wb_units = {
            u.id: u for u in VocabUnit.objects.filter(
                pk__in=touched, category=VocabUnit.CATEGORY_WORDBOOK)
        }
        for uid in to_add:
            u = wb_units.get(uid)
            if u:
                qz_sets += ensure_quizlet_ranges(student, u, assigned_by=request.user)
        for uid in to_remove:
            u = wb_units.get(uid)
            if u:
                remove_quizlet_ranges(student, u)

    return JsonResponse({
        'success': True,
        'assigned_count': VocabAssignment.objects.filter(student=student).count(),
        'added': len(to_add), 'removed': len(to_remove),
        'quizlet_sets_created': qz_sets,
    })


# ─────────────────────────────────────────────
# 외부(로컬 자동화 스크립트) 연동 — 토큰 인증 API
# 개별단어장생성.py 가 실행될 때 시험범위를 밀어넣고, 결과를 되읽어 N열에 기록.
# ─────────────────────────────────────────────

def _check_api_token(request):
    """공유 시크릿 토큰 검증. 헤더 X-Vocab-Token 또는 body/GET token."""
    expected = 'pedu-vocab-2026'
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
def words_import_api(request):
    """내신단어 일괄 등록 (부교재 출력 → 마스터 '내신단어' 시트 푸시).

    body: {token, school, exam?, assign_to?, assign_login_id?, assign_to_list?,
           items: [{idx, word, meaning, unit?, source?}]}
    (school, exam) 단위로 category=naesin VocabUnit upsert + 기존 VocabWord 교체(replace).
    단어 import HTTP API (기존 import_wordbooks 커맨드의 HTTP 버전). assign_* 로 학생 배정.
    """
    import re as _re
    from django.db import transaction as _tx
    ok, reason = _check_api_token(request)
    if not ok:
        return JsonResponse({'success': False, 'error': reason}, status=403)
    try:
        data = json.loads(request.body or '{}')
        items = data.get('items') or []
        school = str(data.get('school', '')).strip()
        exam = str(data.get('exam', '')).strip()
        assign_to = str(data.get('assign_to', '') or '').strip()
        assign_login_id = str(data.get('assign_login_id', '') or '').strip()
        assign_to_list = [str(x).strip() for x in (data.get('assign_to_list') or []) if str(x).strip()]
        mode = str(data.get('mode', 'replace') or 'replace').strip().lower()   # 'replace' | 'merge'
    except (json.JSONDecodeError, TypeError):
        return HttpResponseBadRequest('Invalid JSON')
    if not items:
        return JsonResponse({'success': False, 'error': 'items 비어있음'}, status=400)

    m = _re.search(r'(고|중|초)\s*([1-3])', school or '')
    grade = (m.group(1) + m.group(2)) if (m and (m.group(1) + m.group(2)) in
             {c[0] for c in VocabUnit.GRADE_CHOICES}) else '기타'
    title = (f'{school} {exam}').strip() or school or exam or '내신 단어'

    with _tx.atomic():
        unit = VocabUnit.objects.filter(
            school=school, exam=exam, category=VocabUnit.CATEGORY_NAESIN).first()
        if unit is None:
            unit = VocabUnit.objects.create(
                school=school, exam=exam, category=VocabUnit.CATEGORY_NAESIN,
                title=title, grade=grade, is_active=True)
        else:
            unit.title = title
            unit.grade = grade
            unit.is_active = True
            unit.save(update_fields=['title', 'grade', 'is_active', 'updated_at'])
        # 입력 파싱(번호 기준)
        parsed = []
        for it in items:
            w = str(it.get('word', '') or '').strip()
            if not w:
                continue
            try:
                idx = int(it.get('idx'))
            except (TypeError, ValueError):
                idx = len(parsed) + 1
            parsed.append({
                'index': idx, 'word': w,
                'meaning': str(it.get('meaning', '') or '').strip(),
                'sub_unit': str(it.get('unit', '') or '').strip(),
                'source': str(it.get('source', '') or '').strip(),
            })

        if mode == 'merge':
            # 통합 — 번호(index) 기준 upsert: 기존 갱신·신규 추가·나머지 보존
            existing = {x.index: x for x in VocabWord.objects.filter(unit=unit)}
            to_create, to_update = [], []
            for p in parsed:
                x = existing.get(p['index'])
                if x is None:
                    to_create.append(VocabWord(
                        unit=unit, index=p['index'], word=p['word'],
                        meaning=p['meaning'], sub_unit=p['sub_unit'], source=p['source']))
                else:
                    x.word, x.meaning, x.sub_unit, x.source = p['word'], p['meaning'], p['sub_unit'], p['source']
                    to_update.append(x)
            if to_create:
                VocabWord.objects.bulk_create(to_create)
            if to_update:
                VocabWord.objects.bulk_update(to_update, ['word', 'meaning', 'sub_unit', 'source'])
            created = len(to_create) + len(to_update)
        else:
            # 삭제 후 새로(replace) — 기존 전부 지우고 새로
            VocabWord.objects.filter(unit=unit).delete()
            VocabWord.objects.bulk_create([
                VocabWord(unit=unit, index=p['index'], word=p['word'], meaning=p['meaning'],
                          sub_unit=p['sub_unit'], source=p['source']) for p in parsed])
            created = len(parsed)

    User = get_user_model()
    assigned = assigned_many = None
    if assign_to or assign_login_id:
        student, why = _find_student(User, assign_to, assign_login_id)
        if student is None:
            assigned = {'ok': False, 'reason': why, 'name': assign_to or assign_login_id}
        else:
            _, made = VocabAssignment.objects.get_or_create(student=student, unit=unit)
            assigned = {'ok': True, 'student': student.username, 'newly': bool(made)}
    if assign_to_list:
        ok_names, fail = [], []
        for nm in assign_to_list:
            student, why = _find_student(User, nm, '')
            if student is None:
                fail.append({'name': nm, 'reason': why})
                continue
            VocabAssignment.objects.get_or_create(student=student, unit=unit)
            ok_names.append(student.username)
        assigned_many = {'assigned': ok_names, 'failed': fail}

    # 학교·학년 자동배정 (unit.school='청덕고3' 등 토큰 매칭 학생들에게)
    auto_assigned = auto_assign_unit(unit, unit.school, VocabAssignment)

    return JsonResponse({
        'success': True, 'school': school, 'exam': exam,
        'unit_id': unit.id, 'created': created,
        'assigned': assigned, 'assigned_many': assigned_many,
        'auto_assigned': auto_assigned,
    })


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

        # 같은 학생·source 기존 활성 범위 비활성화 후, 100단위로 쪼개 새로 생성
        # (예: 101~300 → 101~200 · 201~300 두 개의 시험으로 분리)
        VocabRangeTest.objects.filter(
            student=student, source_label=source, is_active=True,
        ).update(is_active=False)
        qc = int(it.get('question_count', 40))
        tl = int(it.get('time_limit_seconds', 1200))
        th = int(it.get('threshold', 90))
        try:
            row = int(it.get('row') or 0)   # 학생관리표 행 번호(시트 순서 보존)
        except (TypeError, ValueError):
            row = 0
        chunks = split_range_into_chunks(start, end)
        VocabRangeTest.objects.bulk_create([
            VocabRangeTest(
                student=student, unit=unit, start_index=cs, end_index=ce,
                source_label=source,
                question_count=min(qc, ce - cs + 1),
                time_limit_seconds=tl, pass_threshold=th, sort_order=row,
            )
            for cs, ce in chunks
        ])
        created += len(chunks)
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


@csrf_exempt
@require_GET
def unit_word_counts_api(request):
    """활성 단원별 학교·단어 수 조회 (퀴즈렛 배정 스크립트용).
    GET ?token=...
    return: {success, units: [{school, title, word_count}]}
    """
    ok, reason = _check_api_token(request)
    if not ok:
        return JsonResponse({'success': False, 'error': reason}, status=403)

    rows = (VocabUnit.objects
            .filter(is_active=True)
            .annotate(word_count=Count('words'))
            .values('school', 'title', 'word_count'))
    return JsonResponse({
        'success': True,
        'units': list(rows),
    }, json_dumps_params={'ensure_ascii': False})


# ─────────────────────────────────────────────
# 학생 화면 — 단어찾기 (낱말카드 만들기, 퀴즈렛식)
# ─────────────────────────────────────────────

def _student_gate(request):
    """재원생 승인 안 된 일반 학생은 안내 페이지. 통과면 None."""
    if not is_teacher(request.user) and not getattr(request.user, 'is_approved', False):
        return render(request, 'vocab/student_pending.html', {})
    return None


def lookup_meaning(word):
    """영→한 사전 조회. 반환: (meaning, source).

    순서: 전체 단어장 사전(DictionaryEntry) → 캐시 → 교재 단원 단어 → AI.
    """
    w = (word or '').strip()
    if not w:
        return '', ''
    key = w.lower()

    # 1) 전체 단어장 사전 (단어장 전체 모음 — 1순위)
    de = DictionaryEntry.objects.filter(key=key).first()
    if de:
        return de.meaning, 'book'

    # 2) 이전 조회 캐시 (AI 결과 등)
    cached = DictionaryCache.objects.filter(word=key).first()
    if cached:
        return cached.meaning, cached.source

    # 3) 교재 단원 단어 (대소문자 무시, 뜻 있는 것)
    vw = (VocabWord.objects
          .filter(word__iexact=w).exclude(meaning='')
          .order_by('id').first())
    if vw:
        meaning = vw.meaning.strip()
        DictionaryCache.objects.get_or_create(
            word=key, defaults={'meaning': meaning, 'source': DictionaryCache.SRC_DB})
        return meaning, DictionaryCache.SRC_DB

    # AI 폴백 (지연 import — genai 미설치 환경에서도 앞단계는 동작)
    try:
        from writing.services.ai import translate_word_en_ko
        meaning = translate_word_en_ko(w)
    except Exception as e:
        print(f'[dict] AI 조회 실패: {e}')
        meaning = ''
    if meaning:
        DictionaryCache.objects.get_or_create(
            word=key, defaults={'meaning': meaning, 'source': DictionaryCache.SRC_AI})
        return meaning, DictionaryCache.SRC_AI
    return '', ''


@login_required
def wordcard_list(request):
    """학생이 만든 낱말카드 세트 목록 (임시저장 포함) + 새로 만들기."""
    gate = _student_gate(request)
    if gate:
        return gate

    sets = list(
        WordCardSet.objects.filter(student=request.user)
        .annotate(card_total=Count('cards'))
        .order_by('-updated_at')
    )
    return render(request, 'vocab/wordcard_list.html', {'sets': sets})


@login_required
def star_menu(request):
    """별표 모음 메뉴 — 전체 별표 모음 / 오늘 별표 모음 선택."""
    gate = _student_gate(request)
    if gate:
        return gate

    # USE_TZ=False → now()는 Asia/Seoul 로컬 naive. created_at도 동일 기준.
    day_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    total_star_count = (
        StudentWordStar.objects.filter(student=request.user).count()
        + WordCardStar.objects.filter(student=request.user).count())
    today_star_count = (
        StudentWordStar.objects.filter(student=request.user, created_at__gte=day_start).count()
        + WordCardStar.objects.filter(student=request.user, created_at__gte=day_start).count())
    return render(request, 'vocab/star_menu.html', {
        'total_star_count': total_star_count,
        'today_star_count': today_star_count,
    })


@login_required
def star_flashcard(request, today=False):
    """별표 모음 플래시카드 — 단원 별표 + 낱말카드 별표 통합.
    today=True 면 오늘(로컬 자정 이후) 별표한 것만."""
    gate = _student_gate(request)
    if gate:
        return gate

    vocab_qs = (StudentWordStar.objects
                .filter(student=request.user)
                .select_related('word'))
    wc_qs = (WordCardStar.objects
             .filter(student=request.user)
             .select_related('card'))
    if today:
        # USE_TZ=False → now()는 Asia/Seoul 로컬 naive. created_at(auto_now_add)도 동일 기준.
        day_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        vocab_qs = vocab_qs.filter(created_at__gte=day_start)
        wc_qs = wc_qs.filter(created_at__gte=day_start)

    vocab_stars = vocab_qs.order_by('word__unit_id', 'word__index')
    wc_stars = wc_qs.order_by('card__card_set_id', 'card__index')

    cards = []
    for s in vocab_stars:
        cards.append({
            'id': s.word.id, 'index': s.word.index,
            'word': s.word.word, 'meaning': s.word.meaning,
            'sub_unit': s.word.sub_unit or '', 'starred': True,
            'card_type': 'vocab',
        })
    for s in wc_stars:
        cards.append({
            'id': s.card.id, 'index': s.card.index,
            'word': s.card.word, 'meaning': s.card.meaning,
            'sub_unit': '', 'starred': True,
            'card_type': 'wordcard',
        })

    return render(request, 'vocab/flashcard.html', {
        'unit': None,
        'range_title': '📅 오늘 별표 모음' if today else '⭐ 전체 별표 모음',
        'cards_json': json.dumps(cards, ensure_ascii=False),
        'total': len(cards),
        'star_count': len(cards),
        'default_star_only': False,
        'default_shuffle': True,
        'star_enabled': True,
        'wordcard_star_url': reverse('vocab:wordcard_star_toggle'),
        'back_url': reverse('vocab:star_menu'),
        'back_label': '별표 모음',
    })


@login_required
def wordcard_new(request):
    """새 낱말카드 세트(임시저장) 생성 → 편집기로. 번호는 이어서 연속 매김."""
    gate = _student_gate(request)
    if gate:
        return gate

    last = (WordCardSet.objects.filter(student=request.user)
            .order_by('-end_index').first())
    start = (last.end_index + 1) if last else 1
    count = 20
    s = WordCardSet.objects.create(
        student=request.user,
        title=f'{start}-{start + count - 1}',
        start_index=start,
        end_index=start + count - 1,
        status=WordCardSet.STATUS_DRAFT,
    )
    return redirect('vocab:wordcard_edit', set_id=s.id)


@login_required
def wordcard_edit(request, set_id):
    """낱말카드 편집기 — 단어 입력 시 영→한 사전으로 뜻 자동 채움."""
    gate = _student_gate(request)
    if gate:
        return gate

    s = get_object_or_404(WordCardSet, pk=set_id, student=request.user)
    cards = list(s.cards.all().order_by('index'))
    cards_json = json.dumps(
        [{'index': c.index, 'word': c.word, 'meaning': c.meaning} for c in cards],
        ensure_ascii=False,
    )
    return render(request, 'vocab/wordcard_edit.html', {
        'set': s,
        'cards_json': cards_json,
    })


@login_required
@require_POST
def wordcard_save_api(request):
    """편집기 저장 — 세트 메타 + 카드 전체 교체. status: draft(임시저장)/published(완성).

    body: {set_id, title, description, start_index, cards:[{word, meaning}], status}
    """
    try:
        data = json.loads(request.body or '{}')
        set_id = int(data['set_id'])
        raw_cards = data.get('cards', [])
        status = data.get('status', WordCardSet.STATUS_DRAFT)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'error': '잘못된 요청'}, status=400)

    if status not in (WordCardSet.STATUS_DRAFT, WordCardSet.STATUS_PUBLISHED):
        status = WordCardSet.STATUS_DRAFT

    s = get_object_or_404(WordCardSet, pk=set_id, student=request.user)

    # 카드 정리 (순번 1부터 다시 매김)
    cards = []
    for i, c in enumerate(raw_cards, start=1):
        word = str(c.get('word', '')).strip()[:200]
        meaning = str(c.get('meaning', '')).strip()
        cards.append({'index': i, 'word': word, 'meaning': meaning})

    # 완성(publish) 시 검증: 빈 카드 없어야 함
    if status == WordCardSet.STATUS_PUBLISHED:
        filled = [c for c in cards if c['word'] and c['meaning']]
        if not filled:
            return JsonResponse({'success': False, 'error': '단어가 하나도 없습니다.'}, status=400)
        empties = [c['index'] for c in cards if not (c['word'] and c['meaning'])]
        if empties:
            return JsonResponse({
                'success': False,
                'error': f'{len(empties)}개 카드가 비어 있습니다. 단어와 뜻을 모두 채워주세요.',
                'empty_indexes': empties,
            }, status=400)

    start = int(data.get('start_index') or s.start_index or 1)
    count = len(cards)
    end = start + count - 1 if count else start

    title = str(data.get('title', '')).strip()[:200] or f'{start}-{end}'
    s.title = title
    s.description = str(data.get('description', '')).strip()
    s.start_index = start
    s.end_index = end
    s.status = status
    s.save()

    # 카드 전체 교체 (단순·안전)
    s.cards.all().delete()
    WordCard.objects.bulk_create([
        WordCard(card_set=s, index=c['index'], word=c['word'], meaning=c['meaning'])
        for c in cards
    ])

    return JsonResponse({'success': True, 'set_id': s.id, 'status': s.status,
                         'title': s.title, 'start_index': start, 'end_index': end})


@login_required
@require_POST
def wordcard_delete(request, set_id):
    """낱말카드 세트 삭제."""
    s = get_object_or_404(WordCardSet, pk=set_id, student=request.user)
    s.delete()
    return redirect('vocab:wordcard_list')


@login_required
def wordcard_flashcard(request, set_id):
    """완성한 낱말카드 세트를 플래시카드로 학습 — 별표 활성."""
    gate = _student_gate(request)
    if gate:
        return gate

    s = get_object_or_404(WordCardSet, pk=set_id, student=request.user)
    word_cards = list(s.cards.exclude(word='').exclude(meaning='').order_by('index'))
    starred_ids = set(
        WordCardStar.objects.filter(student=request.user, card__in=word_cards)
        .values_list('card_id', flat=True)
    )
    cards = [
        {'id': c.id, 'index': c.index, 'word': c.word, 'meaning': c.meaning,
         'sub_unit': '', 'starred': c.id in starred_ids, 'card_type': 'wordcard'}
        for c in word_cards
    ]
    return render(request, 'vocab/flashcard.html', {
        'unit': s,
        'range_title': s.title,
        'cards_json': json.dumps(cards, ensure_ascii=False),
        'total': len(cards),
        'star_count': len(starred_ids),
        'default_star_only': False,
        'default_shuffle': False,
        'star_enabled': True,
        'wordcard_star_url': reverse('vocab:wordcard_star_toggle'),
        'back_url': reverse('vocab:wordcard_list'),
        'back_label': '낱말카드',
    })


@login_required
@require_POST
def dict_lookup_api(request):
    """영→한 사전 단건 조회. body: {word} → {success, meaning, source}."""
    try:
        data = json.loads(request.body or '{}')
        word = str(data.get('word', '')).strip()
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'error': '잘못된 요청'}, status=400)

    if not word:
        return JsonResponse({'success': True, 'meaning': '', 'source': ''})

    meaning, source = lookup_meaning(word)
    return JsonResponse({'success': True, 'meaning': meaning, 'source': source},
                        json_dumps_params={'ensure_ascii': False})


def lookup_mock_word(grade, year, month, number, word):
    """모의고사 회차·문항 한정 단어 뜻. 반환 (meaning, source).

    우선순위: MockVocab(그 지문 맥락) → 없으면 Gemini(+캐시). 다의어/지문 전용 명사 정확도용.
    구(phrase) 항목은 더블클릭한 단어를 첫 토큰/포함 토큰으로 매칭.
    """
    from .models import MockVocab
    w = ' '.join((word or '').split()).lower()
    if not w:
        return '', ''
    rows = list(MockVocab.objects
                .filter(grade=grade, year=year, month=month, number=number)
                .values_list('word_key', 'meaning'))
    # 1) 정확히 같은 단어
    for k, m in rows:
        if k == w:
            return m, 'mockdb'
    # 2) 구의 첫 토큰이 일치 (예: 'allow 사람 to v' ← 더블클릭 'allow')
    for k, m in rows:
        toks = k.split()
        if toks and toks[0] == w:
            return m, 'mockdb'
    # 3) 구 안의 아무 토큰이나 일치
    for k, m in rows:
        if w in k.split():
            return m, 'mockdb'

    # 4) Gemini 폴백 (회차 단어DB에 빠진 단어) — 단어 기준 캐시
    cached = DictionaryCache.objects.filter(word=w).first()
    if cached:
        return cached.meaning, cached.source
    try:
        from writing.services.ai import translate_word_en_ko
        meaning = translate_word_en_ko(word)
    except Exception as e:
        print(f'[mockvocab] Gemini 조회 실패: {e}')
        meaning = ''
    if meaning:
        DictionaryCache.objects.get_or_create(
            word=w, defaults={'meaning': meaning, 'source': DictionaryCache.SRC_AI})
        return meaning, DictionaryCache.SRC_AI
    return '', ''


# 지문에서 더블클릭으로 찾은 단어가 모이는 학생 개인 세트(자동)
FOUND_WORDS_SET_TITLE = '📖 지문에서 찾은 단어'


def _save_found_word(student, word, meaning):
    """더블클릭으로 찾은 단어를 학생 개인 '지문에서 찾은 단어' 낱말카드 세트에 추가.

    중복(대소문자 무시)이면 추가 안 함. 저장됐으면 True.
    """
    word = (word or '').strip()[:200]
    meaning = (meaning or '').strip()
    if not word or not meaning:
        return False
    s, _ = WordCardSet.objects.get_or_create(
        student=student, title=FOUND_WORDS_SET_TITLE,
        defaults={'status': WordCardSet.STATUS_PUBLISHED, 'start_index': 1, 'end_index': 0,
                  'description': '지문에서 더블클릭해 찾은 단어가 자동 저장됩니다.'},
    )
    if s.cards.filter(word__iexact=word).exists():
        return False
    nxt = (s.cards.aggregate(m=Max('index'))['m'] or 0) + 1
    WordCard.objects.create(card_set=s, index=nxt, word=word, meaning=meaning)
    if s.status != WordCardSet.STATUS_PUBLISHED or (s.end_index or 0) < nxt:
        s.status = WordCardSet.STATUS_PUBLISHED
        s.end_index = nxt
        s.save(update_fields=['status', 'end_index'])
    return True


@login_required
@require_POST
def lookup_save_api(request):
    """지문 단어 더블클릭 → 영→한 뜻 조회 + 학생 개인 낱말카드 자동 저장.

    body: {word, grade?, year?, month?, number?} → {success, meaning, source, saved, set_title}
    회차·문항(grade,year,month,number)이 오면 모의고사 회차 단어DB→Gemini 순으로(맥락 한정),
    없으면 전체 사전(lookup_meaning).
    """
    try:
        data = json.loads(request.body or '{}')
        word = str(data.get('word', '')).strip()
    except (ValueError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'error': '잘못된 요청'}, status=400)

    if not word:
        return JsonResponse({'success': True, 'meaning': '', 'source': '', 'saved': False})

    def _int(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0
    g, y, mo, n = _int(data.get('grade')), _int(data.get('year')), _int(data.get('month')), _int(data.get('number'))
    if g and y and mo and n:
        meaning, source = lookup_mock_word(g, y, mo, n, word)
    else:
        meaning, source = lookup_meaning(word)
    saved = _save_found_word(request.user, word, meaning) if meaning else False
    return JsonResponse({'success': True, 'word': word, 'meaning': meaning, 'source': source,
                         'saved': saved, 'set_title': FOUND_WORDS_SET_TITLE},
                        json_dumps_params={'ensure_ascii': False})
