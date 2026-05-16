import json
import threading
from datetime import date, datetime

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse, HttpResponseBadRequest
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

from .models import (
    WritingUnit, WritingProblem, UnitAssignment,
    WritingSession, WritingAttempt,
    StudentProfile, Achievement, StudentAchievement,
)
from .forms import WritingUnitUploadForm
from .services.excel import parse_writing_excel
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

    # 클라이언트에 보낼 문제 데이터 (영어 정답은 빼고!)
    problems_data = []
    for p in problems:
        words = p.english_words
        problems_data.append({
            'id': p.id,
            'index': p.index,
            'korean': p.korean,
            'word_count': len(words),
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
        score_earned = scoring.calculate_word_score(attempt_num, time_taken)
        # 콤보 업데이트
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

    # 세션 점수 / 프로필 XP 업데이트
    session.total_score += score_earned
    if profile.current_word_combo > session.max_word_combo:
        session.max_word_combo = profile.current_word_combo
    session.save(update_fields=['total_score', 'max_word_combo'])

    old_level = scoring.compute_level(profile.total_xp)
    profile.total_xp += score_earned
    new_level = scoring.compute_level(profile.total_xp)
    level_up = new_level > old_level

    # 배지 체크 (간단 버전)
    perfect_count_total = WritingAttempt.objects.filter(
        session__student=request.user,
        is_correct=True,
        attempt_num=1,
    ).count()

    earned_codes = scoring.check_badges(profile, {
        'is_correct_first_try': is_correct and attempt_num == 1,
        'perfect_count_total': perfect_count_total,
        'was_perfect_sentence': False,
        'was_perfect_unit': False,
        'speed_bonus_count': 0,  # TODO
        'current_hour': datetime.now().hour,
    })

    profile.save()

    # 신규 배지 부여
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
        'badges_earned': newly_earned,
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

    # 무실수 문장 = 모든 단어가 1차 시도 정답
    all_first_try = attempts.filter(is_correct=True, attempt_num=1).count() == total_words

    profile = get_or_create_profile(request.user)
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

    session.save()
    profile.save()

    return JsonResponse({
        'was_perfect_sentence': all_first_try,
        'perfect_bonus': perfect_bonus,
        'sentence_combo_bonus': sentence_combo_bonus,
        'current_sentence_combo': profile.current_sentence_combo,
        'total_score': session.total_score,
        'total_xp': profile.total_xp,
        'level': scoring.compute_level(profile.total_xp),
        'title': scoring.compute_title(scoring.compute_level(profile.total_xp)),
        'xp_in_level': profile.xp_in_current_level,
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

@teacher_required
def upload_view(request):
    if request.method == 'POST':
        form = WritingUnitUploadForm(request.POST, request.FILES)
        if form.is_valid():
            result = parse_writing_excel(form.cleaned_data['excel_file'])
            if not result['success']:
                for err in result['errors']:
                    messages.error(request, err)
                return render(request, 'writing/upload.html', {'form': form})

            try:
                with transaction.atomic():
                    unit = WritingUnit.objects.create(
                        title=form.cleaned_data['title'],
                        publisher=form.cleaned_data['publisher'],
                        grade=form.cleaned_data['grade'],
                        description=form.cleaned_data['description'],
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
                messages.success(
                    request,
                    f'단원 "{unit.title}" 생성 완료. 문제 {len(result["problems"])}개 등록. AI 한글뜻 생성 버튼을 눌러주세요.',
                )
                return redirect('writing:unit_detail', unit_id=unit.id)
            except Exception as e:
                messages.error(request, f'저장 중 오류: {e}')
                return render(request, 'writing/upload.html', {'form': form})
    else:
        form = WritingUnitUploadForm()

    return render(request, 'writing/upload.html', {'form': form})


@teacher_required
def unit_list(request):
    units = WritingUnit.objects.all().order_by('-created_at')
    return render(request, 'writing/unit_list.html', {'units': units})


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
