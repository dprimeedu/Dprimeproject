"""시험 응시·자동채점 뷰 (모의고사 + 내신 통합). summary 앱 패턴.

- 모의고사: academy.QuestionData를 (학년·연도·강)으로 실시간 출제. ExamPaper(source=mock)는
  배정/응시 시점에 get_or_create.
- 내신: 외부(엑셀답지생성 흐름)에서 import_api로 푸시한 ExamPaper(source=naesin)+ExamQuestion.
  카테고리 6종: Part1~4 / 내신TEST / 내신객관식빈칸.
채점은 객관식(1~5) 숫자 비교 자동채점.
"""
import json
import os
import re

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

# 동그라미 숫자 → 일반 숫자 (정답키에 ①②③④⑤ 가 와도 인식)
_CIRCLED = {'①': '1', '②': '2', '③': '3', '④': '4', '⑤': '5',
            '⑥': '6', '⑦': '7', '⑧': '8', '⑨': '9', '⑩': '10'}


def parse_answers(correct_answer):
    """정답키 문자열 → 허용 정답 리스트. 복수정답(중복 답) 지원.

    예) '2,3' / '②③' / '2 또는 3' / '2/3' / '2 or 3' → ['2', '3'].
    구분자(쉼표·슬래시·공백·또는·or··~|)로 나눈다. 단일 정답이면 1개짜리 리스트.
    """
    s = (correct_answer or '').strip()
    if not s:
        return []
    for k, v in _CIRCLED.items():
        s = s.replace(k, v + ',')          # 동그라미는 붙어 있어도 분리되게 구분자 삽입
    out = []
    for p in re.split(r'[,\s/|·~]+|또는|or', s):
        p = p.strip()
        if not p:
            continue
        if re.fullmatch(r'[1-5]{2,}', p):  # 객관식(1~5) 붙여 쓴 복수정답: '23' → 2,3
            out.extend(list(p))
        else:
            out.append(p)
    return out


def grade_answer(student_choice, correct_answer):
    """학생 답 vs 정답 채점. 복수정답이면 그중 하나라도 맞으면 정답.

    각 정답은 숫자면 숫자 비교, 아니면 문자열 비교.
    """
    s = (student_choice or '').strip()
    if not s:
        return False
    for c in parse_answers(correct_answer):
        try:
            if float(s) == float(c):
                return True
        except ValueError:
            if s == c:
                return True
    return False


# 한글 요일 → weekday() 번호 (월=0 … 일=6)
_WEEKDAY_NUM = {'월': 0, '화': 1, '수': 2, '목': 3, '금': 4, '토': 5, '일': 6}


def parse_weekdays(s):
    """'화목' / '월,수,금' → {1,3} 같은 요일 번호 집합."""
    return {_WEEKDAY_NUM[ch] for ch in (s or '') if ch in _WEEKDAY_NUM}


def class_days_until(weekdays_str, exam_date, today):
    """오늘(포함)~시험일 전날까지, 학생 출석요일에 해당하는 '남은 수업 횟수'.

    출석요일/시험일 없으면 None. 시험일이 지났으면 0.
    """
    from datetime import timedelta
    wd = parse_weekdays(weekdays_str)
    if not wd or not exam_date:
        return None
    if exam_date <= today:
        return 0
    n, d = 0, today
    while d < exam_date:           # 시험 당일은 제외(그날이 시험)
        if d.weekday() in wd:
            n += 1
        d += timedelta(days=1)
    return n


def _split_redblue(text):
    """빨파 text('원문\\n[빨] ...\\n[파] ...') → (passage, red, blue). ￰ 마커는 「」 로 표시."""
    passage, red, blue = [], '', ''
    for line in (text or '').split('\n'):
        ls = line.strip()
        if ls.startswith('[빨]'):
            red = ls[3:].strip()
        elif ls.startswith('[파]'):
            blue = ls[3:].strip()
        else:
            passage.append(line)

    def mark(s):
        return re.sub('￰(.*?)￰', r'「\1」', s or '')
    return mark('\n'.join(passage).strip()), mark(red), mark(blue)


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
    if paper.category == '빨파':       # 모의고사 빨파는 배정 없이 자기주도 응시 허용
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
            .exclude(category='빨파')      # 빨파 모의고사는 별도 메뉴로
            .order_by('school_grade', 'season', 'category')
        )
        return render(request, 'exam/home.html', {
            'is_teacher': True,
            'mock_exams': available_mock_exams(),
            'naesin_papers': naesin_papers,
            'has_redblue': ExamPaper.objects.filter(category='빨파').exists(),
        })

    assignments = list(
        ExamAssignment.objects.filter(student=request.user)
        .select_related('paper').order_by('-assigned_at')
    )
    return render(request, 'exam/home.html', {
        'is_teacher': False,
        'assignments': assignments,
        'has_redblue': ExamPaper.objects.filter(category='빨파').exists(),
    })


@login_required
def mock_redblue(request):
    """모의고사 빨파 회차 브라우저 — 학년 → 연도·월 회차 선택 후 응시(자기주도)."""
    if not is_teacher(request.user) and not getattr(request.user, 'is_approved', False):
        return render(request, 'exam/student_pending.html', {})

    from collections import defaultdict
    papers = (ExamPaper.objects.filter(category='빨파')
              .annotate(qn=Count('questions')).order_by('school_grade', 'season'))
    tree = defaultdict(lambda: defaultdict(list))   # grade -> year -> [(month, paper)]
    for p in papers:
        m = re.match(r'(\d{4})\s*(\d{1,2})\s*월', p.season or '')
        year = m.group(1) if m else '기타'
        month = int(m.group(2)) if m else 0
        tree[p.school_grade][year].append((month, p))

    grades = sorted(tree.keys())
    # 기본 학년 = 학생 본인 학년(고N) 있으면 그것, 없으면 첫 학년
    default_grade = ''
    try:
        sg = request.user.report_info.school_grade or ''
        mm = re.search(r'고[123]', sg)
        if mm and mm.group(0) in tree:
            default_grade = mm.group(0)
    except Exception:
        pass
    grade = request.GET.get('grade') or default_grade or (grades[0] if grades else '')

    years = []
    for y in sorted(tree.get(grade, {}).keys(), reverse=True):
        months = [{'month': mo, 'paper': p} for mo, p in sorted(tree[grade][y])]
        years.append({'year': y, 'months': months})

    return render(request, 'exam/mock_redblue.html', {
        'grades': grades, 'grade': grade, 'years': years,
        'is_teacher': is_teacher(request.user),
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
    redblue = session.paper.category == '빨파'   # 빨파 회차 → 지문+지시문 리딩 응시

    # 진행 저장된 답/오류표시 로드 → 이어풀기(이미 입력/오류표시 문항은 숨김)
    saved = {a.number: a for a in ExamAnswer.objects.filter(session=session)}
    q_view, done_count = [], 0
    for q in questions:
        a = saved.get(q['number'])
        choice = a.student_choice if a else ''
        flagged = a.flagged if a else False
        answered = bool(choice) or flagged
        if answered:
            done_count += 1
        item = {'number': q['number'], 'qtype': q['qtype'],
                'choice': choice, 'flagged': flagged, 'answered': answered}
        if redblue:
            item['passage'], item['red'], item['blue'] = _split_redblue(q.get('text', ''))
        q_view.append(item)

    # 시험일 D-day + 남은 수업 수 (학생 출석요일 기준)
    today = timezone.now().date()
    exam_date = session.paper.exam_date
    dday = (exam_date - today).days if exam_date else None
    weekdays = ''
    try:
        weekdays = request.user.report_info.attend_weekdays
    except Exception:
        weekdays = ''
    classes_left = class_days_until(weekdays, exam_date, today)

    return render(request, 'exam/session.html', {
        'session': session,
        'questions': q_view,
        'total_questions': len(q_view),
        'done_count': done_count,
        'daily_goal': session.paper.daily_goal,
        'exam_date': exam_date,
        'dday': dday,
        'classes_left': classes_left,
        'redblue': redblue,
    })


@login_required
def result_view(request, session_id):
    session = get_object_or_404(
        ExamSession.objects.select_related('paper', 'student'), pk=session_id)
    teacher = is_teacher(request.user)
    if session.student != request.user and not teacher:
        return redirect('exam:home')
    answers = list(session.answers.all().order_by('number'))
    flagged = [a for a in answers if a.flagged]
    graded = [a for a in answers if not a.flagged]
    wrong = [a for a in graded if not a.is_correct]          # 1차 오답(빈칸 포함)
    round2_done = session.round >= 2

    # 교사에게는 지문/관련번호/해설도 붙여 보여준다(채점·리뷰용)
    has_detail = False
    if teacher:
        meta = {q['number']: q for q in session.paper.get_questions()}
        for a in answers:
            m = meta.get(a.number) or {}
            a.q_ref = m.get('ref_number') or ''
            a.q_text = m.get('text') or m.get('question') or m.get('passage') or ''
            a.q_expl = m.get('explanation') or ''
            a.q_img = m.get('explanation_image') or ''
            if a.q_ref or a.q_text or a.q_expl or a.q_img:
                has_detail = True

    return render(request, 'exam/result.html', {
        'session': session,
        'answers': answers,
        'graded': graded,
        'wrong': wrong,
        'flagged': flagged,
        'wrong_numbers': [a.number for a in wrong],
        'is_teacher': teacher,
        'round2_done': round2_done,
        'round2_total': len(wrong),
        'has_detail': has_detail,
    })


@login_required
@require_POST
def save_progress_api(request):
    """응시 중 진행 저장(채점 안 함). body: {session_id, number, choice, flagged}.

    한 문항 단위 upsert — 자동저장. 이어풀기/오류표시 보존용.
    """
    try:
        data = json.loads(request.body or '{}')
        session_id = int(data['session_id'])
        number = int(data['number'])
        choice = ('' if data.get('choice') is None else str(data.get('choice'))).strip()
        flagged = bool(data.get('flagged'))
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return HttpResponseBadRequest('Invalid')

    session = get_object_or_404(
        ExamSession, pk=session_id, student=request.user,
        status=ExamSession.STATUS_IN_PROGRESS,
    )
    ExamAnswer.objects.update_or_create(
        session=session, number=number,
        defaults={'student_choice': choice, 'flagged': flagged},
    )
    return JsonResponse({'success': True})


@login_required
@require_POST
def submit_session_api(request):
    """세션 1차 제출 → 즉시 자동 채점. body: {session_id, answers:{번호:답}, flagged:[번호]}.

    오류표시(flagged) 문항은 채점에서 제외(전체 문항 수에서도 빠짐).
    """
    try:
        data = json.loads(request.body or '{}')
        session_id = int(data['session_id'])
        raw_answers = data.get('answers') or {}
        flagged_raw = data.get('flagged') or []
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
    flagged_set = set()
    for k in flagged_raw:
        try:
            flagged_set.add(int(k))
        except (ValueError, TypeError):
            continue

    questions = session.paper.get_questions()
    rows, correct, graded_total = [], 0, 0
    for q in questions:
        num = q['number']
        is_flagged = num in flagged_set
        choice = '' if is_flagged else choice_by_number.get(num, '')
        ans = q['answer']
        ok = (not is_flagged) and grade_answer(choice, ans)
        if not is_flagged:
            graded_total += 1
            if ok:
                correct += 1
        rows.append(ExamAnswer(
            session=session, number=num, qtype=q['qtype'],
            student_choice=choice, correct_answer=ans, is_correct=ok, flagged=is_flagged,
        ))

    with transaction.atomic():
        session.answers.all().delete()
        ExamAnswer.objects.bulk_create(rows)
        session.total_questions = graded_total      # 오류표시 제외한 채점 대상 수
        session.correct_count = correct
        session.status = ExamSession.STATUS_GRADED
        session.round = 1
        session.submitted_at = timezone.now()
        session.graded_at = timezone.now()
        session.save(update_fields=['total_questions', 'correct_count', 'status', 'round',
                                    'submitted_at', 'graded_at'])

    return JsonResponse({'success': True,
                         'redirect_url': f'/training/exam/result/{session.id}/'},
                        json_dumps_params={'ensure_ascii': False})


@login_required
@require_POST
def submit_round2_api(request):
    """2차(틀린문제 재시험) 제출. body: {session_id, answers:{번호:답}}.

    학생이 제출하지만 2차 점수는 학생에게 안 보이고 교사만 결과 페이지에서 본다.
    """
    try:
        data = json.loads(request.body or '{}')
        session_id = int(data['session_id'])
        raw_answers = data.get('answers') or {}
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return HttpResponseBadRequest('Invalid')

    session = get_object_or_404(
        ExamSession, pk=session_id, student=request.user,
        status=ExamSession.STATUS_GRADED, round=1,
    )
    by_num = {}
    for k, v in raw_answers.items():
        try:
            by_num[int(k)] = ('' if v is None else str(v)).strip()
        except (ValueError, TypeError):
            continue

    targets = list(session.answers.filter(flagged=False, is_correct=False))
    correct2 = 0
    for a in targets:
        a.second_choice = by_num.get(a.number, '')
        a.is_correct2 = grade_answer(a.second_choice, a.correct_answer)
        if a.is_correct2:
            correct2 += 1

    with transaction.atomic():
        if targets:
            ExamAnswer.objects.bulk_update(targets, ['second_choice', 'is_correct2'])
        session.round = 2
        session.round2_at = timezone.now()
        session.correct_count2 = correct2
        session.save(update_fields=['round', 'round2_at', 'correct_count2'])

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
def wrong_summary(request, paper_id):
    """시험지 한 장의 '틀린번호 모아보기' — 학생별 틀린 번호 + 번호별 오답자 수."""
    from collections import Counter
    paper = get_object_or_404(ExamPaper, pk=paper_id)
    sessions = list(
        ExamSession.objects.filter(paper=paper, status=ExamSession.STATUS_GRADED)
        .select_related('student').order_by('student__username')
    )
    sess_ids = [s.id for s in sessions]
    # 세션별 틀린/오류 번호 (1쿼리)
    wrong_map, flag_map = {}, {}
    for a in (ExamAnswer.objects.filter(session_id__in=sess_ids)
              .values('session_id', 'number', 'is_correct', 'flagged')
              .order_by('number')):
        if a['flagged']:
            flag_map.setdefault(a['session_id'], []).append(a['number'])
        elif not a['is_correct']:
            wrong_map.setdefault(a['session_id'], []).append(a['number'])

    freq = Counter()
    rows = []
    for s in sessions:
        wn = wrong_map.get(s.id, [])
        freq.update(wn)
        rows.append({
            'session': s,
            'student': s.student.username,
            'wrong': wn,
            'wrong_count': len(wn),
            'flagged': flag_map.get(s.id, []),
            'score': f'{s.correct_count}/{s.total_questions}',
            'round2': s.round >= 2,
            'correct2': s.correct_count2,
        })
    most_wrong = [{'number': n, 'count': c} for n, c in freq.most_common()]
    return render(request, 'exam/wrong_summary.html', {
        'paper': paper,
        'rows': rows,
        'most_wrong': most_wrong,
        'student_count': len(sessions),
    })


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


def _parse_question_item(it):
    """답지 한 문항 → {number, answer, qtype, ref_number, text, explanation} | None.

    list 형: [번호, 정답, 유형, 관련번호?, 지문/text?, 해설?]  (뒤 3개 선택, 하위호환)
    dict 형: {number, answer, qtype/type, ref_number/ref/관련번호, text/passage/지문, explanation/해설}
    """
    def s(v):
        return '' if v is None else str(v).strip()

    if isinstance(it, dict):
        try:
            num = int(it.get('number'))
        except (TypeError, ValueError):
            return None
        return {
            'number': num,
            'answer': s(it.get('answer')),
            'qtype': s(it.get('qtype') or it.get('type')),
            'ref_number': s(it.get('ref_number') or it.get('ref') or it.get('관련번호')),
            'text': s(it.get('text') or it.get('passage') or it.get('지문')),
            'explanation': s(it.get('explanation') or it.get('해설')),
        }
    try:
        num = int(it[0])
    except (ValueError, TypeError, IndexError):
        return None

    def g(i):
        return s(it[i]) if len(it) > i else ''
    return {'number': num, 'answer': g(1), 'qtype': g(2),
            'ref_number': g(3), 'text': g(4), 'explanation': g(5)}


@csrf_exempt
@require_POST
def import_naesin_api(request):
    """내신 정답 일괄 등록 (엑셀답지생성 흐름 → 웹 푸시).

    body: {
      token,
      school_grade,           # 예: 동백고2
      season,                 # 예: 2026 1학기 기말
      categories: {           # 카테고리별 문항 목록
        # 기본: [번호, 정답, 유형]  / 확장: [번호, 정답, 유형, 관련번호, 지문, 해설]
        # 또는 dict: {number, answer, qtype, ref_number, text, explanation}
        "Part1": [[번호, 정답, 유형, 관련번호?, 지문?, 해설?], ...],
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
                f = _parse_question_item(it)
                if f is None:
                    continue
                rows.append(ExamQuestion(paper=paper, **f))
            ExamQuestion.objects.bulk_create(rows)
            total += len(rows)
            results.append({'paper_id': paper.id, 'category': cat, 'questions': len(rows)})

    return JsonResponse({'success': True, 'school_grade': school_grade, 'season': season,
                         'papers': results, 'total_questions': total},
                        json_dumps_params={'ensure_ascii': False})


@csrf_exempt
@require_POST
def import_image_api(request):
    """문항 해설 이미지 업로드 (multipart/form-data). 구글드라이브 대체 — 서버에 직접 저장.

    form fields: token, number, image(파일) + 문항식별
      식별 A: paper_id
      식별 B: school_grade, season, category
    """
    # 멀티파트라 request.body 못 읽음 → 헤더/폼필드에서 토큰 확인
    expected = getattr(settings, 'EXAM_IMPORT_TOKEN', '')
    got = request.headers.get('X-Exam-Token') or request.POST.get('token') or ''
    if not expected or got != expected:
        return JsonResponse({'success': False, 'error': '토큰 불일치/미설정'}, status=403)

    img = request.FILES.get('image')
    if not img:
        return JsonResponse({'success': False, 'error': 'image 파일 없음'}, status=400)
    try:
        number = int(request.POST.get('number'))
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 'number 필요'}, status=400)

    paper_id = (request.POST.get('paper_id') or '').strip()
    if paper_id:
        q = ExamQuestion.objects.filter(paper_id=paper_id, number=number).first()
    else:
        q = ExamQuestion.objects.filter(
            paper__source=ExamPaper.SOURCE_NAESIN,
            paper__school_grade=(request.POST.get('school_grade') or '').strip(),
            paper__season=(request.POST.get('season') or '').strip(),
            paper__category=(request.POST.get('category') or '').strip(),
            number=number,
        ).first()
    if q is None:
        return JsonResponse({'success': False, 'error': '해당 문항을 찾지 못함'}, status=404)

    # 파일명 충돌 방지: 시험지·번호 기준 고정 이름
    ext = os.path.splitext(img.name)[1].lower() or '.png'
    fname = f'p{q.paper_id}_n{q.number}{ext}'
    if q.explanation_image:
        q.explanation_image.delete(save=False)   # 재업로드 시 기존 교체
    q.explanation_image.save(fname, img, save=True)
    return JsonResponse({'success': True, 'paper_id': q.paper_id, 'number': q.number,
                         'url': q.explanation_image.url},
                        json_dumps_params={'ensure_ascii': False})
