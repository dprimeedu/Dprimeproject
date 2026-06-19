"""학생 종합 학습 리포트 — 4과목(단어·요약문·영작·시험) 세션 자동 집계 (read-only).

report 앱의 수동 DailyRecord(교사 입력 + 카톡 PNG)와는 별개로,
학생이 홈페이지에서 실제로 푼 vocab/summary/writing/exam 세션을
'그날(started_at 기준)' 모아 보여준다. 새 모델/마이그레이션 없음.

USE_TZ=False 환경이라 DB 저장값이 naive datetime → started_at__date 로 그대로 비교.
"""
from collections import defaultdict
from datetime import datetime, timedelta

from django.db.models import Count, Max
from django.utils import timezone

from vocab.models import (
    VocabSession, VocabAttempt, VocabRangeTest, VocabAssignment, StudentWordStar,
    WordCard,
)
from summary.models import (
    SummarySession, SummaryBlankAnswer, SummaryRangeTest, SummaryAssignment,
)
from writing.models import WritingSession, WritingAttempt, DailyStudyGoal
from exam.models import ExamSession, ExamAnswer, ExamAssignment
from grammar.models import GrammarSession


# (key, 라벨, 학생 홈 URL)
SUBJECT_META = [
    ('vocab', '단어', '/training/vocab/'),
    ('summary', '요약문', '/training/summary/'),
    ('writing', '영작', '/training/writing/'),
    ('grammar', '어법', '/training/grammar/'),
    ('exam', '정답입력', '/training/exam/'),
]

SUBJECT_LABEL = {k: lab for k, lab, _ in SUBJECT_META}

# 라이브 활동 판정 시간(분) — 이 시간 안에 마지막 활동이 있으면 '현재 활동 중'
LIVE_WINDOW_MIN = 5


def _now_naive():
    """USE_TZ=False 환경 호환: tz-aware 면 naive 로 변환."""
    n = timezone.now()
    return n.replace(tzinfo=None) if n.tzinfo else n


def current_activity_map(now=None):
    """{student_id: {'subject': key, 'subject_label': str, 'started_at': dt, 'last_active': dt}}

    학생별 '지금 활동 중'인 과목 — 최근 LIVE_WINDOW_MIN 분 내 활동이 가장 최근인 1과목.
    각 *Session 의 in_progress 상태 + 최근 답안/입력 시각으로 판정.
    """
    now = now or _now_naive()
    cutoff = now - timedelta(minutes=LIVE_WINDOW_MIN)

    # subject → {sid: (last_active, started_at)}
    per_subject = {}

    # 영작 — live_updated_at(타이핑 push)
    rows = (WritingSession.objects
            .filter(finished_at__isnull=True, live_updated_at__gte=cutoff)
            .values('student_id', 'started_at', 'live_updated_at'))
    m = {}
    for r in rows:
        sid, t, st = r['student_id'], r['live_updated_at'], r['started_at']
        cur = m.get(sid)
        if cur is None or t > cur[0]:
            m[sid] = (t, st)
    per_subject['writing'] = m

    # 단어 — VocabAttempt.created_at (Max via session)
    rows = (VocabSession.objects
            .filter(finished_at__isnull=True)
            .annotate(t=Max('attempts__created_at'))
            .filter(t__gte=cutoff)
            .values('student_id', 'started_at', 't'))
    m = {}
    for r in rows:
        sid, t, st = r['student_id'], r['t'], r['started_at']
        cur = m.get(sid)
        if cur is None or t > cur[0]:
            m[sid] = (t, st)
    per_subject['vocab'] = m

    # 요약문 — SummaryBlankAnswer.updated_at(Max via session)
    rows = (SummarySession.objects
            .filter(status=SummarySession.STATUS_IN_PROGRESS)
            .annotate(t=Max('blank_answers__updated_at'))
            .filter(t__gte=cutoff)
            .values('student_id', 'started_at', 't'))
    m = {}
    for r in rows:
        sid, t, st = r['student_id'], r['t'], r['started_at']
        cur = m.get(sid)
        if cur is None or t > cur[0]:
            m[sid] = (t, st)
    per_subject['summary'] = m

    # 어법 — GrammarAnswer.updated_at(Max via session)
    rows = (GrammarSession.objects
            .filter(status=GrammarSession.STATUS_IN_PROGRESS)
            .annotate(t=Max('answers__updated_at'))
            .filter(t__gte=cutoff)
            .values('student_id', 'started_at', 't'))
    m = {}
    for r in rows:
        sid, t, st = r['student_id'], r['t'], r['started_at']
        cur = m.get(sid)
        if cur is None or t > cur[0]:
            m[sid] = (t, st)
    per_subject['grammar'] = m

    # 시험 — ExamAnswer.created_at(Max via session; 업데이트는 잡지 못함 — 제한적)
    rows = (ExamSession.objects
            .filter(status=ExamSession.STATUS_IN_PROGRESS)
            .annotate(t=Max('answers__created_at'))
            .filter(t__gte=cutoff)
            .values('student_id', 'started_at', 't'))
    m = {}
    for r in rows:
        sid, t, st = r['student_id'], r['t'], r['started_at']
        cur = m.get(sid)
        if cur is None or t > cur[0]:
            m[sid] = (t, st)
    per_subject['exam'] = m

    # 학생별 가장 최근 활동 과목 1개
    result = {}
    for subject, mp in per_subject.items():
        for sid, (last_active, started_at) in mp.items():
            cur = result.get(sid)
            if cur is None or last_active > cur['last_active']:
                result[sid] = {
                    'subject': subject,
                    'subject_label': SUBJECT_LABEL.get(subject, subject),
                    'started_at': started_at,
                    'last_active': last_active,
                }
    return result


def fmt_hms(td):
    """timedelta → 'HH:MM:SS' (음수/None → '00:00:00')."""
    if td is None:
        return '00:00:00'
    s = max(0, int(td.total_seconds()))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f'{h:02d}:{m:02d}:{s:02d}'


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
    # 학생이 열기만 하고 입력 안 한(빈) 진행중 세션은 제외 — 현황판에 '안 본' 차시 안 보이게
    sessions = [s for s in sessions
                if not (s.status == SummarySession.STATUS_IN_PROGRESS
                        and getattr(s, '_ans', None) == 0)]
    if not sessions:
        return {'did': False}
    graded = [s for s in sessions if s.status == SummarySession.STATUS_GRADED]
    pending = [s for s in sessions if s.status == SummarySession.STATUS_SUBMITTED]
    pcts = [s.percent for s in graded if s.total_blanks]
    best = max(pcts) if pcts else None
    # 차시별(10문제 청크) 상세 — 범위 순으로 1차시·2차시·3차시 …
    chashi = []
    for s in sorted(sessions, key=lambda x: ((x.start_index or 0), x.started_at)):
        if s.status == SummarySession.STATUS_GRADED:
            st, cls = f'채점완료·{s.percent}점', 'graded'
        elif s.status == SummarySession.STATUS_SUBMITTED:
            st, cls = '제출·채점대기', 'pending'
        else:
            st, cls = '시험중', 'progress'
        chashi.append({'no': s.chunk_no, 'range': s.range_label,
                       'status': st, 'cls': cls, 'sid': s.id})
    parts = [f'{len(sessions)}회']
    if best is not None:
        parts.append(f'최고 {best}점')
    if pending:
        parts.append(f'채점대기 {len(pending)}')
    return {'did': True, 'n': len(sessions), 'done': len(graded),
            'best': best, 'pending': len(pending), 'chashi': chashi,
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
    # 미제출(in_progress) 전부 제외 — 채점 창구 의도. 1~2개만 답하고 나간 것도 보이지 않게.
    sessions = [s for s in sessions if s.status != ExamSession.STATUS_IN_PROGRESS]
    # 같은 시험지 여러 시도 → 최신 1개만 (재응시 통합)
    by_paper = {}
    for s in sessions:
        cur = by_paper.get(s.paper_id)
        if cur is None or s.started_at > cur.started_at:
            by_paper[s.paper_id] = s
    sessions = sorted(by_paper.values(), key=lambda x: x.started_at)
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
    detail = []
    for s in sessions:
        src = s.paper.source
        is_mocklike = src in ('mock', 'mock_type')
        cls = status = ''
        if s.status == ExamSession.STATUS_GRADED:
            if is_mocklike:
                # 모의/유형 빨파 워크플로 4단계: 공개대기 → 빨파채점대기 → 최종확인대기 → 최종완료
                if not s.redblue_released:
                    cls, status = 'release', f'{s.percent}점·공개대기'
                elif not s.student_redblue_done:
                    cls, status = 'wait_student', f'{s.percent}점·학생 빨파채점 중'
                elif not s.teacher_final_confirmed:
                    cls, status = 'finalize', f'{s.percent}점·최종확인 대기'
                else:
                    cls, status = 'r2', f'{s.percent}점·완료'
            else:
                # 내신: 자동채점 후 선생님 확인 여부만
                if not s.teacher_checked:
                    cls, status = 'pending', f'{s.percent}점·미확인'
                else:
                    cls, status = 'graded', f'{s.percent}점'
        else:
            cls, status = 'inprog', s.get_status_display()
        detail.append({
            'sid': s.id, 'title': s.title, 'status': status, 'cls': cls,
            'source': src,
            'can_release': is_mocklike and not s.redblue_released
                           and s.status == ExamSession.STATUS_GRADED,
            'can_finalize': is_mocklike and s.redblue_released
                            and s.student_redblue_done and not s.teacher_final_confirmed,
        })
    return {'did': True, 'n': len(sessions), 'done': len(graded),
            'best': best, 'pending': len(pending),
            'label': ' · '.join(parts),
            'detail': detail}


def _grammar_cell(sessions):
    """어법 — 모의고사식 다차시 흐름(1차→2차…, set_no로 이어짐).

    세트(set_no)별 '현재 차시'의 상태를 칩으로:
      시험중(in_progress) / 제출·채점대기(submitted) / 채점완료(graded).
    """
    if not sessions:
        return {'did': False}
    # 세트별로 가장 최근 차시 1개만 — 현재 진행 상태 표시(1차 채점→2차 시험중 등)
    by_set = {}
    for s in sessions:
        key = (s.unit_id, s.set_no)
        cur = by_set.get(key)
        if cur is None or (s.round_no or 1, s.started_at) > (cur.round_no or 1, cur.started_at):
            by_set[key] = s
    sessions = list(by_set.values())
    graded = [s for s in sessions if s.status == GrammarSession.STATUS_GRADED]
    pending = [s for s in sessions if s.status == GrammarSession.STATUS_SUBMITTED]
    pcts = [s.percent for s in graded if s.total_count]
    best = max(pcts) if pcts else None
    detail = []
    seen = set()
    for s in sorted(sessions, key=lambda x: ((x.set_no or 0), (x.round_no or 1))):
        rd = s.round_no or 1
        if s.status == GrammarSession.STATUS_GRADED:
            st, cls, link = f'{rd}차 채점완료·{s.percent}점', 'graded', True
        elif s.status == GrammarSession.STATUS_SUBMITTED:
            st, cls, link = f'{rd}차 제출·채점대기', 'pending', True
        else:
            st, cls, link = f'{rd}차 시험중', 'progress', False
        # 화면 라벨이 동일한 칩은 1개만 — 서로 다른 단원이라도 (세트번호·차시·상태)가
        # 같으면 사용자에겐 같은 칩으로 보이므로 중복 노출 방지.
        key = (s.range_label, st)
        if key in seen:
            continue
        seen.add(key)
        detail.append({'range': s.range_label, 'status': st, 'cls': cls,
                       'sid': s.id, 'link': link})
    parts = [f'{len(sessions)}세트']
    if best is not None:
        parts.append(f'최고 {best}점')
    if pending:
        parts.append(f'채점대기 {len(pending)}')
    return {'did': True, 'n': len(sessions), 'done': len(graded),
            'best': best, 'pending': len(pending), 'detail': detail,
            'label': ' · '.join(parts)}


def _bucket(qs):
    out = defaultdict(list)
    for s in qs:
        out[s.student_id].append(s)
    return out


# ─────────────────────────────────────────────
# 전체 학생 현황판 (그리드)
# ─────────────────────────────────────────────

def _summary_today_tests(range_tests, sessions):
    """학생의 활성 '오늘 볼 요약문 TEST'(SummaryRangeTest) — 단원·범위·응시여부.
    단어TEST 표시 패턴과 동일. 합격선 없음 — 응시/미응시만 구분."""
    seen = set()
    deduped = []
    for rt in range_tests:
        key = (rt.source_label or rt.unit.title, rt.start_index, rt.end_index)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(rt)
    out = []
    for rt in deduped:
        matched = [s for s in sessions
                   if s.unit_id == rt.unit_id
                   and s.start_index == rt.start_index
                   and s.end_index == rt.end_index
                   and s.status != SummarySession.STATUS_IN_PROGRESS]
        best = max((s.percent for s in matched if s.total_blanks), default=None)
        if best is None:
            status, ok = '미응시', None
        else:
            status, ok = f'응시 {best}점', True
        rng = f'{rt.start_index}~{rt.end_index}' if rt.start_index and rt.end_index else ''
        out.append({'book': rt.source_label or rt.unit.title, 'range': rng,
                    'status': status, 'ok': ok})
    return out


def _vocab_today_tests(range_tests, day_test_sessions):
    """학생의 활성 단어 '오늘 볼 TEST'(VocabRangeTest) — 단어장·범위·합격여부.
    학생관리표의 '단어시험결과 / 단어장 / 오늘 범위' 칸에 대응."""
    # 같은 단어장(source_label)에 여러 범위가 있으면 가장 오래된(start_index 최소) 1개만
    # 예: 401-500 + 301-400 + 1-100 → 1-100 만 노출 (학생이 먼저 끝낼 범위)
    by_label = {}
    for rt in range_tests:
        label = rt.source_label or rt.unit.title
        cur = by_label.get(label)
        if cur is None or rt.start_index < cur.start_index:
            by_label[label] = rt
    range_tests = list(by_label.values())
    out = []
    for rt in range_tests:
        matched = [s for s in day_test_sessions if s.range_test_id == rt.id]
        best = max((s.percent for s in matched), default=None)
        if best is None:
            status, ok = '미응시', None
        elif best >= rt.pass_threshold:
            status, ok = f'합격 {best}', True
        else:
            status, ok = f'미달 {best}', False
        rng = f'{rt.start_index}~{rt.end_index}' if rt.start_index and rt.end_index else ''
        out.append({'book': rt.source_label or rt.unit.title, 'range': rng,
                    'status': status, 'ok': ok, 'rt_id': rt.id})
    return out


def board(date):
    """{student_id: {'vocab':cell, 'summary':cell, 'writing':cell, 'exam':cell, 'active':bool}}

    그날 1과목이라도 푼 학생만 키로 들어감. 나머지는 뷰에서 '미접속' 처리.
    단, 시험은 '선생님 처리 대기'(모의/유형 빨파 미공개 · 내신 미확인)는 날짜 무관 표시.
    """
    from django.db.models import Q
    v = _bucket(VocabSession.objects.filter(started_at__date=date).select_related('unit', 'range_test'))
    su = _bucket(SummarySession.objects.filter(started_at__date=date)
                 .select_related('unit').annotate(_ans=Count('blank_answers')))
    w = _bucket(WritingSession.objects.filter(started_at__date=date).select_related('unit'))
    e = _bucket(ExamSession.objects.filter(started_at__date=date).select_related('paper'))
    g = _bucket(GrammarSession.objects.filter(started_at__date=date).select_related('unit'))

    # 시험 — 날짜 무관 시험란 노출. 모의/유형은 '선생님 최종확인 전' 모두(공개대기/빨파채점대기/
    # 최종확인 대기 단계), 내신은 한 세트 부분입력 패턴이라 채점완료 세션을 항상 표시.
    e_pending = defaultdict(list)
    for s in (ExamSession.objects
              .filter(status=ExamSession.STATUS_GRADED)
              .filter(Q(paper__source__in=['mock', 'mock_type'], teacher_final_confirmed=False)
                      | Q(paper__source='naesin'))
              .select_related('paper')):
        e_pending[s.student_id].append(s)

    # 응시 시작 전 배정(=자동 배정된 다음 회차/세트 포함) — 정답입력 cell에 '미응시' 배지.
    # 학생 (paper 단위)별로 한 번이라도 세션이 있었으면 제외.
    sessioned_papers = defaultdict(set)
    for r in ExamSession.objects.values_list('student_id', 'paper_id'):
        sessioned_papers[r[0]].add(r[1])
    assigned_only = defaultdict(list)
    for a in ExamAssignment.objects.select_related('paper'):
        if a.paper_id not in sessioned_papers.get(a.student_id, set()):
            assigned_only[a.student_id].append(a)

    # 학생 개인 낱말카드 단어 수 — 단어장이 따로 지정 안 됐어도 직접 모은 단어들.
    # word & meaning 둘 다 채워진 것만 카운트(빈 칸 제외). 단어 cell에 '개인 단어 N개' 배지.
    personal_words = defaultdict(int)
    for r in (WordCard.objects.exclude(word='').exclude(meaning='')
              .values('card_set__student_id').annotate(c=Count('id'))):
        personal_words[r['card_set__student_id']] = r['c']

    # 오늘 볼 단어 TEST(VocabRangeTest) — 학생관리자료 '내신단어TEST' 지정만(퀴즈렛 자동청크 제외).
    # vocab '오늘 단어 TEST' 페이지와 동일 기준. 접속 안 한 학생도 표시 위해 별도 집계.
    vrt = defaultdict(list)
    for rt in VocabRangeTest.objects.filter(is_active=True, source_label='내신단어TEST').select_related('unit'):
        vrt[rt.student_id].append(rt)

    # 오늘 볼 요약문 TEST(SummaryRangeTest) — 접속 안 한 학생도 미응시 표시
    srt = defaultdict(list)
    for rt in SummaryRangeTest.objects.filter(is_active=True).select_related('unit'):
        srt[rt.student_id].append(rt)

    out = {}
    for sid in (set(v) | set(su) | set(w) | set(e) | set(g) | set(vrt) | set(srt)
                | set(e_pending) | set(assigned_only) | set(personal_words)):
        vs = v.get(sid, [])
        # 시험: 그날 세션 + 처리 대기 세션(중복 session.id 제거) 합쳐 표시
        e_today = e.get(sid, [])
        seen_eids = {s.id for s in e_today}
        e_combined = e_today + [s for s in e_pending.get(sid, []) if s.id not in seen_eids]
        cells = {
            'vocab': _vocab_cell(vs),
            'summary': _summary_cell(su.get(sid, [])),
            'writing': _writing_cell(w.get(sid, [])),
            'grammar': _grammar_cell(g.get(sid, [])),
            'exam': _exam_cell(e_combined),
        }
        # 응시 시작 전 배정 — 정답입력 cell에 표시(클릭 → 응시 시작 페이지).
        cells['exam']['assigned_only'] = [
            {'paper_id': a.paper_id, 'title': a.paper.resolved_title}
            for a in assigned_only.get(sid, [])
        ]
        if cells['exam']['assigned_only']:
            cells['exam']['did'] = True
        # 학생 개인 단어장(낱말카드) — 단어장 미지정이어도 모은 단어 수 표시.
        cells['vocab']['personal_count'] = personal_words.get(sid, 0)
        if cells['vocab']['personal_count']:
            cells['vocab']['did'] = True
        # 단어 '오늘 볼 TEST' 범위/합격 — 정식시험(MODE_TEST) 완료 세션 기준
        cells['vocab']['tests'] = _vocab_today_tests(
            vrt.get(sid, []),
            [s for s in vs if s.mode == VocabSession.MODE_TEST and s.finished_at])
        # 요약문 '오늘 볼 TEST' — 동일 단원·범위 세션 응시 여부
        cells['summary']['tests'] = _summary_today_tests(
            srt.get(sid, []), su.get(sid, []))
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
                    .select_related('unit').annotate(_ans=Count('blank_answers')).order_by('started_at'))
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
    for rt in VocabRangeTest.objects.filter(
            student=student, is_active=True, source_label='내신단어TEST').select_related('unit'):
        matched = [s for s in day_v if s.range_test_id == rt.id]
        best = max((s.percent for s in matched), default=None)
        if best is None:
            status, ok = '미응시', False
        elif best >= rt.pass_threshold:
            status, ok = f'합격 ({best}점)', True
        else:
            status, ok = f'미달 ({best}점)', False
        _rng = f'{rt.start_index}~{rt.end_index}' if rt.start_index and rt.end_index else ''
        out['vocab_tests'].append({
            'label': f'{rt.source_label or rt.unit.title} {_rng}'.strip(), 'status': status, 'ok': ok})

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


# ─────────────────────────────────────────────
# 심층 분석 — 시도 단위(오답/약점) 파고들기
# ─────────────────────────────────────────────

def _vocab_analysis(student, date):
    """오늘 단어 오답·반복오답·망설인 단어."""
    sess_ids = list(VocabSession.objects
                    .filter(student=student, started_at__date=date)
                    .values_list('id', flat=True))
    attempts = list(VocabAttempt.objects.filter(session_id__in=sess_ids)
                    .select_related('word'))
    if not attempts:
        return None

    by_word = {}
    for a in attempts:
        w = by_word.setdefault(a.word_id, {
            'word': a.word.word, 'meaning': a.word.meaning,
            'wrong': 0, 'total': 0, 'inputs': []})
        w['total'] += 1
        if not a.is_correct:
            w['wrong'] += 1
            if a.input_value and a.input_value not in w['inputs']:
                w['inputs'].append(a.input_value)
    wrong_words = [w for w in by_word.values() if w['wrong'] > 0]
    wrong_words.sort(key=lambda x: (-x['wrong'], x['word']))
    for w in wrong_words:
        w['input_text'] = ', '.join(w['inputs'][:3]) if w['inputs'] else '(무응답)'
        w['repeat'] = w['wrong'] >= 2

    timed = [(a.time_taken_seconds, a.word.word, a.word.meaning)
             for a in attempts if a.time_taken_seconds and a.time_taken_seconds > 0]
    timed.sort(key=lambda x: -x[0])
    slowest = [{'word': w, 'meaning': m, 'sec': t} for t, w, m in timed[:5]]
    avg_time = round(sum(t for t, _, _ in timed) / len(timed), 1) if timed else None

    return {
        'wrong_words': wrong_words[:30],
        'wrong_total': len(wrong_words),
        'repeat_total': sum(1 for w in wrong_words if w['repeat']),
        'attempt_count': len(attempts),
        'slowest': slowest,
        'avg_time': avg_time,
        'star_count': StudentWordStar.objects.filter(student=student).count(),
    }


def _summary_analysis(student, date):
    """오늘 요약문 빈칸 오답 + 한글뜻 의존도/1차 자동정답률."""
    sess_ids = list(SummarySession.objects
                    .filter(student=student, started_at__date=date)
                    .values_list('id', flat=True))
    answers = list(SummaryBlankAnswer.objects.filter(session_id__in=sess_ids)
                   .select_related('problem'))
    if not answers:
        return None

    wrong, auto_first, korean_used, graded = [], 0, 0, 0
    for a in answers:
        if a.first_auto_correct:
            auto_first += 1
        if a.korean_shown:
            korean_used += 1
        if a.admin_verdict:
            graded += 1
            if a.admin_verdict == 'X':
                wrong.append({
                    'index': a.problem.index,
                    'blank': a.get_blank_display(),
                    'correct': a.correct_answer or a.problem.answer_for(a.blank),
                    'student': a.final_input or '(무응답)',
                    'korean': a.problem.korean_for(a.blank),
                })
    wrong.sort(key=lambda x: (x['index'], x['blank']))
    total = len(answers)
    return {
        'wrong': wrong[:30],
        'wrong_total': len(wrong),
        'graded': graded,
        'auto_first_pct': round(auto_first / total * 100) if total else 0,
        'korean_pct': round(korean_used / total * 100) if total else 0,
        'total_blanks': total,
    }


def _writing_analysis(student, date):
    """오늘 영작 첫시도 정답률·힌트 의존도 (상세는 영작 리포트 링크)."""
    sess_ids = list(WritingSession.objects
                    .filter(student=student, started_at__date=date)
                    .values_list('id', flat=True))
    attempts = list(WritingAttempt.objects.filter(session_id__in=sess_ids))
    if not attempts:
        return None

    # 단어칸 단위 1차 시도
    first_by_word = {}
    for a in attempts:
        key = (a.session_id, a.problem_id, a.word_index)
        cur = first_by_word.get(key)
        if cur is None or a.attempt_num < cur.attempt_num:
            first_by_word[key] = a
    firsts = list(first_by_word.values())
    n = len(firsts)
    first_perfect = sum(1 for a in firsts
                        if a.attempt_num == 1 and a.hint_level == 0 and a.is_correct)
    used_hint = sum(1 for a in attempts if a.hint_level and a.hint_level > 0)
    return {
        'word_blanks': n,
        'first_perfect_pct': round(first_perfect / n * 100) if n else 0,
        'hint_pct': round(used_hint / len(attempts) * 100) if attempts else 0,
        'attempt_count': len(attempts),
    }


def _exam_analysis(student, date):
    """오늘 시험 오답 문항 + 유형별 정답률(약한 유형 진단)."""
    sess_ids = list(ExamSession.objects
                    .filter(student=student, started_at__date=date,
                            status=ExamSession.STATUS_GRADED)
                    .values_list('id', flat=True))
    answers = list(ExamAnswer.objects.filter(session_id__in=sess_ids))
    if not answers:
        return None

    wrong = [{
        'number': a.number, 'qtype': a.qtype or '-',
        'student': a.student_choice or '(무응답)', 'correct': a.correct_answer,
    } for a in answers if not a.is_correct]
    wrong.sort(key=lambda x: x['number'])

    by_type = {}
    for a in answers:
        t = a.qtype or '기타'
        bt = by_type.setdefault(t, {'qtype': t, 'correct': 0, 'total': 0})
        bt['total'] += 1
        if a.is_correct:
            bt['correct'] += 1
    type_stats = []
    for bt in by_type.values():
        bt['pct'] = round(bt['correct'] / bt['total'] * 100) if bt['total'] else 0
        type_stats.append(bt)
    type_stats.sort(key=lambda x: (x['pct'], -x['total']))  # 약한 유형 먼저

    return {
        'wrong': wrong[:40], 'wrong_total': len(wrong),
        'type_stats': type_stats, 'total': len(answers),
    }


def _diagnosis(v, s, w, e):
    """과목 분석들을 묶어 '오늘의 약점' 한 줄 진단 + 추천."""
    weak, tips = [], []
    if v and v['wrong_total']:
        weak.append(f"단어 오답 {v['wrong_total']}개"
                    + (f" (반복 {v['repeat_total']})" if v['repeat_total'] else ''))
        tips.append('틀린 단어 ⭐별표 후 별표 집중훈련')
    if s and s['wrong_total']:
        weak.append(f"요약문 빈칸 오답 {s['wrong_total']}개")
        tips.append('틀린 요약문 범위 재시험')
    if s and s['total_blanks'] and s['korean_pct'] >= 50:
        weak.append(f"요약문 한글뜻 의존 {s['korean_pct']}%")
    if w and w['word_blanks'] and w['first_perfect_pct'] < 60:
        weak.append(f"영작 첫시도 정답률 {w['first_perfect_pct']}%")
    if e and e['type_stats']:
        worst = e['type_stats'][0]
        if worst['pct'] < 70 and worst['total'] >= 2:
            weak.append(f"시험 '{worst['qtype']}' {worst['pct']}%")
            tips.append(f"'{worst['qtype']}' 유형 보강")
    return {'weak': weak, 'tips': tips}


def _praise_and_focus(day, va, sa, wa, ea):
    """학생용 보고서 — 오늘 '잘한 점'과 '다음에 더 힘낼 점'을 말로 풀어준다.

    day: 과목별 today dict({'cell','rows',...}). va/sa/wa/ea: 분석 dict(없으면 None).
    """
    good, focus = [], []
    vc, sc, wc, ec = (day['vocab']['cell'], day['summary']['cell'],
                      day['writing']['cell'], day['exam']['cell'])

    # ── 잘한 점 ──
    if vc.get('did') and vc.get('best') is not None and vc['best'] >= 80:
        good.append(f"단어 시험 {vc['best']}점 — 정확해요!")
    if va and va['attempt_count'] and va['wrong_total'] == 0:
        good.append("단어를 하나도 안 틀렸어요. 완벽! 💯")
    if sc.get('did') and sc.get('best') is not None and sc['best'] >= 80:
        good.append(f"요약문 {sc['best']}점 — 잘했어요!")
    if sa and sa['total_blanks'] and sa['auto_first_pct'] >= 70:
        good.append(f"요약문을 한글뜻 없이 {sa['auto_first_pct']}%나 맞혔어요. 실력이 붙었네요!")
    if wc.get('did') and wc.get('perfect'):
        good.append(f"영작 완벽 문장 {wc['perfect']}개 작성! ✍️")
    if wa and wa['word_blanks'] and wa['first_perfect_pct'] >= 70:
        good.append(f"영작 첫 시도 정답률 {wa['first_perfect_pct']}% — 힌트 없이도 척척!")
    if ec.get('did') and ec.get('best') is not None and ec['best'] >= 80:
        good.append(f"시험 {ec['best']}점, 좋아요!")
    if ea and ea['type_stats']:
        perfect_types = [t for t in ea['type_stats'] if t['pct'] == 100 and t['total'] >= 2]
        if perfect_types:
            good.append(f"시험 '{perfect_types[0]['qtype']}' 유형은 다 맞혔어요!")
    done = sum(1 for c in (vc, sc, wc, ec) if c.get('did'))
    if done >= 3:
        good.append(f"오늘 {done}과목이나 꾸준히 했어요. 성실함이 최고의 무기예요!")

    # ── 다음에 더 힘낼 점 ──
    if va and va['wrong_total']:
        msg = f"단어 {va['wrong_total']}개를 더 외워보기"
        if va['repeat_total']:
            msg += f" (특히 반복해서 틀린 {va['repeat_total']}개는 ⭐별표!)"
        focus.append(msg)
    if sa and sa['wrong_total']:
        focus.append(f"요약문 빈칸 {sa['wrong_total']}개 다시 보기")
    if sa and sa['total_blanks'] and sa['korean_pct'] >= 50:
        focus.append(f"요약문은 한글뜻 보기 전에 영어를 먼저 떠올려보기 (오늘 한글뜻 {sa['korean_pct']}% 사용)")
    if wa and wa['word_blanks'] and wa['first_perfect_pct'] < 60:
        focus.append(f"영작은 힌트를 조금씩 줄여보기 (첫 시도 정답률 {wa['first_perfect_pct']}%)")
    if ea and ea['type_stats']:
        worst = ea['type_stats'][0]
        if worst['pct'] < 70 and worst['total'] >= 2:
            focus.append(f"시험 '{worst['qtype']}' 유형을 집중 연습 (오늘 {worst['pct']}%)")
    # 오늘 안 한 과목 권유 (분석 데이터 없는 = 미실시)
    if not vc.get('did'):
        focus.append("오늘 단어 훈련도 도전해보기")
    elif not sc.get('did'):
        focus.append("요약문도 한 세트 풀어보기")

    # 비어있을 때 기본 메시지
    if not good and done:
        good.append("오늘도 학습을 시작한 것 자체가 멋져요! 👏")
    if not focus:
        focus.append("지금처럼만 꾸준히 하면 충분해요. 내일도 화이팅!")

    return {'good': good[:5], 'focus': focus[:5]}


def student_day(student, date):
    """학생 1명의 그날 종합 리포트 데이터."""
    va = _vocab_analysis(student, date)
    sa = _summary_analysis(student, date)
    wa = _writing_analysis(student, date)
    ea = _exam_analysis(student, date)
    day = {
        'vocab': _vocab_today(student, date),
        'summary': _summary_today(student, date),
        'writing': _writing_today(student, date),
        'exam': _exam_today(student, date),
    }
    day['week'] = _week_trend(student, date)
    day['next'] = _next_actions(student, date)
    day['analysis'] = {
        'vocab': va, 'summary': sa, 'writing': wa, 'exam': ea,
        'diagnosis': _diagnosis(va, sa, wa, ea),
    }
    day['feedback'] = _praise_and_focus(day, va, sa, wa, ea)
    return day
