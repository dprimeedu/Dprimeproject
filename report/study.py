"""학생 종합 학습 리포트 — 4과목(단어·요약문·영작·시험) 세션 자동 집계 (read-only).

report 앱의 수동 DailyRecord(교사 입력 + 카톡 PNG)와는 별개로,
학생이 홈페이지에서 실제로 푼 vocab/summary/writing/exam 세션을
'그날(started_at 기준)' 모아 보여준다. 새 모델/마이그레이션 없음.

USE_TZ=False 환경이라 DB 저장값이 naive datetime → started_at__date 로 그대로 비교.
"""
from collections import defaultdict
from datetime import timedelta

from vocab.models import VocabSession, VocabRangeTest, VocabAssignment
from summary.models import SummarySession, SummaryRangeTest, SummaryAssignment
from writing.models import WritingSession, WritingAttempt, DailyStudyGoal
from exam.models import ExamSession, ExamAssignment


# (key, 라벨, 학생 홈 URL)
SUBJECT_META = [
    ('vocab', '단어', '/training/vocab/'),
    ('summary', '요약문', '/training/summary/'),
    ('writing', '영작', '/training/writing/'),
    ('exam', '시험', '/training/exam/'),
]


# ─────────────────────────────────────────────
# 과목별 '한 칸' 요약 (보드 셀 + 상세 헤더 공용)
# ─────────────────────────────────────────────

def _vocab_cell(sessions):
    if not sessions:
        return {'did': False}
    finished = [s for s in sessions if s.finished_at]
    tests = [s for s in finished if s.mode == VocabSession.MODE_TEST]
    pcts = [s.percent for s in finished if s.total_count]
    best = max(pcts) if pcts else None
    parts = [f'{len(sessions)}회']
    if tests:
        parts.append(f'시험 {len(tests)}')
    if best is not None:
        parts.append(f'최고 {best}점')
    return {'did': True, 'n': len(sessions), 'done': len(finished),
            'tests': len(tests), 'best': best, 'pending': 0,
            'label': ' · '.join(parts)}


def _summary_cell(sessions):
    if not sessions:
        return {'did': False}
    graded = [s for s in sessions if s.status == SummarySession.STATUS_GRADED]
    pending = [s for s in sessions if s.status == SummarySession.STATUS_SUBMITTED]
    pcts = [s.percent for s in graded if s.total_blanks]
    best = max(pcts) if pcts else None
    parts = [f'{len(sessions)}회']
    if best is not None:
        parts.append(f'최고 {best}점')
    if pending:
        parts.append(f'채점대기 {len(pending)}')
    return {'did': True, 'n': len(sessions), 'done': len(graded),
            'best': best, 'pending': len(pending),
            'label': ' · '.join(parts)}


def _writing_cell(sessions):
    if not sessions:
        return {'did': False}
    finished = [s for s in sessions if s.finished_at]
    perfect = sum(s.perfect_sentences for s in sessions)
    score = sum(s.total_score for s in sessions)
    parts = [f'{len(sessions)}회']
    if perfect:
        parts.append(f'완벽 {perfect}문장')
    parts.append(f'{score}점')
    return {'did': True, 'n': len(sessions), 'done': len(finished),
            'perfect': perfect, 'score': score, 'best': None, 'pending': 0,
            'label': ' · '.join(parts)}


def _exam_cell(sessions):
    if not sessions:
        return {'did': False}
    graded = [s for s in sessions if s.status == ExamSession.STATUS_GRADED]
    pending = [s for s in sessions if s.status == ExamSession.STATUS_SUBMITTED]
    pcts = [s.percent for s in graded if s.total_questions]
    best = max(pcts) if pcts else None
    parts = [f'{len(sessions)}회']
    if best is not None:
        parts.append(f'최고 {best}점')
    if pending:
        parts.append(f'채점대기 {len(pending)}')
    return {'did': True, 'n': len(sessions), 'done': len(graded),
            'best': best, 'pending': len(pending),
            'label': ' · '.join(parts)}


def _bucket(qs):
    out = defaultdict(list)
    for s in qs:
        out[s.student_id].append(s)
    return out


# ─────────────────────────────────────────────
# 전체 학생 현황판 (그리드)
# ─────────────────────────────────────────────

def board(date):
    """{student_id: {'vocab':cell, 'summary':cell, 'writing':cell, 'exam':cell, 'active':bool}}

    그날 1과목이라도 푼 학생만 키로 들어감. 나머지는 뷰에서 '미접속' 처리.
    """
    v = _bucket(VocabSession.objects.filter(started_at__date=date).select_related('unit'))
    su = _bucket(SummarySession.objects.filter(started_at__date=date).select_related('unit'))
    w = _bucket(WritingSession.objects.filter(started_at__date=date).select_related('unit'))
    e = _bucket(ExamSession.objects.filter(started_at__date=date).select_related('paper'))

    out = {}
    for sid in set(v) | set(su) | set(w) | set(e):
        cells = {
            'vocab': _vocab_cell(v.get(sid, [])),
            'summary': _summary_cell(su.get(sid, [])),
            'writing': _writing_cell(w.get(sid, [])),
            'exam': _exam_cell(e.get(sid, [])),
        }
        cells['active'] = any(cells[k].get('did') for k, _, _ in SUBJECT_META)
        cells['subjects_done'] = sum(1 for k, _, _ in SUBJECT_META if cells[k].get('did'))
        cells['pending'] = sum(cells[k].get('pending', 0) for k, _, _ in SUBJECT_META)
        out[sid] = cells
    return out


# ─────────────────────────────────────────────
# 학생 1명 상세 (그날 + 주간 추이 + 다음 할 것)
# ─────────────────────────────────────────────

def _fmt_time(dt):
    return dt.strftime('%H:%M') if dt else ''


def _vocab_today(student, date):
    sessions = list(VocabSession.objects.filter(student=student, started_at__date=date)
                    .select_related('unit', 'range_test').order_by('started_at'))
    rows = []
    for s in sessions:
        rows.append({
            'time': _fmt_time(s.started_at),
            'title': s.unit.title,
            'mode': s.get_mode_display(),
            'is_test': s.mode == VocabSession.MODE_TEST,
            'done': bool(s.finished_at),
            'score_text': f'{s.correct_count}/{s.total_count} {s.percent}점' if s.total_count else '진행중',
            'percent': s.percent if s.total_count else None,
            'star_only': s.star_only,
        })
    return {'cell': _vocab_cell(sessions), 'rows': rows}


def _summary_today(student, date):
    sessions = list(SummarySession.objects.filter(student=student, started_at__date=date)
                    .select_related('unit').order_by('started_at'))
    rows = []
    for s in sessions:
        rows.append({
            'time': _fmt_time(s.started_at),
            'title': f'{s.unit.title} ({s.range_label})',
            'status': s.get_status_display(),
            'graded': s.status == SummarySession.STATUS_GRADED,
            'pending': s.status == SummarySession.STATUS_SUBMITTED,
            'score_text': f'{s.correct_count}/{s.total_blanks} {s.percent}점' if s.status == SummarySession.STATUS_GRADED else s.get_status_display(),
            'percent': s.percent if s.status == SummarySession.STATUS_GRADED and s.total_blanks else None,
        })
    return {'cell': _summary_cell(sessions), 'rows': rows}


def _writing_today(student, date):
    sessions = list(WritingSession.objects.filter(student=student, started_at__date=date)
                    .select_related('unit').order_by('started_at'))
    sess_ids = [s.id for s in sessions]
    attempts = list(WritingAttempt.objects.filter(session_id__in=sess_ids))
    total = len(attempts)
    correct = sum(1 for a in attempts if a.is_correct)
    accuracy = round(correct / total * 100, 1) if total else None
    rows = []
    for s in sessions:
        rows.append({
            'time': _fmt_time(s.started_at),
            'title': s.unit.title,
            'done': bool(s.finished_at),
            'score_text': f'완벽 {s.perfect_sentences}문장 · {s.total_score}점',
        })
    return {'cell': _writing_cell(sessions), 'rows': rows,
            'accuracy': accuracy, 'attempts': total}


def _exam_today(student, date):
    sessions = list(ExamSession.objects.filter(student=student, started_at__date=date)
                    .select_related('paper').order_by('started_at'))
    rows = []
    for s in sessions:
        rows.append({
            'time': _fmt_time(s.started_at),
            'title': s.title,
            'status': s.get_status_display(),
            'graded': s.status == ExamSession.STATUS_GRADED,
            'pending': s.status == ExamSession.STATUS_SUBMITTED,
            'score_text': s.score_text if s.status == ExamSession.STATUS_GRADED else s.get_status_display(),
            'percent': s.percent if s.status == ExamSession.STATUS_GRADED and s.total_questions else None,
        })
    return {'cell': _exam_cell(sessions), 'rows': rows}


def _week_trend(student, date):
    """최근 7일(date 포함) 과목별 세션 수 — 추이 막대용."""
    start = date - timedelta(days=6)
    counts = {k: defaultdict(int) for k, _, _ in SUBJECT_META}
    qsets = {
        'vocab': VocabSession.objects.filter(student=student, started_at__date__gte=start, started_at__date__lte=date),
        'summary': SummarySession.objects.filter(student=student, started_at__date__gte=start, started_at__date__lte=date),
        'writing': WritingSession.objects.filter(student=student, started_at__date__gte=start, started_at__date__lte=date),
        'exam': ExamSession.objects.filter(student=student, started_at__date__gte=start, started_at__date__lte=date),
    }
    for key, qs in qsets.items():
        for s in qs:
            counts[key][s.started_at.date()] += 1
    days = [start + timedelta(days=i) for i in range(7)]
    rows = []
    for d in days:
        # SUBJECT_META 순서대로 — 템플릿에서 그대로 순회
        per = [counts[k][d] for k, _, _ in SUBJECT_META]
        rows.append({'date': d, 'is_target': d == date,
                     'total': sum(per), 'per': per})
    return rows


def _next_actions(student, date):
    """다음에 뭘 할지 — '오늘 볼 TEST'(범위) 합격여부 + 미응시 배정."""
    out = {'vocab_tests': [], 'summary_tests': [], 'exam_pending': 0, 'goal': None}

    # 단어 오늘 볼 TEST (VocabRangeTest) — 그날 정식시험 합격 여부
    day_v = list(VocabSession.objects.filter(
        student=student, started_at__date=date,
        mode=VocabSession.MODE_TEST, finished_at__isnull=False))
    for rt in VocabRangeTest.objects.filter(student=student, is_active=True).select_related('unit'):
        matched = [s for s in day_v if s.range_test_id == rt.id]
        best = max((s.percent for s in matched), default=None)
        if best is None:
            status, ok = '미응시', False
        elif best >= rt.pass_threshold:
            status, ok = f'합격 ({best}점)', True
        else:
            status, ok = f'미달 ({best}점)', False
        out['vocab_tests'].append({
            'label': f'{rt.unit.title} {rt.range_label}', 'status': status, 'ok': ok})

    # 요약문 오늘 볼 TEST (SummaryRangeTest) — unit+범위로 매칭, 채점완료 점수
    day_s = list(SummarySession.objects.filter(student=student, started_at__date=date))
    for rt in SummaryRangeTest.objects.filter(student=student, is_active=True).select_related('unit'):
        matched = [s for s in day_s
                   if s.unit_id == rt.unit_id
                   and s.start_index == rt.start_index and s.end_index == rt.end_index]
        graded = [s for s in matched if s.status == SummarySession.STATUS_GRADED]
        pending = [s for s in matched if s.status == SummarySession.STATUS_SUBMITTED]
        if graded:
            best = max(s.percent for s in graded)
            status, ok = f'완료 ({best}점)', True
        elif pending:
            status, ok = '채점대기', False
        else:
            status, ok = '미응시', False
        out['summary_tests'].append({
            'label': f'{rt.unit.title} {rt.range_label}', 'status': status, 'ok': ok})

    # 배정됐지만 아직 채점완료 세션 없는 시험 수
    assigned_papers = set(ExamAssignment.objects.filter(student=student).values_list('paper_id', flat=True))
    if assigned_papers:
        graded_papers = set(ExamSession.objects.filter(
            student=student, paper_id__in=assigned_papers,
            status=ExamSession.STATUS_GRADED).values_list('paper_id', flat=True))
        out['exam_pending'] = len(assigned_papers - graded_papers)

    out['goal'] = DailyStudyGoal.objects.filter(student=student, date=date).first()
    return out


def student_day(student, date):
    """학생 1명의 그날 종합 리포트 데이터."""
    return {
        'vocab': _vocab_today(student, date),
        'summary': _summary_today(student, date),
        'writing': _writing_today(student, date),
        'exam': _exam_today(student, date),
        'week': _week_trend(student, date),
        'next': _next_actions(student, date),
    }
