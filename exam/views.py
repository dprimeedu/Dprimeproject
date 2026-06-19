"""시험 응시·자동채점 뷰 (모의고사 + 내신 통합). summary 앱 패턴.

- 모의고사: academy.QuestionData를 (학년·연도·강)으로 실시간 출제. ExamPaper(source=mock)는
  배정/응시 시점에 get_or_create.
- 내신: 외부(엑셀답지생성 흐름)에서 import_api로 푸시한 ExamPaper(source=naesin)+ExamQuestion.
  카테고리 6종: Part1~4 / 내신TEST / 내신객관식빈칸.
채점은 객관식(1~5) 숫자 비교 자동채점.
"""
import json
import math
import os
import re

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponse, HttpResponseForbidden, Http404
from urllib.parse import quote
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


NAESIN_GOAL_CATEGORIES = ['Part1', 'Part2', 'Part3', 'Part4']


def naesin_daily_goal(student):
    """학생의 내신 '하루 목표' 계산.

    하루목표 = (배정된 Part1~4 총 문항수) / (시험까지 남은 수업일수), 올림.
    - exam_date: 학생이 응시화면에서 입력(StudentInfo.naesin_exam_date)
    - weekdays:  StudentInfo.attend_weekdays (학생Data D열 동기화)
    값이 없으면 goal=None(입력 유도). 시험이 임박/지나 남은수업=0이면 남은 전량(total_q).
    """
    si = getattr(student, 'report_info', None)
    exam_date = getattr(si, 'naesin_exam_date', None) if si else None
    weekdays = getattr(si, 'attend_weekdays', '') if si else ''
    total_q = ExamQuestion.objects.filter(
        paper__source=ExamPaper.SOURCE_NAESIN,
        paper__category__in=NAESIN_GOAL_CATEGORIES,
        paper__assignments__student=student,
    ).count()
    today = timezone.now().date()
    classes_left = class_days_until(weekdays, exam_date, today)
    if total_q and classes_left:
        goal = math.ceil(total_q / classes_left)
    elif total_q and classes_left == 0:
        goal = total_q          # 시험 임박/당일 — 남은 전량
    else:
        goal = None
    dday = (exam_date - today).days if exam_date else None
    return {'goal': goal, 'total_q': total_q, 'classes_left': classes_left,
            'exam_date': exam_date, 'dday': dday, 'weekdays': weekdays}


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


def _find_redblue_paper(school_grade, year, month):
    season = f'{year} {month}월 모의고사'
    return (ExamPaper.objects.filter(category='빨파', school_grade=school_grade, season=season).first()
            or ExamPaper.objects.filter(category='빨파', school_grade=school_grade,
                                        season__startswith=f'{year} {month}월').first())


def redblue_qmap_for_mock(paper):
    """모의고사/유형별 paper → {paper번호: 빨파 ExamQuestion} 매핑.

    - SOURCE_MOCK: 같은 회차 빨파 시험지(category=빨파, season='YYYY M월 모의고사'). 번호 1:1.
    - SOURCE_MOCK_TYPE: 문항별 ref_number='연도-강-번호' 를 파싱해 회차별 빨파에서 원본번호로 매칭.
    """
    if paper.source == ExamPaper.SOURCE_MOCK:
        rb = _find_redblue_paper(paper.grade, paper.year, paper.month)
        if rb is None:
            return {}
        return {q.number: q for q in rb.questions.all()}

    if paper.source == ExamPaper.SOURCE_MOCK_TYPE:
        rows = paper.get_questions()
        refs = []
        for r in rows:
            m = re.match(r'(\d+)-(\d+)-(\d+)$', r.get('ref_number') or '')
            if m:
                refs.append((r['number'], m.group(1), int(m.group(2)), int(m.group(3))))
        if not refs:
            return {}
        rb_by_ym = {}
        for (y, mo) in {(y, mo) for (_, y, mo, _) in refs}:
            rb = _find_redblue_paper(paper.grade, y, mo)
            if rb is not None:
                rb_by_ym[(y, mo)] = rb
        if not rb_by_ym:
            return {}
        q_by_paper = {
            p.id: {q.number: q for q in p.questions.all()}
            for p in rb_by_ym.values()
        }
        result = {}
        for (new_num, y, mo, orig_num) in refs:
            rb = rb_by_ym.get((y, mo))
            if rb is None:
                continue
            q = q_by_paper.get(rb.id, {}).get(orig_num)
            if q is not None:
                result[new_num] = q
        return result

    return {}


def available_mock_exams():
    """QuestionData에 존재하는 모의고사 1회분 목록 (학년·연도·강 + 문항 수)."""
    rows = (QuestionData.objects
            .values('학년', '연도', '강')
            .annotate(c=Count('색인'))
            .order_by('학년', '-연도', '강'))
    return [{'grade': r['학년'], 'year': r['연도'], 'month': r['강'], 'count': r['c'],
             'title': ExamPaper.format_mock_title(r['연도'], r['학년'], r['강'])} for r in rows]


def get_or_create_mock_paper(grade, year, month):
    paper, _ = ExamPaper.objects.get_or_create(
        source=ExamPaper.SOURCE_MOCK, grade=grade, year=year, month=month,
        school_grade='', season='', category='',
        defaults={'title': ExamPaper.format_mock_title(year, grade, month)},
    )
    return paper


def get_or_create_mock_type_paper(grade, type_name, tags, start, end):
    """유형별 가상 시험지 get_or_create. 식별 = (grade, type_name, range) — season에 범위 인코딩.

    tags = ['[순서]','[문장넣기]',...] (클라이언트가 COMBO_TYPES로 해석해 전달).
    """
    tags_str = ','.join(t for t in tags if t)
    season = f'{start}-{end}'
    paper, created = ExamPaper.objects.get_or_create(
        source=ExamPaper.SOURCE_MOCK_TYPE, grade=grade, category=type_name,
        season=season, year='', month='', school_grade='',
        defaults={'title': f'{grade} {type_name} ({start}-{end})',
                  'type_tags': tags_str, 'range_start': start, 'range_end': end},
    )
    # 태그/범위가 바뀌었으면 갱신(같은 식별이라도 태그 보강 시 반영)
    fields = []
    if paper.type_tags != tags_str and tags_str:
        paper.type_tags = tags_str; fields.append('type_tags')
    if paper.range_start != start:
        paper.range_start = start; fields.append('range_start')
    if paper.range_end != end:
        paper.range_end = end; fields.append('range_end')
    if fields:
        paper.save(update_fields=fields)
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
    # 시험지당 가장 진행된(round↓·최근) 세션 1개만 — 과거 중복 세션 숨김
    sessions_all = (
        ExamSession.objects.filter(student=request.user)
        .exclude(status=ExamSession.STATUS_IN_PROGRESS)
        .select_related('paper').order_by('-round', '-submitted_at')
    )
    my_sessions, done_paper_ids = [], set()
    for s in sessions_all:
        if s.paper_id in done_paper_ids:
            continue
        done_paper_ids.add(s.paper_id)
        my_sessions.append(s)
    my_sessions.sort(key=lambda s: s.submitted_at or s.started_at, reverse=True)
    my_sessions = my_sessions[:30]
    # 선생님이 '최종 확인' 누른 결과 카드만 학생 시야에서 숨김.
    # 빨파공개만 된 상태에서는 '빨파채점' 액션을 위해 카드가 남아 있어야 한다.
    my_sessions = [s for s in my_sessions if not s.teacher_final_confirmed]
    # 이미 응시 결과가 있는 시험지는 위 '응시 시작' 카드에서 숨김.
    # 단 내신은 분할 응시(여러 차수에 걸쳐 일부 문항만 입력)가 정상 패턴 → 항상 노출.
    assignments = [a for a in assignments
                   if a.paper_id not in done_paper_ids
                   or a.paper.source == ExamPaper.SOURCE_NAESIN]
    return render(request, 'exam/home.html', {
        'is_teacher': False,
        'assignments': assignments,
        'my_sessions': my_sessions,
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

def _resume_or_start(request, paper):
    """이미 응시한 세션이 있으면 그 세션으로 보냄(정답 보존).
    - 진행 중 세션 → 이어풀기
    - 제출/채점된 세션 → 결과(틀린문제 빨파 복습) 페이지
    - 내신은 채점완료된 세션이 있어도 분할 응시를 위해 새 세션 생성
    - 없으면 새 세션 생성
    """
    session = (ExamSession.objects
               .filter(paper=paper, student=request.user)
               .order_by('-id').first())
    if session is None:
        session = ExamSession.objects.create(paper=paper, student=request.user)
        return redirect('exam:session', session_id=session.id)
    if session.status == ExamSession.STATUS_IN_PROGRESS:
        return redirect('exam:session', session_id=session.id)
    # 내신은 분할 응시 — 채점완료 후에도 '응시 시작'을 누르면 새 세션을 만들어 추가 입력.
    if paper.source == ExamPaper.SOURCE_NAESIN:
        session = ExamSession.objects.create(paper=paper, student=request.user)
        return redirect('exam:session', session_id=session.id)
    return redirect('exam:result', session_id=session.id)


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
    return _resume_or_start(request, paper)


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
    return _resume_or_start(request, paper)


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

    # 내신 Part1~4 응시 → 학생이 시험일 입력하고 하루목표(남은수업 기준) 실시간 계산
    is_naesin = (session.paper.source == ExamPaper.SOURCE_NAESIN
                 and session.paper.category != '빨파')
    goal_info = naesin_daily_goal(request.user) if is_naesin else None

    return render(request, 'exam/session.html', {
        'session': session,
        'questions': q_view,
        'total_questions': len(q_view),
        'done_count': done_count,
        'redblue': redblue,
        'show_goal': is_naesin,
        'goal_info': goal_info,
    })


@login_required
@require_POST
def set_exam_date(request):
    """학생이 응시화면에서 내신 시험시작일을 입력/수정 → StudentInfo 저장 + 하루목표 재계산 반환."""
    from report.models import StudentInfo
    from django.utils.dateparse import parse_date
    try:
        data = json.loads(request.body or '{}')
    except (json.JSONDecodeError, TypeError):
        return JsonResponse({'success': False, 'error': '잘못된 요청'}, status=400)
    raw = str(data.get('exam_date') or '').strip()
    d = parse_date(raw) if raw else None
    if raw and d is None:
        return JsonResponse({'success': False, 'error': '날짜 형식 오류(YYYY-MM-DD)'}, status=400)
    si, _ = StudentInfo.objects.get_or_create(student=request.user)
    si.naesin_exam_date = d
    si.save(update_fields=['naesin_exam_date'])
    info = naesin_daily_goal(request.user)
    info['exam_date'] = info['exam_date'].isoformat() if info['exam_date'] else None
    return JsonResponse({'success': True, 'goal_info': info},
                        json_dumps_params={'ensure_ascii': False})


@login_required
def result_view(request, session_id):
    session = get_object_or_404(
        ExamSession.objects.select_related('paper', 'student'), pk=session_id)
    teacher = is_teacher(request.user)
    if session.student != request.user and not teacher:
        return redirect('exam:home')
    # 교사가 결과를 열면 '미확인' 뱃지에서 빠진다(자동채점 → '채점대기' 대신 미확인 기준)
    if teacher and not session.teacher_checked:
        session.teacher_checked = True
        session.save(update_fields=['teacher_checked'])
    answers = list(session.answers.all().order_by('number'))
    flagged = [a for a in answers if a.flagged]
    graded = [a for a in answers if not a.flagged]
    # 내신은 분할 응시(여러 차수에 걸쳐 일부 문항만 입력)가 정상 패턴 →
    # 학생이 입력하지 않은 문항은 오답 표시에서 제외(입력한 것 중 틀린 것만).
    is_naesin = session.paper.source == ExamPaper.SOURCE_NAESIN
    wrong = [a for a in graded
             if not a.is_correct
             and not (is_naesin and not (a.student_choice or '').strip())]
    round2_done = session.round >= 2

    # 통합본 번호(ref_number) — 오답 표에 '몇번 출처(예: 2026-03-24)인지' 함께 표기.
    # 모의고사(SOURCE_MOCK)는 비어있음, 내신/유형별만 채워짐.
    meta = {q['number']: q for q in session.paper.get_questions()}
    for a in wrong:
        m = meta.get(a.number) or {}
        a.ref_number = m.get('ref_number') or ''
    has_ref = any(a.ref_number for a in wrong)

    # 내신 빨파 정답 PDF 링크 — ExamQuestion 단위로 URL 생성. 폴더 매칭은 view 응답 시점에 lazy.
    # 학생은 빨파 공개 완료(redblue_released) 후에만 접근 가능 — view 단에서 한 번 더 검사.
    rb_visible = teacher or session.redblue_released
    if session.paper.source == ExamPaper.SOURCE_NAESIN and wrong:
        qid_by_num = dict(ExamQuestion.objects
                          .filter(paper=session.paper, number__in=[a.number for a in wrong])
                          .values_list('number', 'id'))
        for a in wrong:
            qid = qid_by_num.get(a.number)
            if qid and a.ref_number and rb_visible:
                a.rb_pdf_url = f'/training/exam/redblue/{qid}.pdf'
            else:
                a.rb_pdf_url = ''
    else:
        for a in wrong:
            a.rb_pdf_url = ''

    # 교사에게는 지문/관련번호/해설도 붙여 보여준다(채점·리뷰용)
    has_detail = False
    if teacher:
        for a in answers:
            m = meta.get(a.number) or {}
            a.q_ref = m.get('ref_number') or ''
            a.q_text = m.get('text') or m.get('question') or m.get('passage') or ''
            a.q_expl = m.get('explanation') or ''
            a.q_img = m.get('explanation_image') or ''
            if a.q_ref or a.q_text or a.q_expl or a.q_img:
                has_detail = True

    # 모의고사 1차 오답 → 같은 회차 '빨파' 문제/정답을 번호로 붙인다.
    #  · 학생: 2차에 빨파 문제(지문) 표시. 정답이미지는 교사 공개(redblue_released) 후에만.
    #  · 교사: 항상 빨파 정답이미지 열람 + '공개' 버튼.
    is_mock_like = session.paper.source in (ExamPaper.SOURCE_MOCK, ExamPaper.SOURCE_MOCK_TYPE)
    # 더블클릭 단어조회용 회차 컨텍스트 — MOCK_TYPE 은 회차 섞임 → year/month=0
    mock_ctx = None
    if is_mock_like:
        gm = re.search(r'(\d+)', session.paper.grade or '')
        is_single = session.paper.source == ExamPaper.SOURCE_MOCK
        mock_ctx = {
            'grade': int(gm.group(1)) if gm else 0,
            'year': int(session.paper.year) if (is_single and str(session.paper.year).isdigit()) else 0,
            'month': int(session.paper.month) if (is_single and str(session.paper.month).isdigit()) else 0,
        }
    rb_map = redblue_qmap_for_mock(session.paper) if (is_mock_like and wrong) else {}
    released = session.redblue_released
    show_rb_answer = teacher or released        # 빨파 정답이미지 노출 여부
    has_redblue = False
    for a in wrong:
        q = rb_map.get(a.number)
        a.rb_has = q is not None
        if q is None:
            a.rb_passage = a.rb_red = a.rb_blue = ''
            a.rb_img = ''
            continue
        has_redblue = True
        a.rb_passage, a.rb_red, a.rb_blue = _split_redblue(q.text or '')
        a.rb_img = (q.explanation_image.url if (show_rb_answer and q.explanation_image) else '')

    # 내신 — 1차 오답의 지문(ExamQuestion.text)을 wrong에 붙여 result 화면 2차 입력 시
    # 학생이 지문을 보며 다시 풀 수 있게(모르는 단어 클릭→뜻 팝업·개인 단어장 자동 저장).
    # mock_ctx는 학생 학년만 채워 단어 lookup 컨텍스트로 사용.
    if session.paper.source == ExamPaper.SOURCE_NAESIN:
        for a in wrong:
            m = meta.get(a.number) or {}
            txt = m.get('text') or ''
            a.rb_passage = txt
            a.rb_red = a.rb_blue = ''
            a.rb_img = ''
            a.rb_has = bool(txt)
        if any(a.rb_has for a in wrong):
            has_redblue = True
        if mock_ctx is None:
            sg_grade = 0
            try:
                gm = re.search(r'고(\d)', getattr(request.user.report_info, 'school_grade', '') or '')
                if gm:
                    sg_grade = int(gm.group(1))
            except Exception:
                pass
            mock_ctx = {'grade': sg_grade, 'year': 0, 'month': 0}

    return render(request, 'exam/result.html', {
        'session': session,
        'answers': answers,
        'graded': graded,
        'wrong': wrong,
        'flagged': flagged,
        'wrong_numbers': [a.number for a in wrong],
        'wrong_second_numbers': [a.number for a in wrong if not a.is_correct2],
        'wrong_second_count': sum(1 for a in wrong if not a.is_correct2),
        'is_teacher': teacher,
        'round2_done': round2_done,
        'round2_total': len(wrong),
        'has_ref': has_ref,
        'has_detail': has_detail,
        'has_redblue': has_redblue,
        'redblue_released': released,
        'mock_ctx': mock_ctx,
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

    # 내신은 분할 응시(여러 차수에 걸쳐 일부 문항만 입력)가 정상 — 미입력은 채점 대상에서 제외.
    # 점수 분모도 학생이 입력한 문항 수 기준(예: 40개 입력 → 33/40).
    is_naesin = session.paper.source == ExamPaper.SOURCE_NAESIN

    questions = session.paper.get_questions()
    rows, correct, graded_total = [], 0, 0
    for q in questions:
        num = q['number']
        is_flagged = num in flagged_set
        choice = '' if is_flagged else choice_by_number.get(num, '')
        ans = q['answer']
        skip_blank = is_naesin and not is_flagged and not choice
        ok = (not is_flagged) and (not skip_blank) and grade_answer(choice, ans)
        if not is_flagged and not skip_blank:
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


def find_next_mock_paper(paper):
    """주어진 모의고사 paper의 '다음 회차' paper(없으면 None).

    같은 학년에서 (연도, 강) > 현재 의 최소값을 찾아 get_or_create_mock_paper 한다.
    강(월)은 '9' < '10' 처리를 위해 정수 비교. 회차가 없는 학년/연도는 None.
    """
    if paper.source != ExamPaper.SOURCE_MOCK:
        return None
    try:
        cur = (int(paper.year), int(paper.month))
    except (ValueError, TypeError):
        return None
    rows = (QuestionData.objects.filter(학년=paper.grade)
            .values_list('연도', '강').distinct())
    nxt = None
    for y, m in rows:
        try:
            yi, mi = int(y), int(m)
        except (ValueError, TypeError):
            continue
        if (yi, mi) <= cur:
            continue
        if nxt is None or (yi, mi) < nxt:
            nxt = (yi, mi)
    if nxt is None:
        return None
    return get_or_create_mock_paper(paper.grade, str(nxt[0]), str(nxt[1]))


def find_next_mock_type_paper(paper):
    """유형별 가상 시험지의 '다음 세트' paper(없으면 None).

    동일 (grade, category, type_tags) 에서 range를 (end+1) ~ (end + size) 로 잡아
    QuestionData 총 가용 문항을 넘으면 자른다. 이미 끝이면 None.
    """
    if paper.source != ExamPaper.SOURCE_MOCK_TYPE:
        return None
    start, end = paper.range_start, paper.range_end
    if not start or not end or end < start:
        return None
    tags = [t for t in (paper.type_tags or '').split(',') if t]
    if not tags:
        return None
    total = QuestionData.objects.filter(학년=paper.grade, 유형__in=tags).count()
    size = end - start + 1
    next_start = end + 1
    next_end = end + size
    if next_start > total:
        return None      # 단어장(모집단) 끝까지 다 풀었음
    if next_end > total:
        next_end = total  # 마지막 세트는 잘림
    return get_or_create_mock_type_paper(paper.grade, paper.category,
                                         tags, next_start, next_end)


def find_next_paper(paper):
    """다음 회차/세트 paper 디스패처. SOURCE에 따라 회차(mock) 또는 세트(mock_type) 분기.
    내신(naesin)은 분할 응시 패턴이라 '다음' 개념 없음 → None."""
    if paper.source == ExamPaper.SOURCE_MOCK:
        return find_next_mock_paper(paper)
    if paper.source == ExamPaper.SOURCE_MOCK_TYPE:
        return find_next_mock_type_paper(paper)
    return None


@login_required
@require_POST
def mark_redblue_done(request, session_id):
    """학생이 빨파 정답 보고 자기채점(빨파채점) 완료 표시.

    선생님이 빨파공개한 후에만 가능. 이후 선생님이 [최종 확인]을 눌러야 학생 홈에서
    이 시험이 사라진다(그 전까지는 새 시험과 함께 같이 보임).
    """
    session = get_object_or_404(ExamSession, pk=session_id, student=request.user)
    if not session.redblue_released:
        return JsonResponse({'success': False,
                             'error': '빨파 정답이 아직 공개되지 않았습니다'}, status=400)
    if not session.student_redblue_done:
        session.student_redblue_done = True
        session.student_redblue_done_at = timezone.now()
        session.save(update_fields=['student_redblue_done', 'student_redblue_done_at'])
    return JsonResponse({'success': True})


@require_POST
def final_confirm(request, session_id):
    """선생님 최종 확인 — 학생 빨파채점을 검토한 후 누른다.

    이걸 누르면 학생 홈에서 이전 시험 카드가 사라지고 다음 시험만 남는다.
    """
    if not is_teacher(request.user):
        return HttpResponseBadRequest('권한 없음')
    session = get_object_or_404(ExamSession, pk=session_id)
    if not session.teacher_final_confirmed:
        session.teacher_final_confirmed = True
        session.teacher_final_confirmed_at = timezone.now()
        session.teacher_checked = True
        session.save(update_fields=['teacher_final_confirmed',
                                    'teacher_final_confirmed_at', 'teacher_checked'])
    return JsonResponse({'success': True})


@require_POST
def release_redblue(request, session_id):
    """교사가 '빨파정답 공개' → 학생이 자기 1차 오답의 빨파 정답이미지를 볼 수 있게 한다.

    부수효과: 모의/유형이면 다음 회차/세트를 학생에게 자동 배정 → 학생 홈에 다음 시험이
    이전 시험과 함께 표시. 이전 시험은 학생 빨파채점 + 선생님 최종확인 후에 사라진다.
    """
    if not is_teacher(request.user):
        return HttpResponseBadRequest('권한 없음')
    session = get_object_or_404(ExamSession.objects.select_related('paper'), pk=session_id)
    next_paper_id = None
    next_title = ''
    if not session.redblue_released:
        session.redblue_released = True
        session.redblue_released_at = timezone.now()
        session.teacher_checked = True
        session.save(update_fields=['redblue_released', 'redblue_released_at', 'teacher_checked'])
        nxt = find_next_paper(session.paper)
        if nxt is not None:
            ExamAssignment.objects.get_or_create(
                paper=nxt, student=session.student,
                defaults={'assigned_by': request.user},
            )
            next_paper_id = nxt.id
            next_title = nxt.resolved_title
    return JsonResponse({'success': True,
                         'next_paper_id': next_paper_id, 'next_title': next_title},
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
    # 내신은 분할 응시 — 미입력은 오답 집계에서 제외(입력한 것 중 틀린 것만).
    is_naesin = paper.source == ExamPaper.SOURCE_NAESIN
    # 세션별 틀린/오류 번호 (1쿼리)
    wrong_map, flag_map = {}, {}
    for a in (ExamAnswer.objects.filter(session_id__in=sess_ids)
              .values('session_id', 'number', 'is_correct', 'flagged', 'student_choice')
              .order_by('number')):
        if a['flagged']:
            flag_map.setdefault(a['session_id'], []).append(a['number'])
        elif not a['is_correct']:
            if is_naesin and not (a['student_choice'] or '').strip():
                continue
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


@login_required
def redblue_pdf(request, question_id):
    """내신 빨파 정답 PDF 서빙 — nginx X-Accel-Redirect 로 NAS 교재폴더 파일 스트리밍.

    접근 권한: 교사는 모두 / 학생은 같은 paper 응시 + redblue_released=True 일 때만.
    파일이 NAS에 없으면 404. 컨테이너에 /redblue_root 마운트가 있어야 동작한다.
    """
    q = get_object_or_404(ExamQuestion.objects.select_related('paper'), pk=question_id)
    teacher = is_teacher(request.user)
    if not teacher:
        ok = ExamSession.objects.filter(
            paper_id=q.paper_id, student=request.user, redblue_released=True,
        ).exists()
        if not ok:
            return HttpResponseForbidden('빨파 정답이 아직 공개되지 않았습니다.')
    rel = q.paper.redblue_relpath(q.ref_number)
    if not rel:
        raise Http404('빨파 정답 PDF를 찾지 못했습니다.')
    resp = HttpResponse(content_type='application/pdf')
    # X-Accel-Redirect 헤더는 ASCII 필요 — 한글 경로는 percent-encoding.
    resp['X-Accel-Redirect'] = '/redblue_internal/' + quote(rel)
    return resp


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
      exam_date,              # 선택: 'YYYY-MM-DD' (보내면 paper.exam_date 갱신, 생략 시 유지)
      daily_goal,             # 선택: 정수 (보내면 paper.daily_goal 갱신, 생략 시 유지)
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
        # 선택: 학생 이름 리스트 — 보내면 생성된 시험지를 그 학생들에게 자동 배정(전원 적용).
        #   (writing import_api 의 assign_to_list 패턴과 동일. username=이름 매칭.)
        assign_to_list = [str(x).strip() for x in (data.get('assign_to_list') or []) if str(x).strip()]
        # 선택: append=True 면 기존 문항을 지우지 않고 '뒤에 이어붙임'(번호는 기존 최대+1 부터 재지정).
        #   기본(False)은 카테고리 전체 교체(replace-on-reimport).
        append = bool(data.get('append'))
    except (json.JSONDecodeError, TypeError):
        return HttpResponseBadRequest('Invalid JSON')

    if not school_grade or not categories:
        return JsonResponse({'success': False, 'error': 'school_grade/categories 필요'}, status=400)

    # 선택: 시험일(YYYY-MM-DD)·하루목표 — 보내면 paper에 반영(admin 수동입력 대체), 안 보내면 기존 유지
    from django.utils.dateparse import parse_date
    raw_date = str(data.get('exam_date') or '').strip()
    exam_date = parse_date(raw_date) if raw_date else None
    if raw_date and exam_date is None:
        return JsonResponse({'success': False, 'error': f'exam_date 형식 오류(YYYY-MM-DD): {raw_date}'}, status=400)
    raw_goal = data.get('daily_goal', None)
    try:
        daily_goal = int(raw_goal) if raw_goal not in (None, '') else None
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': f'daily_goal 정수 아님: {raw_goal}'}, status=400)

    results = []
    total = 0
    created_papers = []   # 배정용 — 이번에 생성/갱신된 ExamPaper 객체
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
            # 시험일·하루목표는 보낸 경우에만 갱신
            paper_fields = []
            if exam_date is not None:
                paper.exam_date = exam_date
                paper_fields.append('exam_date')
            if daily_goal is not None:
                paper.daily_goal = daily_goal
                paper_fields.append('daily_goal')
            if paper_fields:
                paper.save(update_fields=paper_fields)
            if append:
                # 기존 문항 유지 + 최대 번호 뒤로 이어붙임(번호 재지정). 복수정답 등 기존 문항 보존.
                from django.db.models import Max
                base_no = paper.questions.aggregate(m=Max('number'))['m'] or 0
                rows = []
                k = 0
                for it in items:
                    f = _parse_question_item(it)
                    if f is None:
                        continue
                    k += 1
                    f['number'] = base_no + k
                    rows.append(ExamQuestion(paper=paper, **f))
                ExamQuestion.objects.bulk_create(rows)
                cur = paper.questions.count()
            else:
                ExamQuestion.objects.filter(paper=paper).delete()
                rows = []
                for it in items:
                    f = _parse_question_item(it)
                    if f is None:
                        continue
                    rows.append(ExamQuestion(paper=paper, **f))
                ExamQuestion.objects.bulk_create(rows)
                cur = len(rows)
            total += len(rows)
            created_papers.append(paper)
            results.append({'paper_id': paper.id, 'category': cat,
                            'added': len(rows), 'questions': cur})

    # 학생 자동 배정 — assign_to_list(이름)의 학생 전원에게 생성된 시험지를 배정.
    #   구글시트 '답지업뎃'이 학생 시트에 자동 기록되는 것의 웹(홈페이지) 대응.
    #   username=이름 매칭, 동명이인/미존재는 스킵하고 결과에 보고.
    assigned_many = None
    if assign_to_list and created_papers:
        User = get_user_model()
        ok_names, fail = [], []
        for nm in assign_to_list:
            qs = User.objects.filter(username=nm)
            if qs.count() != 1:
                fail.append({'name': nm, 'reason': ('없음' if qs.count() == 0 else '동명이인')})
                continue
            student = qs.first()
            for paper in created_papers:
                ExamAssignment.objects.get_or_create(
                    paper=paper, student=student, defaults={'assigned_by': None})
            ok_names.append(student.username)
        assigned_many = {'assigned': ok_names, 'failed': fail, 'papers': len(created_papers)}

    return JsonResponse({'success': True, 'school_grade': school_grade, 'season': season,
                         'exam_date': raw_date or None, 'daily_goal': daily_goal,
                         'papers': results, 'total_questions': total,
                         'assigned_many': assigned_many},
                        json_dumps_params={'ensure_ascii': False})


@csrf_exempt
@require_POST
def import_student_schedule(request):
    """학생 수업요일 동기화 — 로컬 학생요일동기화.py → StudentInfo.attend_weekdays 세팅.

    body: { token, schedules: [ {name, weekdays} | {name, daytime} ] }
      - weekdays: '월수' 처럼 요일만. 없으면 daytime('월수44시')에서 요일 글자만 추출.
      - Member.username(이름)으로 매칭. 동명이인/미존재는 건너뜀(카운트 반환).
    """
    ok, reason = _check_token(request)
    if not ok:
        return JsonResponse({'success': False, 'error': reason}, status=403)
    from report.models import StudentInfo
    User = get_user_model()
    try:
        data = json.loads(request.body or '{}')
        schedules = data.get('schedules') or []
    except (json.JSONDecodeError, TypeError):
        return HttpResponseBadRequest('Invalid JSON')

    _WD = '월화수목금토일'
    updated, skipped_dup, not_found = 0, 0, 0
    for it in schedules:
        name = str(it.get('name') or '').strip()
        wd = str(it.get('weekdays') or '').strip()
        if not wd:
            wd = ''.join(c for c in str(it.get('daytime') or '') if c in _WD)
        if not name or not wd:
            continue
        qs = User.objects.filter(username=name)
        cnt = qs.count()
        if cnt == 0:
            not_found += 1
            continue
        if cnt > 1:
            skipped_dup += 1
            continue
        si, _ = StudentInfo.objects.get_or_create(student=qs.first())
        fields = []
        if si.attend_weekdays != wd:
            si.attend_weekdays = wd
            fields.append('attend_weekdays')
        daytime = str(it.get('daytime') or '').strip()
        if daytime and si.weekday_time != daytime:
            si.weekday_time = daytime
            fields.append('weekday_time')
        if fields:
            si.save(update_fields=fields)
        updated += 1

    return JsonResponse({'success': True, 'updated': updated,
                         'skipped_dup': skipped_dup, 'not_found': not_found},
                        json_dumps_params={'ensure_ascii': False})


# exam_key 규약: 회차 = 'YYYY-고N-M' (예: '2013-고3-11'). 유형 = '고N-유형명-YYYY'(콘텐츠 미정).
_MOCK_KEY_ROUND_RE = re.compile(r'^(\d{4})-(고[123])-(\d{1,2})$')


@csrf_exempt
@require_POST
def import_student_mock_api(request):
    """학생별 모의고사 배정 (개별단어장생성.py ⑤ → 웹 푸시).

    body: { token, items: [ ... ] }
      - kind='round': {name, exam_key:'YYYY-고N-M', goal?} → 회차 ExamPaper(source=mock) 배정.
                       콘텐츠=QuestionData(학년·연도·강) 자동출제.
      - kind='type' : {name, grade:'고N', type_name, types:['[순서]',...], start, end, goal?}
                       → QuestionData를 학년+유형태그 필터, 색인(연도·강·번호)순 재번호, [start-end] 슬라이스한
                       가상 시험지(source=mock_type) 배정. import 불필요(같은 모집단·태그 이미 보유).
      두 경우 모두 응시화면=기존 OMR 재사용. name=Member.username 매칭, 동명이인/미존재 skip.
    응답: {success, assigned, updated_goal, skipped_dup, not_found, no_content, bad_key, results}
    """
    ok, reason = _check_token(request)
    if not ok:
        return JsonResponse({'success': False, 'error': reason}, status=403)
    try:
        data = json.loads(request.body or '{}')
        items = data.get('items') or []
    except (json.JSONDecodeError, TypeError):
        return HttpResponseBadRequest('Invalid JSON')

    User = get_user_model()
    assigned = updated_goal = skipped_dup = not_found = no_content = bad_key = 0
    results = []

    def goal_of(it):
        try:
            return int(it.get('goal'))
        except (TypeError, ValueError):
            return None

    def find_student(name):
        qs = User.objects.filter(username=name)
        return qs.count(), (qs.first() if qs.count() == 1 else None)

    for it in items:
        name = str(it.get('name') or '').strip()
        kind = str(it.get('kind') or 'round').strip().lower()
        exam_key = str(it.get('exam_key') or '').strip()
        if not name:
            continue

        if kind == 'type':
            # 유형별: QuestionData(같은 모집단)를 학년+유형태그 필터→색인순 재번호→범위 슬라이스.
            grade = str(it.get('grade') or '').strip()
            type_name = str(it.get('type_name') or '').strip()
            tags = [str(t).strip() for t in (it.get('types') or []) if str(t).strip()]
            try:
                start, end = int(it.get('start')), int(it.get('end'))
            except (TypeError, ValueError):
                start = end = 0
            if not (grade and tags and start and end and start <= end):
                bad_key += 1
                results.append({'name': name, 'kind': 'type', 'exam_key': exam_key,
                                'status': 'bad_type_params'})
                continue
            cnt, student = find_student(name)
            if cnt == 0:
                not_found += 1; results.append({'name': name, 'status': 'not_found'}); continue
            if cnt > 1:
                skipped_dup += 1; results.append({'name': name, 'status': 'dup_name'}); continue
            paper = get_or_create_mock_type_paper(grade, type_name, tags, start, end)
            qn = len(paper.get_questions())
            a, created = ExamAssignment.objects.get_or_create(
                paper=paper, student=student, defaults={'assigned_by': None})
            g = goal_of(it)
            if g is not None and a.daily_goal != g:
                a.daily_goal = g; a.save(update_fields=['daily_goal']); updated_goal += 1
            if created:
                assigned += 1
            if qn == 0:
                no_content += 1
            results.append({'name': name, 'kind': 'type', 'type_name': type_name,
                            'range': f'{start}-{end}', 'paper_id': paper.id, 'questions': qn,
                            'created': created,
                            'status': 'assigned' if qn else 'assigned_no_content'})
            continue

        # kind == 'round'
        m = _MOCK_KEY_ROUND_RE.match(exam_key)
        if not m:
            bad_key += 1
            results.append({'name': name, 'exam_key': exam_key, 'status': 'bad_exam_key'})
            continue
        year, grade, month = m.group(1), m.group(2), m.group(3)

        cnt, student = find_student(name)
        if cnt == 0:
            not_found += 1
            results.append({'name': name, 'exam_key': exam_key, 'status': 'not_found'})
            continue
        if cnt > 1:
            skipped_dup += 1
            results.append({'name': name, 'exam_key': exam_key, 'status': 'dup_name'})
            continue

        paper = get_or_create_mock_paper(grade, year, month)
        qn = len(paper.get_questions())
        a, created = ExamAssignment.objects.get_or_create(
            paper=paper, student=student, defaults={'assigned_by': None})
        g = goal_of(it)
        if g is not None and a.daily_goal != g:
            a.daily_goal = g
            a.save(update_fields=['daily_goal'])
            updated_goal += 1
        if created:
            assigned += 1
        if qn == 0:
            no_content += 1
        results.append({'name': name, 'exam_key': exam_key, 'paper_id': paper.id,
                        'questions': qn, 'created': created,
                        'status': 'assigned' if qn else 'assigned_no_content'})

    return JsonResponse({'success': True, 'assigned': assigned, 'updated_goal': updated_goal,
                         'skipped_dup': skipped_dup, 'not_found': not_found,
                         'no_content': no_content, 'bad_key': bad_key, 'results': results},
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
