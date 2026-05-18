import json
import re
import threading
from datetime import date, datetime

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.db.models import Count, Q, Avg
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

from .models import (
    WritingUnit, WritingProblem, UnitAssignment,
    WritingSession, WritingAttempt,
    StudentProfile, Achievement, StudentAchievement,
)
from .services.excel import parse_writing_excel, parse_filename
from .services.ai import generate_word_hints, generate_word_hints_batch
from .services import scoring


# 진행 상태 추적 (메모리, 프로세스당)
_hint_progress = {}  # {unit_id: {'total', 'completed', 'done', 'running'}}
_hint_progress_lock = threading.Lock()


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def is_teacher(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    if hasattr(user, 'member_type'):
        return user.member_type in ('academy_admin', 'admin')
    if hasattr(user, 'is_academy') and user.is_academy:
        return True
    return False


def teacher_required(view_func):
    return login_required(user_passes_test(is_teacher, login_url='/login/')(view_func))


def get_or_create_profile(user):
    profile, _ = StudentProfile.objects.get_or_create(student=user)
    return profile


def update_login_streak(profile):
    today = date.today()
    last = profile.last_login_date
    if last is None:
        profile.login_streak_days = 1
    elif last == today:
        return  # 이미 오늘 처리됨
    elif (today - last).days == 1:
        profile.login_streak_days += 1
    else:
        profile.login_streak_days = 1
    profile.last_login_date = today
    profile.save(update_fields=['login_streak_days', 'last_login_date'])


# ─────────────────────────────────────────────
# 학생 화면들
# ─────────────────────────────────────────────

@login_required
def student_home(request):
    """영작훈련 학생 홈 — 배정된 단원 목록 (선생님은 전체)"""
    profile = get_or_create_profile(request.user)
    update_login_streak(profile)

    if is_teacher(request.user):
        # 선생님/관리자는 전체 단원 풀이 가능
        units = WritingUnit.objects.filter(is_active=True).order_by('-created_at')
        is_assigned_view = False
    else:
        # 일반 학생: 배정된 단원만
        assignments = UnitAssignment.objects.filter(student=request.user).select_related('unit')
        units = [a.unit for a in assignments if a.unit.is_active]
        is_assigned_view = True

    # 각 단원마다 학생의 진행 상태
    unit_info = []
    for unit in units:
        sessions = WritingSession.objects.filter(student=request.user, unit=unit)
        last = sessions.order_by('-started_at').first()
        unit_info.append({
            'unit': unit,
            'attempts_count': sessions.count(),
            'last_score': last.total_score if last else None,
            'last_started': last.started_at if last else None,
        })

    return render(request, 'writing/home.html', {
        'profile': profile,
        'unit_info': unit_info,
        'is_assigned_view': is_assigned_view,
    })


@login_required
def start_session(request, unit_id):
    """단원 풀이 시작 — WritingSession 생성 후 풀이 화면으로"""
    unit = get_object_or_404(WritingUnit, pk=unit_id, is_active=True)

    # 권한 체크: 일반 학생이면 배정받았는지
    if not is_teacher(request.user):
        if not UnitAssignment.objects.filter(student=request.user, unit=unit).exists():
            messages.error(request, '이 단원은 배정되지 않았습니다. 선생님께 문의하세요.')
            return redirect('writing:home')

    if not unit.problems.exists():
        messages.error(request, '이 단원에 문제가 없습니다.')
        return redirect('writing:home')

    session = WritingSession.objects.create(student=request.user, unit=unit)
    return redirect('writing:session', session_id=session.id)


IGNORED_WORDS = {'a', 'an', 'the'}

# 약자 패턴 (Mt., Dr., Mr., Mrs., Ms., St., Jr., Sr., Prof., Inc., Ltd., Co., vs., etc.)
_ABBREV_PATTERN = re.compile(
    r'^(Mt|Dr|Mr|Mrs|Ms|St|Jr|Sr|Prof|Inc|Ltd|Co|vs|etc|Ave|Blvd|Rd)\.?$',
    re.IGNORECASE,
)
# 숫자 (1815, 5, 1st, 2nd, 1990s 등)
_NUMBER_PATTERN = re.compile(r'^\d+(st|nd|rd|th|s)?$', re.IGNORECASE)

_PUNCT = ',.!?;:"\'()[]{}'


def _should_auto_fill(word, position):
    """
    학습 가치가 낮아 자동으로 채워줄 단어인지 판정.
    position: 문장 내 단어 인덱스 (0부터)
    """
    if not word:
        return False
    cleaned = word.strip(_PUNCT)
    if not cleaned:
        return False

    # 관사
    if cleaned.lower() in IGNORED_WORDS:
        return True
    # 숫자 (서수/연도 포함)
    if _NUMBER_PATTERN.match(cleaned):
        return True
    # 약자 (Mt., Dr. 등)
    if _ABBREV_PATTERN.match(cleaned):
        return True
    # 모두 대문자 (USA, AI, NASA 등) — 2글자 이상
    if len(cleaned) >= 2 and cleaned.isupper():
        return True
    # 문장 첫 단어가 아니면서 대문자 시작 → 고유명사로 간주 ('I' 제외)
    if position > 0 and cleaned[0].isupper() and cleaned != 'I':
        return True

    return False


# 하위 호환 — 다른 곳에서 쓰일 수 있으므로 유지
def _is_ignored_word(word):
    cleaned = word.strip(_PUNCT).lower()
    return cleaned in IGNORED_WORDS


@login_required
def session_view(request, session_id):
    """실제 풀이 화면"""
    session = get_object_or_404(WritingSession, pk=session_id)

    # 본인 세션만
    if session.student != request.user:
        messages.error(request, '본인 세션이 아닙니다.')
        return redirect('writing:home')

    # 이미 완료된 세션은 결과 화면으로
    if session.finished_at:
        return redirect('writing:result', session_id=session.id)

    profile = get_or_create_profile(request.user)
    problems = list(session.unit.problems.all().order_by('index'))

    # 클라이언트에 보낼 문제 데이터
    # 관사/고유명사/숫자/약자는 자동 채우기 — 정답값을 노출하지만 학습 가치 낮은 단어들
    problems_data = []
    for p in problems:
        words = p.english_words
        word_meta = []
        for i, w in enumerate(words):
            if _should_auto_fill(w, i):
                word_meta.append({'auto': True, 'value': w})
            else:
                word_meta.append({'auto': False})
        problems_data.append({
            'id': p.id,
            'index': p.index,
            'korean': p.korean,
            'word_count': len(words),
            'words': word_meta,
        })

    return render(request, 'writing/session.html', {
        'session': session,
        'unit': session.unit,
        'profile': profile,
        'problems_json': json.dumps(problems_data, ensure_ascii=False),
        'total_problems': len(problems),
    })


@login_required
def result_view(request, session_id):
    """결과 화면"""
    session = get_object_or_404(WritingSession, pk=session_id)
    if session.student != request.user:
        return redirect('writing:home')

    profile = get_or_create_profile(request.user)
    attempts = WritingAttempt.objects.filter(session=session)
    total_words_attempted = attempts.values('problem_id', 'word_index').distinct().count()
    correct_first_try = attempts.filter(is_correct=True, attempt_num=1).count()
    accuracy = (correct_first_try / total_words_attempted * 100) if total_words_attempted else 0

    earned_badges = StudentAchievement.objects.filter(
        student=request.user,
        earned_at__gte=session.started_at,
    ).select_related('achievement')

    return render(request, 'writing/result.html', {
        'session': session,
        'unit': session.unit,
        'profile': profile,
        'accuracy': round(accuracy, 1),
        'total_words': total_words_attempted,
        'correct_first_try': correct_first_try,
        'earned_badges': earned_badges,
    })


# ─────────────────────────────────────────────
# AJAX API — 단어 채점
# ─────────────────────────────────────────────

@login_required
@require_POST
def check_word_api(request):
    """
    단어 채점 + 점수/콤보/XP 처리.

    POST body (JSON):
      session_id, problem_id, word_index, input, time_taken_seconds

    Response:
      is_correct, attempt_num, hint_level, word_done, next_hint,
      score_earned, combo_bonus,
      current_word_combo, total_score, total_xp, level, level_up,
      badges_earned
    """
    try:
        data = json.loads(request.body)
        session_id = int(data['session_id'])
        problem_id = int(data['problem_id'])
        word_index = int(data['word_index'])
        student_input = str(data.get('input', ''))
        time_taken = int(data.get('time_taken_seconds', 0))
        is_auto_fill = bool(data.get('auto', False))
    except (json.JSONDecodeError, KeyError, ValueError):
        return HttpResponseBadRequest('Invalid request')

    session = get_object_or_404(WritingSession, pk=session_id)
    if session.student != request.user:
        return JsonResponse({'error': 'forbidden'}, status=403)
    if session.finished_at:
        return JsonResponse({'error': 'session_finished'}, status=400)

    problem = get_object_or_404(WritingProblem, pk=problem_id, unit=session.unit)
    words = problem.english_words
    if word_index < 0 or word_index >= len(words):
        return HttpResponseBadRequest('Invalid word_index')

    correct_word = words[word_index]

    # 자동 채우기는 서버 측에서도 그 단어가 실제 자동 대상인지 검증 (악용 방지)
    if is_auto_fill and not _should_auto_fill(correct_word, word_index):
        is_auto_fill = False

    # 이 단어에 대한 이전 시도 횟수
    prev_attempts = WritingAttempt.objects.filter(
        session=session, problem=problem, word_index=word_index
    )
    prev_count = prev_attempts.count()

    # 이미 done(맞췄거나 3회 다 썼거나)이면 무시
    last_done = prev_attempts.filter(Q(is_correct=True) | Q(hint_level=3)).exists()
    if last_done:
        return JsonResponse({'error': 'word_already_done'}, status=400)

    attempt_num = prev_count + 1
    is_correct = scoring.check_correctness(student_input, correct_word)

    profile = get_or_create_profile(request.user)

    score_earned = 0
    combo_bonus = 0
    hint_level_to_show = 0
    next_hint = None
    word_done = False
    fully_failed = False

    if is_correct:
        # 정답
        word_done = True
        hint_level_to_show = attempt_num - 1  # 0/1/2
        if is_auto_fill:
            # 자동 채우기는 점수/콤보 없음 (학생이 노력한 게 아님)
            score_earned = 0
        else:
            score_earned = scoring.calculate_word_score(attempt_num, time_taken)
            new_combo, hit_milestone = scoring.update_word_combo(profile, True, False)
            if hit_milestone:
                combo_bonus = scoring.WORD_COMBO_BONUSES.get(new_combo, 0)
                score_earned += combo_bonus
    else:
        # 오답
        if attempt_num >= 3:
            # 3번째도 틀림 → 정답 공개로 종료
            word_done = True
            fully_failed = True
            hint_level_to_show = 3
            score_earned = scoring.SCORE_REVEAL
            next_hint = scoring.get_hint_content(problem, word_index, 3)
            # 콤보 끊김
            scoring.update_word_combo(profile, False, True)
        else:
            # 다음 힌트 보여줌 (1 또는 2)
            hint_level_to_show = attempt_num
            score_earned = 0
            # 학생 입력이 정답의 70% 이상 prefix 매칭이면 정답 markup으로 (한글뜻 건너뜀)
            match_ratio = scoring.prefix_match_ratio(student_input, correct_word)
            if match_ratio >= scoring.NEAR_MISS_THRESHOLD:
                next_hint = {
                    'type': 'near_miss',
                    'content': correct_word,
                    'student': student_input.strip(),
                }
            else:
                next_hint = scoring.get_hint_content(problem, word_index, hint_level_to_show)

    # WritingAttempt 저장
    WritingAttempt.objects.create(
        session=session,
        problem=problem,
        word_index=word_index,
        input_value=student_input[:200],
        correct_answer=correct_word,
        hint_level=hint_level_to_show,
        is_correct=is_correct,
        attempt_num=attempt_num,
        time_taken_seconds=time_taken,
        score_earned=score_earned,
    )

    # 세션 점수 / 프로필 XP 업데이트 (단어마다, 가볍게)
    session.total_score += score_earned
    if profile.current_word_combo > session.max_word_combo:
        session.max_word_combo = profile.current_word_combo
    session.save(update_fields=['total_score', 'max_word_combo'])

    old_level = scoring.compute_level(profile.total_xp)
    profile.total_xp += score_earned
    new_level = scoring.compute_level(profile.total_xp)
    level_up = new_level > old_level

    # update_fields로 필수 컬럼만 (배지/통계는 complete_problem에서 일괄)
    profile.save(update_fields=[
        'total_xp', 'current_word_combo', 'max_word_combo_ever',
    ])

    return JsonResponse({
        'is_correct': is_correct,
        'attempt_num': attempt_num,
        'hint_level': hint_level_to_show,
        'word_done': word_done,
        'next_hint': next_hint,
        'score_earned': score_earned,
        'combo_bonus': combo_bonus,
        'current_word_combo': profile.current_word_combo,
        'total_score': session.total_score,
        'total_xp': profile.total_xp,
        'level': new_level,
        'title': scoring.compute_title(new_level),
        'level_up': level_up,
        'xp_in_level': profile.xp_in_current_level,
        'badges_earned': [],  # 배지는 문장 끝에 일괄 처리
    })


@login_required
@require_POST
def complete_problem_api(request):
    """
    문제 1개 풀이 완료 시 (모든 단어 done) — 문장 콤보 처리.

    POST body: {session_id, problem_id}
    """
    try:
        data = json.loads(request.body)
        session_id = int(data['session_id'])
        problem_id = int(data['problem_id'])
    except (json.JSONDecodeError, KeyError, ValueError):
        return HttpResponseBadRequest('Invalid')

    session = get_object_or_404(WritingSession, pk=session_id)
    if session.student != request.user:
        return JsonResponse({'error': 'forbidden'}, status=403)
    problem = get_object_or_404(WritingProblem, pk=problem_id, unit=session.unit)

    # 이 문제 단어 전체 시도 분석
    attempts = WritingAttempt.objects.filter(session=session, problem=problem)
    total_words = len(problem.english_words)
    distinct_words_done = attempts.values('word_index').distinct().count()
    if distinct_words_done < total_words:
        return JsonResponse({'error': 'not_all_words_done'}, status=400)

    # 사람이 실제로 맞춘 단어 수 (자동 채우기 = score_earned=0 제외)
    human_correct_count = attempts.filter(is_correct=True, score_earned__gt=0).count()

    # 무지성 통과 판정: 정답 0개 + 시도당 평균 시간이 너무 짧음
    # (자동 채우기는 is_correct=True AND score_earned=0 으로 식별)
    non_auto_attempts = attempts.exclude(is_correct=True, score_earned=0)
    non_auto_count = non_auto_attempts.count()
    avg_time = (
        non_auto_attempts.aggregate(Avg('time_taken_seconds'))['time_taken_seconds__avg'] or 0
    )
    forfeit = (
        human_correct_count == 0
        and non_auto_count > 0
        and avg_time < scoring.NO_THINK_THRESHOLD_SEC
    )

    # 무실수 문장 = 모든 단어가 1차 시도 정답 (단, 무지성 케이스는 제외)
    all_first_try = (
        not forfeit
        and attempts.filter(is_correct=True, attempt_num=1).count() == total_words
    )

    profile = get_or_create_profile(request.user)

    forfeit_amount = 0
    if forfeit:
        # 이 문장에서 얻은 모든 점수 회수 (자동 채우기 +0은 영향 없음)
        forfeit_amount = sum(a.score_earned for a in attempts)
        if forfeit_amount > 0:
            session.total_score = max(0, session.total_score - forfeit_amount)
            profile.total_xp = max(0, profile.total_xp - forfeit_amount)
        # 문장 콤보도 끊김
        scoring.update_sentence_combo(profile, False)
        new_sent_combo, milestone = 0, False
    else:
        new_sent_combo, milestone = scoring.update_sentence_combo(profile, all_first_try)

    extra_score = 0
    perfect_bonus = 0
    sentence_combo_bonus = 0
    if all_first_try:
        perfect_bonus = scoring.PERFECT_SENTENCE_BONUS
        session.perfect_sentences += 1
        if milestone:
            sentence_combo_bonus = scoring.SENTENCE_COMBO_BONUSES.get(new_sent_combo, 0)
        extra_score = perfect_bonus + sentence_combo_bonus
        session.total_score += extra_score
        profile.total_xp += extra_score

    if profile.current_sentence_combo > session.max_sentence_combo:
        session.max_sentence_combo = profile.current_sentence_combo

    # ── 배지 체크 (문장 단위, 단어마다 안 함) ──
    perfect_count_total = WritingAttempt.objects.filter(
        session__student=request.user,
        is_correct=True,
        attempt_num=1,
    ).count()

    earned_codes = scoring.check_badges(profile, {
        'is_correct_first_try': all_first_try,
        'perfect_count_total': perfect_count_total,
        'was_perfect_sentence': all_first_try,
        'was_perfect_unit': False,
        'speed_bonus_count': 0,
        'current_hour': datetime.now().hour,
    })

    newly_earned = []
    if earned_codes:
        for code in earned_codes:
            ach = Achievement.objects.filter(code=code).first()
            if ach:
                sa, created = StudentAchievement.objects.get_or_create(
                    student=request.user, achievement=ach,
                )
                if created:
                    newly_earned.append({
                        'icon': ach.icon, 'name': ach.name, 'description': ach.description,
                    })

    session.save()
    profile.save()

    # 이 문장의 점수 비율 계산 (자동 채우기 제외, base 점수만 — speed/콤보 보너스 제외)
    words = problem.english_words
    non_auto_count = sum(1 for i, w in enumerate(words) if not _should_auto_fill(w, i))
    sentence_max = non_auto_count * scoring.SCORE_BY_HINT_LEVEL[0]  # 단어당 10점 만점

    sentence_earned = 0
    for a in attempts:
        if a.is_correct and a.score_earned == 0:
            continue  # 자동 채우기
        if a.is_correct:
            # PERFECT(10) / GREAT(6) / GOOD(3) — base만
            sentence_earned += scoring.SCORE_BY_HINT_LEVEL.get(a.hint_level, 0)
        elif a.hint_level == 3:
            # BOO~ (정답 공개) +1
            sentence_earned += scoring.SCORE_REVEAL

    if forfeit:
        sentence_earned = 0
    sentence_pct = (sentence_earned / sentence_max * 100) if sentence_max > 0 else 100
    passed = sentence_pct >= scoring.SENTENCE_PASS_THRESHOLD

    return JsonResponse({
        'was_perfect_sentence': all_first_try,
        'perfect_bonus': perfect_bonus,
        'sentence_combo_bonus': sentence_combo_bonus,
        'forfeit': forfeit,
        'forfeit_amount': forfeit_amount,
        'avg_time_per_attempt': round(avg_time, 1),
        'sentence_score': sentence_earned,
        'sentence_max': sentence_max,
        'sentence_pct': round(sentence_pct, 1),
        'passed': passed,
        'pass_threshold': scoring.SENTENCE_PASS_THRESHOLD,
        'current_sentence_combo': profile.current_sentence_combo,
        'badges_earned': newly_earned,
        'total_score': session.total_score,
        'total_xp': profile.total_xp,
        'level': scoring.compute_level(profile.total_xp),
        'title': scoring.compute_title(scoring.compute_level(profile.total_xp)),
        'xp_in_level': profile.xp_in_current_level,
    })


@login_required
@require_POST
def reset_problem_api(request):
    """문제 재시도 — 그 문제의 attempts 삭제 + 점수 회수"""
    try:
        data = json.loads(request.body)
        session_id = int(data['session_id'])
        problem_id = int(data['problem_id'])
    except (json.JSONDecodeError, KeyError, ValueError):
        return HttpResponseBadRequest('Invalid')

    session = get_object_or_404(WritingSession, pk=session_id)
    if session.student != request.user:
        return JsonResponse({'error': 'forbidden'}, status=403)
    if session.finished_at:
        return JsonResponse({'error': 'session_finished'}, status=400)

    attempts = WritingAttempt.objects.filter(session=session, problem_id=problem_id)
    forfeit = sum(a.score_earned for a in attempts)
    attempts.delete()

    profile = get_or_create_profile(request.user)
    if forfeit > 0:
        session.total_score = max(0, session.total_score - forfeit)
        profile.total_xp = max(0, profile.total_xp - forfeit)
        session.save(update_fields=['total_score'])
        profile.save(update_fields=['total_xp'])

    # 콤보도 끊김
    profile.current_word_combo = 0
    profile.current_sentence_combo = 0
    profile.save(update_fields=['current_word_combo', 'current_sentence_combo'])

    return JsonResponse({
        'success': True,
        'forfeit': forfeit,
        'total_score': session.total_score,
        'total_xp': profile.total_xp,
        'xp_in_level': profile.xp_in_current_level,
        'level': scoring.compute_level(profile.total_xp),
        'title': scoring.compute_title(scoring.compute_level(profile.total_xp)),
    })


@login_required
@require_POST
def complete_session_api(request):
    """세션 완료 처리"""
    try:
        data = json.loads(request.body)
        session_id = int(data['session_id'])
    except (json.JSONDecodeError, KeyError, ValueError):
        return HttpResponseBadRequest('Invalid')

    session = get_object_or_404(WritingSession, pk=session_id)
    if session.student != request.user:
        return JsonResponse({'error': 'forbidden'}, status=403)
    if not session.finished_at:
        session.finished_at = timezone.now()
        session.save(update_fields=['finished_at'])

    return JsonResponse({
        'success': True,
        'redirect_url': f'/training/writing/result/{session.id}/',
    })


# ─────────────────────────────────────────────
# 선생님 화면들 (기존)
# ─────────────────────────────────────────────

VALID_GRADES = {g[0] for g in WritingUnit.GRADE_CHOICES}


@teacher_required
def upload_view(request):
    if request.method != 'POST':
        return render(request, 'writing/upload.html', {})

    files = request.FILES.getlist('excel_file')
    if not files:
        messages.error(request, '엑셀 파일을 1개 이상 선택해주세요.')
        return render(request, 'writing/upload.html', {})

    created_units = []
    total_problems = 0
    total_skipped = 0
    file_errors = []

    for f in files:
        if not f.name.lower().endswith(('.xlsx', '.xls')):
            file_errors.append(f'{f.name}: xlsx/xls만 업로드 가능')
            continue
        if f.size > 10 * 1024 * 1024:
            file_errors.append(f'{f.name}: 10MB 초과')
            continue

        result = parse_writing_excel(f)
        if not result['success']:
            file_errors.append(f'{f.name}: {"; ".join(result["errors"])}')
            continue

        meta = parse_filename(f.name)
        title = meta['title'] or re.sub(r'\.[^.]+$', '', f.name)
        grade = meta['grade'] if meta['grade'] in VALID_GRADES else '기타'

        try:
            with transaction.atomic():
                unit = WritingUnit.objects.create(
                    title=title,
                    publisher=meta['publisher'],
                    grade=grade,
                    created_by=request.user,
                )
                for p in result['problems']:
                    WritingProblem.objects.create(
                        unit=unit,
                        index=p['index'],
                        korean=p['korean'],
                        english=p['english'],
                        word_hints=[],
                    )
            created_units.append(unit)
            total_problems += len(result['problems'])
            total_skipped += result.get('skipped_short', 0)
        except Exception as e:
            file_errors.append(f'{f.name}: 저장 실패 — {e}')

    for err in file_errors:
        messages.warning(request, err)

    if not created_units:
        messages.error(request, '생성된 단원이 없습니다.')
        return render(request, 'writing/upload.html', {})

    skip_msg = f' · 3단어 이하 제외 {total_skipped}행' if total_skipped else ''
    messages.success(
        request,
        f'단원 {len(created_units)}개 생성 · 문제 {total_problems}개 등록{skip_msg}. '
        f'각 단원 상세 페이지에서 "AI 한글뜻 생성" 버튼을 눌러주세요.',
    )

    if len(created_units) == 1:
        return redirect('writing:unit_detail', unit_id=created_units[0].id)
    return redirect('writing:unit_list')


@teacher_required
def unit_list(request):
    units = list(WritingUnit.objects.all().order_by('-created_at'))
    # 각 단원의 has_hints_count 동적 부여 (테이블에 진행도 표시용)
    for u in units:
        u.has_hints_count = u.problems.exclude(word_hints=[]).count()
        u.total_count = u.problems.count()
    return render(request, 'writing/unit_list.html', {'units': units})


@teacher_required
@require_POST
def unit_delete(request):
    """체크박스로 고른 단원들을 cascade 데이터(문제·배정·세션·시도)와 함께 삭제."""
    raw_ids = request.POST.getlist('unit_ids')
    try:
        ids = [int(x) for x in raw_ids if x]
    except ValueError:
        ids = []

    if not ids:
        messages.warning(request, '삭제할 단원을 선택해주세요.')
        return redirect('writing:unit_list')

    qs = WritingUnit.objects.filter(pk__in=ids)
    count = qs.count()
    qs.delete()
    messages.success(request, f'단원 {count}개 삭제 완료.')
    return redirect('writing:unit_list')


@teacher_required
def unit_detail(request, unit_id):
    unit = get_object_or_404(WritingUnit, pk=unit_id)
    problems = unit.problems.all().order_by('index')
    has_hints_count = sum(1 for p in problems if p.word_hints)
    return render(request, 'writing/unit_detail.html', {
        'unit': unit,
        'problems': problems,
        'has_hints_count': has_hints_count,
        'total_count': problems.count(),
    })


BATCH_SIZE = 20  # API 호출당 문제 수


def _run_hint_generation(unit_id):
    """백그라운드 스레드에서 단원 전체 한글뜻 생성"""
    from django.db import connection
    try:
        problems = list(
            WritingProblem.objects.filter(unit_id=unit_id, word_hints=[]).order_by('index')
        )
        with _hint_progress_lock:
            _hint_progress[unit_id]['total'] = len(problems)
            _hint_progress[unit_id]['completed'] = 0

        for batch_start in range(0, len(problems), BATCH_SIZE):
            batch = problems[batch_start:batch_start + BATCH_SIZE]
            inputs = [{'english': p.english, 'korean': p.korean} for p in batch]
            hints_lists = generate_word_hints_batch(inputs)

            for problem, hints in zip(batch, hints_lists):
                if hints:
                    problem.word_hints = hints
                    problem.save(update_fields=['word_hints'])

            with _hint_progress_lock:
                _hint_progress[unit_id]['completed'] = batch_start + len(batch)

        with _hint_progress_lock:
            _hint_progress[unit_id]['done'] = True
            _hint_progress[unit_id]['running'] = False
    except Exception as e:
        print(f'[hint generation] unit {unit_id} 실패: {e}')
        with _hint_progress_lock:
            _hint_progress[unit_id]['done'] = True
            _hint_progress[unit_id]['running'] = False
            _hint_progress[unit_id]['error'] = str(e)
    finally:
        connection.close()


@teacher_required
@require_POST
def generate_hints_ajax(request, unit_id):
    """단원의 한글뜻 생성 시작 (백그라운드)"""
    unit = get_object_or_404(WritingUnit, pk=unit_id)

    with _hint_progress_lock:
        existing = _hint_progress.get(unit_id)
        if existing and existing.get('running'):
            return JsonResponse({
                'started': False,
                'message': '이미 생성 중입니다.',
                **existing,
            })

        _hint_progress[unit_id] = {
            'total': unit.problems.filter(word_hints=[]).count(),
            'completed': 0,
            'done': False,
            'running': True,
            'error': None,
        }

    if _hint_progress[unit_id]['total'] == 0:
        with _hint_progress_lock:
            _hint_progress[unit_id]['done'] = True
            _hint_progress[unit_id]['running'] = False
        return JsonResponse({'started': True, 'done': True, 'total': 0, 'completed': 0})

    # 백그라운드 스레드 시작
    t = threading.Thread(target=_run_hint_generation, args=(unit_id,), daemon=True)
    t.start()

    return JsonResponse({
        'started': True,
        'total': _hint_progress[unit_id]['total'],
        'completed': 0,
        'done': False,
    })


@teacher_required
@require_GET
def assignment_list(request, unit_id):
    """단원에 배정 가능한 학생 목록 + 현재 배정 상태 반환"""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    unit = get_object_or_404(WritingUnit, pk=unit_id)

    assigned_ids = set(
        UnitAssignment.objects.filter(unit=unit).values_list('student_id', flat=True)
    )

    users = User.objects.filter(is_active=True).order_by('username')
    students = []
    for u in users:
        if is_teacher(u):
            continue
        name = (
            getattr(u, 'name', None)
            or getattr(u, 'full_name', None)
            or f'{u.first_name} {u.last_name}'.strip()
            or ''
        )
        students.append({
            'id': u.id,
            'username': u.username,
            'name': name,
            'is_assigned': u.id in assigned_ids,
        })

    return JsonResponse(
        {'students': students, 'assigned_count': len(assigned_ids)},
        json_dumps_params={'ensure_ascii': False},
    )


@teacher_required
@require_POST
def assignment_update(request, unit_id):
    """학생 배정 일괄 갱신 — body: {student_ids:[..]} 의 학생만 배정 상태로 (나머지는 해제)"""
    unit = get_object_or_404(WritingUnit, pk=unit_id)
    try:
        data = json.loads(request.body)
        target_ids = {int(x) for x in data.get('student_ids', [])}
    except (json.JSONDecodeError, ValueError, TypeError):
        return HttpResponseBadRequest('Invalid')

    current_ids = set(
        UnitAssignment.objects.filter(unit=unit).values_list('student_id', flat=True)
    )
    to_add = target_ids - current_ids
    to_remove = current_ids - target_ids

    if to_add:
        UnitAssignment.objects.bulk_create([
            UnitAssignment(student_id=sid, unit=unit, assigned_by=request.user)
            for sid in to_add
        ], ignore_conflicts=True)
    if to_remove:
        UnitAssignment.objects.filter(unit=unit, student_id__in=to_remove).delete()

    return JsonResponse({
        'success': True,
        'assigned_count': UnitAssignment.objects.filter(unit=unit).count(),
        'added': len(to_add),
        'removed': len(to_remove),
    })


@teacher_required
@require_POST
def generate_hints_bulk_ajax(request):
    """체크한 N개 단원에서 word_hints 비어있는 문제를 각각 백그라운드 생성 시작."""
    try:
        data = json.loads(request.body or '{}')
        unit_ids = [int(x) for x in data.get('unit_ids', [])]
    except (json.JSONDecodeError, ValueError, TypeError):
        return HttpResponseBadRequest('Invalid unit_ids')

    started = []
    already_running = []
    already_done = []

    for uid in unit_ids:
        unit = WritingUnit.objects.filter(pk=uid).first()
        if not unit:
            continue
        remaining = unit.problems.filter(word_hints=[]).count()
        if remaining == 0:
            already_done.append(uid)
            continue
        with _hint_progress_lock:
            existing = _hint_progress.get(uid)
            if existing and existing.get('running'):
                already_running.append(uid)
                continue
            _hint_progress[uid] = {
                'total': remaining, 'completed': 0,
                'done': False, 'running': True, 'error': None,
            }
        threading.Thread(target=_run_hint_generation, args=(uid,), daemon=True).start()
        started.append(uid)

    return JsonResponse({
        'started': len(started),
        'already_running': len(already_running),
        'already_done': len(already_done),
    })


@teacher_required
@require_GET
def student_list_api(request):
    """전체 학생 목록 (단원 무관) — 일괄 배정/해제 모달용."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    users = User.objects.filter(is_active=True).order_by('username')
    students = []
    for u in users:
        if is_teacher(u):
            continue
        name = (
            getattr(u, 'name', None)
            or getattr(u, 'full_name', None)
            or f'{u.first_name} {u.last_name}'.strip()
            or ''
        )
        students.append({'id': u.id, 'username': u.username, 'name': name})
    return JsonResponse({'students': students}, json_dumps_params={'ensure_ascii': False})


@teacher_required
@require_POST
def assignments_bulk_update(request):
    """체크한 N개 단원에 학생 추가 또는 단원에서 학생 제거.
    body: { action: 'add'|'remove', unit_ids: [...], student_ids: [...] }
    """
    try:
        data = json.loads(request.body)
        action = data.get('action')
        unit_ids = [int(x) for x in data.get('unit_ids', [])]
        student_ids = [int(x) for x in data.get('student_ids', [])]
    except (json.JSONDecodeError, ValueError, TypeError):
        return HttpResponseBadRequest('Invalid body')

    if action not in ('add', 'remove'):
        return HttpResponseBadRequest('action must be add or remove')
    if not unit_ids or not student_ids:
        return HttpResponseBadRequest('Empty unit_ids or student_ids')

    valid_unit_ids = list(
        WritingUnit.objects.filter(pk__in=unit_ids).values_list('id', flat=True)
    )

    if action == 'add':
        UnitAssignment.objects.bulk_create(
            [
                UnitAssignment(student_id=sid, unit_id=uid, assigned_by=request.user)
                for uid in valid_unit_ids
                for sid in student_ids
            ],
            ignore_conflicts=True,
        )
        return JsonResponse({
            'success': True, 'action': 'add',
            'units': len(valid_unit_ids), 'students': len(student_ids),
        })

    deleted, _ = UnitAssignment.objects.filter(
        unit_id__in=valid_unit_ids, student_id__in=student_ids,
    ).delete()
    return JsonResponse({
        'success': True, 'action': 'remove',
        'units': len(valid_unit_ids), 'students': len(student_ids),
        'removed_rows': deleted,
    })


@teacher_required
@require_GET
def generate_hints_status(request, unit_id):
    """진행 상태 폴링"""
    with _hint_progress_lock:
        state = _hint_progress.get(unit_id)
        if not state:
            # 진행 기록 없음 → DB에서 직접 확인
            unit = get_object_or_404(WritingUnit, pk=unit_id)
            total = unit.problems.count()
            done_count = unit.problems.exclude(word_hints=[]).count()
            return JsonResponse({
                'total': total,
                'completed': done_count,
                'done': True,
                'running': False,
            })
        return JsonResponse(dict(state))
