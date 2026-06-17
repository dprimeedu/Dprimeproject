"""학습관리·일일리포트 뷰.

- 교사 일일 입력 그리드(학생관리표 대체) → DailyRecord 저장
- 리포트 PNG 생성 / 목록
- 하이브리드 카톡용 API: 오늘 생성된 리포트 목록(대화방명+이미지URL)을 회사 PC가 받아감
"""
import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

from writing.views import is_teacher, teacher_required

from .models import DailyRecord, StudentInfo
from .services import generate_for_record, generate_for_date, autofill_results
from . import study


# 일일 입력 그리드 필드 (키, 라벨, 타입)
# 학생관리표(0. 학생관리자료.xlsx) 한 행 = DailyRecord 한 건. 엑셀 열 순서에 맞춰 정렬.
GRID_FIELDS = [
    ('attendance', '출석', 'att'),
    # 4과목 시험 결과
    ('grammar_summary_result', '어법/요약문', 'text'),
    ('vocab_result', '단어시험', 'text'),
    ('writing_result', '영작시험', 'text'),
    ('reading_result', 'TEST결과', 'text'),
    # 과제 달성률 · 순위
    ('hw1_rate', '과제1달성률', 'text'),
    ('hw2_rate', '과제2달성률', 'text'),
    ('hw_rank', '숙제순위', 'text'),
    # 독해 · 문법 과제 결과
    ('reading_hw1_result', '독해과제1', 'text'),
    ('reading_hw2_result', '독해과제2', 'text'),
    ('grammar_no', '문법번호', 'text'),
    ('grammar_hw_result', '문법과제', 'text'),
    # 단어 암기
    ('vocab_book', '단어장', 'text'),
    ('vocab_hw_start', '단어시작', 'text'),
    ('vocab_hw_end', '단어끝', 'text'),
    ('is_new_vocab', '새단어장', 'check'),
    # 오늘 / 다음 수업 과제
    ('today_reading1', '오늘독해1', 'text'),
    ('today_reading2', '오늘독해2', 'text'),
    ('next_reading1', '다음독해1', 'text'),
    ('next_reading2', '다음독해2', 'text'),
    ('next_grammar', '다음문법', 'text'),
    ('teacher_comment', '한마디', 'text'),
]
TEXT_FIELDS = [f for f, _, t in GRID_FIELDS if t in ('text', 'att')]
ATT_CHOICES = ['', '출석', '지각', '결석']


def _parse_date(s):
    # USE_TZ=False 환경 — timezone.localdate()는 naive 에서 예외 → now().date() 사용
    if not s:
        return timezone.now().date()
    try:
        return datetime.datetime.strptime(s, '%Y-%m-%d').date()
    except ValueError:
        return timezone.now().date()


def _roster():
    """재원생(비교사) 목록 — StudentInfo.school_grade, 이름 순."""
    User = get_user_model()
    users = [u for u in User.objects.exclude(is_staff=True).exclude(is_superuser=True)
             if not is_teacher(u)]
    infos = {si.student_id: si for si in StudentInfo.objects.all()}

    def keyf(u):
        si = infos.get(u.id)
        return (si.school_grade if si else '', u.username or '')
    users.sort(key=keyf)
    return users, infos


@teacher_required
def daily_input(request):
    """일일 학습기록 입력 그리드."""
    date = _parse_date(request.GET.get('date') or request.POST.get('date'))

    if request.method == 'POST':
        users, _ = _roster()
        valid_ids = {u.id for u in users}
        saved = 0
        for sid in valid_ids:
            prefix = f'{sid}__'
            vals = {f: (request.POST.get(prefix + f, '') or '').strip() for f in TEXT_FIELDS}
            is_new = request.POST.get(prefix + 'is_new_vocab') == 'on'
            # 모든 텍스트가 비고 새단어장도 아니면 스킵 (빈 행)
            if not any(vals.values()) and not is_new:
                continue
            rec, _ = DailyRecord.objects.get_or_create(student_id=sid, date=date)
            for f in TEXT_FIELDS:
                setattr(rec, f, vals[f])
            rec.is_new_vocab = is_new
            rec.created_by = request.user
            rec.save()
            saved += 1
        messages.success(request, f'{date} 일일기록 {saved}건 저장.')
        return redirect(f"{request.path}?date={date}")

    users, infos = _roster()
    records = {r.student_id: r for r in DailyRecord.objects.filter(date=date)}
    rows = []
    for u in users:
        rec = records.get(u.id)
        si = infos.get(u.id)
        cells = []
        for key, label, typ in GRID_FIELDS:
            val = getattr(rec, key, '') if rec else ''
            cells.append({
                'name': f'{u.id}__{key}',
                'type': typ,
                'value': val,
                'checked': bool(val) if typ == 'check' else False,
                'att_choices': ATT_CHOICES if typ == 'att' else None,
            })
        rows.append({
            'student': u,
            'school_grade': si.school_grade if si else '',
            'cells': cells,
            'has_record': rec is not None,
        })
    return render(request, 'report/daily_input.html', {
        'date': date,
        'fields': GRID_FIELDS,
        'rows': rows,
    })


@teacher_required
@require_POST
def autofill(request):
    """해당 날짜의 단어/요약문/영작/모의고사 세션 점수를 DailyRecord에 자동 채움."""
    date = _parse_date(request.POST.get('date'))
    overwrite = request.POST.get('overwrite') == '1'
    n = autofill_results(date, overwrite=overwrite)
    messages.success(request, f'{date} 시험결과 자동 채움 — {n}명 반영'
                              + (' (덮어쓰기)' if overwrite else ' (빈 칸만)'))
    return redirect(f"/report/?date={date}")


@teacher_required
@require_POST
def generate_date(request):
    """해당 날짜 전체 리포트 생성."""
    date = _parse_date(request.POST.get('date'))
    ok, errors = generate_for_date(date)
    if errors:
        messages.warning(request, f'{ok}건 생성, 오류 {len(errors)}건: ' + ' / '.join(errors[:5]))
    else:
        messages.success(request, f'리포트 {ok}건 생성 완료.')
    return redirect(f"/report/list/?date={date}")


@teacher_required
@require_POST
def generate_one(request, record_id):
    rec = get_object_or_404(DailyRecord, pk=record_id)
    try:
        generate_for_record(rec)
        messages.success(request, f'{rec.student.username} 리포트 생성 완료.')
    except Exception as e:  # noqa: BLE001
        messages.error(request, f'생성 실패: {e}')
    return redirect(f"/report/list/?date={rec.date}")


@teacher_required
def report_list(request):
    """날짜별 일일기록 + 리포트 미리보기."""
    date = _parse_date(request.GET.get('date'))
    records = list(DailyRecord.objects.filter(date=date).select_related('student').order_by('student__username'))
    return render(request, 'report/report_list.html', {'date': date, 'records': records})


# ─────────────────────────────────────────────
# 종합 학습 현황 (4과목 세션 자동 집계, read-only)
# ─────────────────────────────────────────────

_WD = '월화수목금토일'


def _parse_class_hour(daytime_str, target_day):
    """엑셀 학생관리표 정렬 규칙 — '월수금444시' + 오늘 요일='수' → 4.
    요일문자열에서 target_day 위치 idx → 숫자열의 idx 자리 정수. 매칭 실패 시 99."""
    dstr = ''.join(c for c in daytime_str if c in _WD)
    nums = ''.join(c for c in daytime_str if c.isdigit())
    idx = dstr.find(target_day)
    if idx < 0 or idx >= len(nums):
        return 99
    try:
        return int(nums[idx])
    except ValueError:
        return 99


@teacher_required
def study_board(request):
    """전체 학생 현황판 — 그날 단어/요약문/영작/시험을 한 표에.
    정렬: 오늘 수업 학생 먼저(요일+시간 순), 그 외는 학교학년+이름."""
    date = _parse_date(request.GET.get('date'))
    users, infos = _roster()
    data = study.board(date)

    target_day = _WD[date.weekday()]

    rows = []
    active_count = 0
    for u in users:
        cells = data.get(u.id)
        si = infos.get(u.id)
        if cells and cells['active']:
            active_count += 1
        wt = (si.weekday_time if si else '') or (si.attend_weekdays if si else '')
        attends_today = target_day in ''.join(c for c in wt if c in _WD)
        rows.append({
            'student': u,
            'school_grade': si.school_grade if si else '',
            'cells': cells,                       # None 이면 그날 미접속
            'active': bool(cells and cells['active']),
            'attends_today': attends_today,
            'class_hour': _parse_class_hour(wt, target_day),
        })
    # 오늘 수업 학생 우선(시간 오름차순 → 이름), 나머지는 학교학년·이름 순
    rows.sort(key=lambda r: (
        0 if r['attends_today'] else 1,
        r['class_hour'] if r['attends_today'] else 99,
        r['student'].username or '',
        r['school_grade'],
    ))

    return render(request, 'report/study_board.html', {
        'date': date,
        'prev_date': date - datetime.timedelta(days=1),
        'next_date': date + datetime.timedelta(days=1),
        'today': timezone.now().date(),
        'rows': rows,
        'subjects': study.SUBJECT_META,
        'active_count': active_count,
        'total_count': len(users),
    })


@teacher_required
def study_report(request, student_id):
    """학생 1명 종합 리포트 — 그날 4과목 상세 + 주간 추이 + 다음 할 것."""
    User = get_user_model()
    student = get_object_or_404(
        User.objects.exclude(is_staff=True).exclude(is_superuser=True),
        pk=student_id,
    )
    date = _parse_date(request.GET.get('date'))
    data = study.student_day(student, date)

    try:
        school_grade = student.report_info.school_grade
    except StudentInfo.DoesNotExist:
        school_grade = ''

    return render(request, 'report/study_report.html', {
        'student': student,
        'student_name': student.username or getattr(student, 'login_id', '') or '학생',
        'school_grade': school_grade,
        'date': date,
        'prev_date': date - datetime.timedelta(days=1),
        'next_date': date + datetime.timedelta(days=1),
        'today': timezone.now().date(),
        'is_today': date == timezone.now().date(),
        'subjects': study.SUBJECT_META,
        'data': data,
    })


@login_required
def my_report(request):
    """학생 본인용 '나의 학습 리포트' — 오늘 한 것 + 앞으로 할 것(동기부여)."""
    student = request.user
    today = timezone.now().date()
    date = _parse_date(request.GET.get('date'))
    if date > today:          # 미래는 보지 않음
        date = today
    data = study.student_day(student, date)

    # 게임화 요소 (영작 프로필 — 레벨/타이틀/XP/연속출석/배지)
    from writing.models import StudentProfile, StudentAchievement
    profile = StudentProfile.objects.filter(student=student).first()
    badges = list(StudentAchievement.objects.filter(student=student)
                  .select_related('achievement')[:10])
    badge_total = StudentAchievement.objects.filter(student=student).count()

    xp_pct = None
    if profile:
        span = profile.xp_in_current_level + profile.xp_to_next_level
        xp_pct = round(profile.xp_in_current_level / span * 100) if span else 0

    done_subjects = sum(1 for k, _, _ in study.SUBJECT_META if data[k]['cell'].get('did'))

    # 오늘의 미션 달성 수 (오늘 볼 TEST 합격 + 시험 완료 등)
    nxt = data['next']
    mission_total = len(nxt['vocab_tests']) + len(nxt['summary_tests'])
    mission_done = (sum(1 for t in nxt['vocab_tests'] if t['ok'])
                    + sum(1 for t in nxt['summary_tests'] if t['ok']))

    # 격려 메시지
    if done_subjects == 0:
        cheer = '아직 오늘 학습 기록이 없어요. 한 과목만 시작해볼까요? 💪'
    elif done_subjects >= 3:
        cheer = f'오늘 {done_subjects}과목이나 했어요! 최고예요 🔥'
    else:
        cheer = f'오늘 {done_subjects}과목 했어요. 좋은 출발이에요! 👍'

    return render(request, 'report/my_report.html', {
        'student': student,
        'student_name': student.username or '학생',
        'date': date,
        'prev_date': date - datetime.timedelta(days=1),
        'next_date': date + datetime.timedelta(days=1),
        'today': today,
        'is_today': date == today,
        'show_next_nav': date < today,
        'subjects': study.SUBJECT_META,
        'data': data,
        'profile': profile,
        'badges': badges,
        'badge_total': badge_total,
        'xp_pct': xp_pct,
        'done_subjects': done_subjects,
        'mission_total': mission_total,
        'mission_done': mission_done,
        'cheer': cheer,
    })


# ─────────────────────────────────────────────
# 하이브리드 카톡용 API (토큰) — 회사 PC 페처가 호출
# ─────────────────────────────────────────────

def _resolve_chatroom(student):
    try:
        return student.report_info.resolved_chatroom_name()
    except StudentInfo.DoesNotExist:
        return f'{student.username} 프라임에듀 단톡방'


@require_GET
def kakao_today_api(request):
    """오늘(또는 ?date=) 생성된 리포트 목록 — [{chatroom_name, image_url, name}]."""
    expected = getattr(settings, 'REPORT_KAKAO_TOKEN', '')
    got = request.headers.get('X-Report-Token') or request.GET.get('token') or ''
    if not expected or got != expected:
        return JsonResponse({'success': False, 'error': '토큰 불일치/미설정'}, status=403)

    date = _parse_date(request.GET.get('date'))
    recs = (DailyRecord.objects.filter(date=date)
            .exclude(report_image='').select_related('student'))
    items = []
    for r in recs:
        try:
            url = request.build_absolute_uri(r.report_image.url)
        except ValueError:
            continue
        items.append({
            'name': r.student.username,
            'chatroom_name': _resolve_chatroom(r.student),
            'image_url': url,
        })
    return JsonResponse({'success': True, 'date': str(date), 'count': len(items), 'reports': items},
                        json_dumps_params={'ensure_ascii': False})
