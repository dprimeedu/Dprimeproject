"""시험 응시·자동채점 뷰 (모의고사 + 내신 통합). summary 앱 패턴.

- 모의고사: academy.QuestionData를 (학년·연도·강)으로 실시간 출제. ExamPaper(source=mock)는
  배정/응시 시점에 get_or_create.
- 내신: 외부(엑셀답지생성 흐름)에서 import_api로 푸시한 ExamPaper(source=naesin)+ExamQuestion.
  카테고리 6종: Part1~4 / 내신TEST / 내신객관식빈칸.
채점은 객관식(1~5) 숫자 비교 자동채점.
"""
import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from writing.views import is_teacher, teacher_required
from academy.models import QuestionData

from .models import ExamPaper, ExamQuestion, ExamAssignment, ExamSession, ExamAnswer

# 내신 카테고리 표준 목록 (엑셀답지생성 흐름과 동일)
NAESIN_CATEGORIES = ['Part1', 'Part2', 'Part3', 'Part4', '내신TEST', '내신객관식빈칸']


# ─────────────────────────────────────────────
# 공통
# ─────────────────────────────────────────────

def grade_answer(student_choice, correct_answer):
    """학생 답 vs 정답 채점. 둘 다 숫자면 숫자 비교, 아니면 문자열 비교."""
    s = (student_choice or '').strip()
    c = (correct_answer or '').strip()
    if not s or not c:
        return False
    try:
        return float(s) == float(c)
    except ValueError:
        return s == c


def available_mock_exams():
    """QuestionData에 존재하는 모의고사 1회분 목록 (학년·연도·강 + 문항 수)."""
    rows = (QuestionData.objects
            .values('학년', '연도', '강')
            .annotate(c=Count('색인'))
            .order_by('학년', '-연도', '강'))
    return [{'grade': r['학년'], 'year': r['연도'], 'month': r['강'], 'count': r['c'],
             'title': f"{r['연도']} {r['학년']} {r['강']}".strip()} for r in rows]


def get_or_create_mock_paper(grade, year, month):
    paper, _ = ExamPaper.objects.get_or_create(
        source=ExamPaper.SOURCE_MOCK, grade=grade, year=year, month=month,
        school_grade='', season='', category='',
        defaults={'title': f'{year} {grade} {month}'.strip()},
    )
    return paper


def _can_access(user, paper):
    if is_teacher(user):
        return True
    return ExamAssignment.objects.filter(paper=paper, student=user).exists()


# ─────────────────────────────────────────────
# 학생/교사 홈
# ─────────────────────────────────────────────

@login_required
def student_home(request):
    if not is_teacher(request.user) and not getattr(request.user, 'is_approved', False):
        return render(request, 'exam/student_pending.html', {})

    if is_teacher(request.user):
        naesin_papers = list(
            ExamPaper.objects.filter(source=ExamPaper.SOURCE_NAESIN)
            .order_by('school_grade', 'season', 'category')
        )
        return render(request, 'exam/home.html', {
            'is_teacher': True,
            'mock_exams': available_mock_exams(),
            'naesin_papers': naesin_papers,
        })

    assignments = list(
        ExamAssignment.objects.filter(student=request.user)
        .select_related('paper').order_by('-assigned_at')
    )
    return render(request, 'exam/home.html', {
        'is_teacher': False,
        'assignments': assignments,
    })


# ─────────────────────────────────────────────
# 응시
# ─────────────────────────────────────────────

@login_required
def start_mock(request):
    """모의고사 응시 시작 — GET: grade, year, month."""
    grade = (request.GET.get('grade') or '').strip()
    year = (request.GET.get('year') or '').strip()
    month = (request.GET.get('month') or '').strip()
    if not (grade and year and month):
        messages.error(request, '모의고사 정보가 올바르지 않습니다.')
        return redirect('exam:home')
    paper = get_or_create_mock_paper(grade, year, month)
    if not _can_access(request.user, paper):
        messages.error(request, '이 모의고사는 배정되지 않았습니다.')
        return redirect('exam:home')
    if not paper.get_questions():
        messages.error(request, '이 회차에 문항이 없습니다.')
        return redirect('exam:home')
    session = ExamSession.objects.create(paper=paper, student=request.user)
    return redirect('exam:session', session_id=session.id)


@login_required
def start_paper(request, paper_id):
    """저장된 시험지(내신/배정) 응시 시작."""
    paper = get_object_or_404(ExamPaper, pk=paper_id)
    if not _can_access(request.user, paper):
        messages.error(request, '이 시험은 배정되지 않았습니다.')
        return redirect('exam:home')
    if not paper.get_questions():
        messages.error(request, '이 시험에 문항이 없습니다.')
        return redirect('exam:home')
    session = ExamSession.objects.create(paper=paper, student=request.user)
    return redirect('exam:session', session_id=session.id)


@login_required
def session_view(request, session_id):
    session = get_object_or_404(ExamSession.objects.select_related('paper'), pk=session_id)
    if session.student != request.user:
        messages.error(request, '본인 세션이 아닙니다.')
        return redirect('exam:home')
    if session.status != ExamSession.STATUS_IN_PROGRESS:
        return redirect('exam:result', session_id=session.id)

    questions = session.paper.get_questions()  # 정답(answer)은 템플릿에 안 보냄
    q_view = [{'number': q['number'], 'qtype': q['qtype'], 'passage': q['passage'],
               'question': q['question'], 'choices': q['choices']} for q in questions]
    return render(request, 'exam/session.html', {
        'session': session,
        'questions': q_view,
        'total_questions': len(q_view),
    })


@login_required
def result_view(request, session_id):
    session = get_object_or_404(ExamSession.objects.select_related('paper'), pk=session_id)
    if session.student != request.user and not is_teacher(request.user):
        return redirect('exam:home')
    answers = list(session.answers.all().order_by('number'))
    wrong = [a for a in answers if not a.is_correct and a.student_choice]
    return render(request, 'exam/result.html', {
        'session': session, 'answers': answers, 'wrong': wrong,
    })


@login_required
@require_POST
def submit_session_api(request):
    """세션 제출 → 즉시 자동 채점. body: {session_id, answers: {번호: 학생답}}."""
    try:
        data = json.loads(request.body or '{}')
        session_id = int(data['session_id'])
        raw_answers = data.get('answers') or {}
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return HttpResponseBadRequest('Invalid')

    session = get_object_or_404(
        ExamSession.objects.select_related('paper'), pk=session_id,
        student=request.user, status=ExamSession.STATUS_IN_PROGRESS,
    )

    choice_by_number = {}
    for k, v in raw_answers.items():
        try:
            choice_by_number[int(k)] = ('' if v is None else str(v)).strip()
        except (ValueError, TypeError):
            continue

    questions = session.paper.get_questions()
    rows, correct = [], 0
    for q in questions:
        choice = choice_by_number.get(q['number'], '')
        ans = q['answer']
        ok = grade_answer(choice, ans)
        if ok:
            correct += 1
        rows.append(ExamAnswer(
            session=session, number=q['number'], qtype=q['qtype'],
            student_choice=choice, correct_answer=ans, is_correct=ok,
        ))

    with transaction.atomic():
        session.answers.all().delete()
        ExamAnswer.objects.bulk_create(rows)
        session.total_questions = len(rows)
        session.correct_count = correct
        session.status = ExamSession.STATUS_GRADED
        session.submitted_at = timezone.now()
        session.graded_at = timezone.now()
        session.save(update_fields=['total_questions', 'correct_count', 'status',
                                    'submitted_at', 'graded_at'])

    return JsonResponse({'success': True,
                         'redirect_url': f'/training/exam/result/{session.id}/'},
                        json_dumps_params={'ensure_ascii': False})


# ─────────────────────────────────────────────
# 선생님 / 관리자
# ─────────────────────────────────────────────

@teacher_required
def result_list(request):
    sessions = list(
        ExamSession.objects.exclude(status=ExamSession.STATUS_IN_PROGRESS)
        .select_related('student', 'paper').order_by('-submitted_at')[:300]
    )
    return render(request, 'exam/result_list.html', {'sessions': sessions})


@teacher_required
def mock_assign_redirect(request):
    """모의고사(미저장) 배정 — 먼저 ExamPaper 생성 후 assign 으로."""
    grade = (request.GET.get('grade') or '').strip()
    year = (request.GET.get('year') or '').strip()
    month = (request.GET.get('month') or '').strip()
    if not (grade and year and month):
        messages.error(request, '모의고사 정보가 올바르지 않습니다.')
        return redirect('exam:home')
    paper = get_or_create_mock_paper(grade, year, month)
    return redirect('exam:assign', paper_id=paper.id)


@teacher_required
def assign_view(request, paper_id):
    """시험지 배정 — GET: 학생 체크박스, POST: 저장."""
    paper = get_object_or_404(ExamPaper, pk=paper_id)
    User = get_user_model()
    students_qs = [s for s in (User.objects.exclude(is_staff=True).exclude(is_superuser=True)
                               .order_by('login_id', 'username')) if not is_teacher(s)]

    if request.method == 'POST':
        target_ids = {int(x) for x in request.POST.getlist('student_ids') if x.isdigit()}
        current_ids = set(ExamAssignment.objects.filter(paper=paper)
                          .values_list('student_id', flat=True))
        valid_ids = {s.id for s in students_qs}
        to_add = (target_ids & valid_ids) - current_ids
        to_remove = current_ids - target_ids
        if to_add:
            ExamAssignment.objects.bulk_create(
                [ExamAssignment(paper=paper, student_id=sid, assigned_by=request.user)
                 for sid in to_add], ignore_conflicts=True)
        if to_remove:
            ExamAssignment.objects.filter(paper=paper, student_id__in=to_remove).delete()
        messages.success(request, f'배정 갱신 완료 (+{len(to_add)} / -{len(to_remove)}).')
        return redirect('exam:assign', paper_id=paper.id)

    assigned_ids = set(ExamAssignment.objects.filter(paper=paper)
                       .values_list('student_id', flat=True))
    students = [{'id': s.id, 'login_id': getattr(s, 'login_id', '') or '',
                 'name': s.username or '', 'is_assigned': s.id in assigned_ids}
                for s in students_qs]
    return render(request, 'exam/assign.html', {
        'paper': paper,
        'title': paper.resolved_title,
        'students': students,
        'assigned_count': len(assigned_ids),
        'question_count': len(paper.get_questions()),
    })


# ─────────────────────────────────────────────
# 외부 연동 — 내신 정답 import (토큰 인증)
# ─────────────────────────────────────────────

def _check_token(request):
    expected = getattr(settings, 'EXAM_IMPORT_TOKEN', '')
    if not expected:
        return False, '서버에 EXAM_IMPORT_TOKEN 미설정'
    got = (request.headers.get('X-Exam-Token') or request.GET.get('token') or '')
    if not got and request.body:
        try:
            got = (json.loads(request.body) or {}).get('token', '')
        except (json.JSONDecodeError, TypeError):
            got = ''
    return (got == expected), ('토큰 불일치' if got != expected else '')


@csrf_exempt
@require_POST
def import_naesin_api(request):
    """내신 정답 일괄 등록 (엑셀답지생성 흐름 → 웹 푸시).

    body: {
      token,
      school_grade,           # 예: 동백고2
      season,                 # 예: 2026 1학기 기말
      categories: {           # 카테고리별 문항 목록
        "Part1": [[번호, 정답, 유형], ...],
        "내신TEST": [...], "내신객관식빈칸": [...], ...
      }
    }
    각 카테고리 = ExamPaper(source=naesin) upsert + ExamQuestion 전체 교체(replace-on-reimport).
    """
    ok, reason = _check_token(request)
    if not ok:
        return JsonResponse({'success': False, 'error': reason}, status=403)
    try:
        data = json.loads(request.body or '{}')
        school_grade = str(data.get('school_grade', '')).strip()
        season = str(data.get('season', '')).strip()
        categories = data.get('categories') or {}
    except (json.JSONDecodeError, TypeError):
        return HttpResponseBadRequest('Invalid JSON')

    if not school_grade or not categories:
        return JsonResponse({'success': False, 'error': 'school_grade/categories 필요'}, status=400)

    results = []
    total = 0
    with transaction.atomic():
        for category, items in categories.items():
            cat = str(category).strip()
            if not items:
                continue
            paper, _ = ExamPaper.objects.get_or_create(
                source=ExamPaper.SOURCE_NAESIN, school_grade=school_grade,
                season=season, category=cat,
                grade='', year='', month='',
                defaults={'title': f'{school_grade} {season} {cat}'.strip()},
            )
            ExamQuestion.objects.filter(paper=paper).delete()
            rows = []
            for it in items:
                try:
                    num = int(it[0])
                except (ValueError, TypeError, IndexError):
                    continue
                ans = '' if len(it) < 2 or it[1] is None else str(it[1]).strip()
                typ = str(it[2]).strip() if len(it) > 2 and it[2] is not None else ''
                rows.append(ExamQuestion(paper=paper, number=num, answer=ans, qtype=typ))
            ExamQuestion.objects.bulk_create(rows)
            total += len(rows)
            results.append({'paper_id': paper.id, 'category': cat, 'questions': len(rows)})

    return JsonResponse({'success': True, 'school_grade': school_grade, 'season': season,
                         'papers': results, 'total_questions': total},
                        json_dumps_params={'ensure_ascii': False})
