"""DailyRecord → 리포트 row 생성 / 연속(streak) 계산 / PNG 생성·저장."""
import math

from django.core.files.base import ContentFile
from django.utils import timezone

from .models import DailyRecord, StudentInfo
from .report_image import (
    render_report_png, get_att_status, convert_achievement_combined,
)


def _ach_row(rec):
    """convert_achievement_combined 가 보는 키만 채운 보조 dict."""
    return {
        '과제1달성률': rec.hw1_rate,
        '과제2달성률': rec.hw2_rate,
        '문법과제결과': rec.grammar_hw_result,
    }


def _trailing(seq, pred):
    c = 0
    for v in reversed(seq):
        if pred(v):
            c += 1
        else:
            break
    return c


def compute_streaks(student, upto_date):
    """upto_date(포함)까지 학생 기록으로 연속 출석/지각/결석/미이행/달성 계산."""
    recs = list(DailyRecord.objects.filter(student=student, date__lte=upto_date)
                .order_by('date', 'id'))
    att = [get_att_status(r.attendance) for r in recs]
    ach = [convert_achievement_combined(_ach_row(r)) for r in recs]

    def is_miss(v):
        return v is not None and not math.isnan(v) and v < 100

    def is_done(v):
        return v is not None and not math.isnan(v) and v >= 100

    return {
        '연속출석': _trailing(att, lambda s: s == '출석'),
        '연속지각': _trailing(att, lambda s: s == '지각'),
        '연속결석': _trailing(att, lambda s: s == '결석'),
        '연속미이행': _trailing(ach, is_miss),
        '연속달성': _trailing(ach, is_done),
    }


def build_row(record):
    """DailyRecord → render_report_png 가 받는 한글 키 dict."""
    try:
        info = record.student.report_info
        school_grade = info.school_grade
    except StudentInfo.DoesNotExist:
        school_grade = ''

    row = {
        '이름': record.student.username,
        '학교학년': school_grade,
        '출석': record.attendance,
        '날짜_parsed': record.date,
        '어법/요약문결과': record.grammar_summary_result,
        '단어시험결과': record.vocab_result,
        '영작시험결과': record.writing_result,
        '독해과제1결과': record.reading_hw1_result,
        '독해과제2결과': record.reading_hw2_result,
        '문법과제결과': record.grammar_hw_result,
        '문법번호': record.grammar_no,
        '오늘독해과제1': record.today_reading1,
        '오늘독해과제2': record.today_reading2,
        '과제1달성률': record.hw1_rate,
        '과제2달성률': record.hw2_rate,
        '다음독해과제1': record.next_reading1,
        '다음독해과제2': record.next_reading2,
        '다음문법과제': record.next_grammar,
        '단어장': record.vocab_book,
        '숙제\n시작.1': record.vocab_hw_start,
        '숙제\n끝.1': record.vocab_hw_end,
        '선생님의 한마디': record.teacher_comment,
        'is_new_vocab': record.is_new_vocab,
    }
    row['출석_상태'] = get_att_status(record.attendance)
    row.update(compute_streaks(record.student, record.date))
    row['숙제달성률_num'] = convert_achievement_combined(row)
    return row


def generate_for_record(record):
    """리포트 PNG 생성 후 record.report_image 에 저장. 저장된 record 반환."""
    png = render_report_png(build_row(record))
    fname = f"report_{record.student_id}_{record.date:%Y%m%d}.png"
    record.report_image.save(fname, ContentFile(png), save=False)
    record.report_generated_at = timezone.now()
    record.save(update_fields=['report_image', 'report_generated_at'])
    return record


def autofill_results(date, overwrite=False):
    """해당 날짜의 vocab(단어시험)·summary(요약문)·writing(영작) 세션 점수를
    DailyRecord 의 시험결과 필드에 자동 입력.

    overwrite=False 면 비어있는 필드만 채움(교사 수동입력 보존).
    같은 날 세션이 여럿이면 최신(started_at 내림차순 기본)만 반영.
    반환: 채운/생성한 DailyRecord 수.
    """
    from vocab.models import VocabSession
    from summary.models import SummarySession
    from writing.models import WritingSession

    touched = {}
    seen = set()

    def get_rec(student_id):
        if student_id not in touched:
            rec, _ = DailyRecord.objects.get_or_create(student_id=student_id, date=date)
            touched[student_id] = rec
        return touched[student_id]

    def setf(student_id, field, val):
        if not val:
            return
        key = (student_id, field)
        if key in seen:
            return
        rec = get_rec(student_id)
        if overwrite or not getattr(rec, field):
            setattr(rec, field, val)
            seen.add(key)

    # 단어 정식시험 (완료)
    for s in (VocabSession.objects
              .filter(mode=VocabSession.MODE_TEST, finished_at__date=date)
              .order_by('-started_at')):
        setf(s.student_id, 'vocab_result', f'{s.correct_count}/{s.total_count} {s.percent}점')

    # 요약문완성 (채점 완료)
    for s in (SummarySession.objects
              .filter(status=SummarySession.STATUS_GRADED, submitted_at__date=date)
              .order_by('-started_at')):
        setf(s.student_id, 'grammar_summary_result', f'{s.correct_count}/{s.total_blanks} {s.percent}점')

    # 영작 (완료) — correct/total 없음 → 완성문장/점수 표기
    for s in (WritingSession.objects
              .filter(finished_at__date=date)
              .order_by('-started_at')):
        setf(s.student_id, 'writing_result', f'{s.perfect_sentences}문장 ({s.total_score}점)')

    # 모의고사 (채점완료) → 독해과제1결과 (Apps Script 모고 채점과 동일 위치).
    # 내신(naesin)은 카테고리가 독해/문법 혼합이라 매핑 보류 → 교사 입력.
    from exam.models import ExamSession, ExamPaper
    for s in (ExamSession.objects
              .filter(status=ExamSession.STATUS_GRADED, submitted_at__date=date,
                      paper__source=ExamPaper.SOURCE_MOCK)
              .select_related('paper').order_by('-started_at')):
        setf(s.student_id, 'reading_hw1_result',
             f'{s.paper.resolved_title}: {s.correct_count}/{s.total_questions} {s.percent}점')

    for rec in touched.values():
        rec.save()
    return len(touched)


def generate_for_date(date):
    """해당 날짜 전체 DailyRecord 리포트 생성. (생성수, 오류목록) 반환."""
    ok, errors = 0, []
    for rec in DailyRecord.objects.filter(date=date).select_related('student'):
        try:
            generate_for_record(rec)
            ok += 1
        except Exception as e:  # noqa: BLE001
            errors.append(f'{rec.student.username}: {e}')
    return ok, errors
