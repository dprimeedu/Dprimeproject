import json
import random

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

# 동일 접근제어·헬퍼·학생 일괄등록 로직 재사용 (writing 미러)
from writing.views import (
    is_teacher, teacher_required,
    DEFAULT_STUDENT_PASSWORD, _xlsx_response, _style_header_row,
)
from writing.services.students_excel import parse_students_excel

from .models import (
    VocabUnit, VocabWord, VocabAssignment, StudentWordStar,
    VocabSession, VocabAttempt,
)
from .services import grade_meaning


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

    unit_info = []
    for unit in units:
        unit._word_count = word_count_map.get(unit.id, 0)
        unit_info.append({
            'unit': unit,
            'word_count': word_count_map.get(unit.id, 0),
            'star_count': star_count_map.get(unit.id, 0),
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
# 학생 화면 — 영→한 주관식 테스트
# ─────────────────────────────────────────────

def _can_access_unit(user, unit):
    """선생님은 전체, 학생은 배정된 단원만."""
    if is_teacher(user):
        return True
    return VocabAssignment.objects.filter(student=user, unit=unit).exists()


@login_required
def test_view(request, unit_id):
    """영→한 테스트 화면 셸. 실제 출제 단어는 test_start API로 받아온다.

    뜻(정답)은 서버에서만 채점하고 클라이언트로 내려보내지 않는다 (답 훔쳐보기 차단).
    """
    unit = get_object_or_404(VocabUnit, pk=unit_id, is_active=True)
    if not _can_access_unit(request.user, unit):
        messages.error(request, '이 단원은 배정되지 않았습니다.')
        return redirect('vocab:home')

    total = unit.words.count()
    star_count = StudentWordStar.objects.filter(
        student=request.user, word__unit=unit,
    ).count()
    return render(request, 'vocab/test.html', {
        'unit': unit,
        'total': total,
        'star_count': star_count,
    })


@login_required
@require_POST
def test_start_api(request):
    """테스트 세션 생성 + 출제 단어 목록 반환 (뜻 제외).

    body: {unit_id, star_only}
    return: {session_id, words: [{id, index, word, sub_unit}]}  (셔플됨)
    """
    try:
        data = json.loads(request.body or '{}')
        unit_id = int(data['unit_id'])
        star_only = bool(data.get('star_only'))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return JsonResponse({'success': False, 'error': '잘못된 요청'}, status=400)

    unit = get_object_or_404(VocabUnit, pk=unit_id, is_active=True)
    if not _can_access_unit(request.user, unit):
        return JsonResponse({'success': False, 'error': '권한 없음'}, status=403)

    words = list(unit.words.all().order_by('index'))
    if star_only:
        starred_ids = set(
            StudentWordStar.objects
            .filter(student=request.user, word__unit=unit)
            .values_list('word_id', flat=True)
        )
        words = [w for w in words if w.id in starred_ids]

    if not words:
        return JsonResponse({'success': False, 'error': '출제할 단어가 없습니다.'}, status=400)

    random.shuffle(words)
    session = VocabSession.objects.create(
        student=request.user, unit=unit, star_only=star_only,
        total_count=len(words),
    )
    return JsonResponse({
        'success': True,
        'session_id': session.id,
        'words': [
            {'id': w.id, 'index': w.index, 'word': w.word, 'sub_unit': w.sub_unit}
            for w in words
        ],
    }, json_dumps_params={'ensure_ascii': False})


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

    # 틀린 단어는 자동으로 별표 → 플래시카드 '별표만' 집중훈련으로 흐름 연결
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

    wrong = [
        {'word': a.word.word, 'meaning': a.word.meaning, 'input': a.input_value}
        for a in attempts if not a.is_correct
    ]
    return JsonResponse({
        'success': True,
        'correct': correct,
        'total': total,
        'percent': round(correct / total * 100) if total else 0,
        'wrong': wrong,
    }, json_dumps_params={'ensure_ascii': False})


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
    for s in students:
        s.vocab_assigned_count = assign_counts.get(s.id, 0)
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
