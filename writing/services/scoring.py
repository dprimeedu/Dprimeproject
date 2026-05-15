"""
점수/콤보/XP/레벨업/배지 계산 로직
"""
import re
from django.utils import timezone


# 점수 테이블
SCORE_BY_HINT_LEVEL = {
    0: 10,  # 1차 시도 정답 (힌트 없이)
    1: 6,   # 1번 힌트(한글뜻) 후 정답
    2: 3,   # 2번 힌트(첫글자) 후 정답
}
SCORE_REVEAL = 1            # 3번에서 정답 공개 (학습 인정)
SPEED_BONUS = 2             # 3초 안에 1차 정답
SPEED_THRESHOLD_SEC = 3

# 콤보 마일스톤 보너스
WORD_COMBO_BONUSES = {5: 10, 10: 20, 20: 40, 50: 100, 100: 200}
SENTENCE_COMBO_BONUSES = {3: 50, 5: 100, 10: 200}
PERFECT_SENTENCE_BONUS = 20


def normalize(text):
    """단어 정규화: 구두점 제거 + 소문자"""
    if text is None:
        return ''
    text = str(text).strip().lower()
    text = re.sub(r'[.,?!;:"]', '', text)
    return text


def check_correctness(student_input, correct_answer):
    """정답 비교"""
    return normalize(student_input) == normalize(correct_answer)


def calculate_word_score(attempt_num, time_taken_seconds):
    """
    단어 1개에 대한 점수 계산.
    attempt_num: 1, 2, 3
    """
    hint_level = attempt_num - 1
    base = SCORE_BY_HINT_LEVEL.get(hint_level, 0)
    speed = SPEED_BONUS if (hint_level == 0 and time_taken_seconds <= SPEED_THRESHOLD_SEC) else 0
    return base + speed


def calculate_combo_bonus(new_combo, combo_bonuses):
    """콤보 마일스톤 도달 시 보너스 (안 도달이면 0)"""
    return combo_bonuses.get(new_combo, 0)


def update_word_combo(profile, is_correct, fully_failed):
    """
    단어 단위 콤보 업데이트.
    is_correct: 단어를 맞췄나
    fully_failed: 3차에서 답 공개로 끝났나 (콤보 끊김)

    Returns: (new_combo, milestone_reached)
    """
    if fully_failed:
        profile.current_word_combo = 0
        return 0, False

    if is_correct:
        profile.current_word_combo += 1
        new_combo = profile.current_word_combo
        if new_combo > profile.max_word_combo_ever:
            profile.max_word_combo_ever = new_combo
        milestone = new_combo in WORD_COMBO_BONUSES
        return new_combo, milestone

    return profile.current_word_combo, False


def update_sentence_combo(profile, was_perfect_sentence):
    """
    문장 단위 콤보 업데이트.
    was_perfect_sentence: 모든 단어 1차 정답이었는지
    """
    if was_perfect_sentence:
        profile.current_sentence_combo += 1
        new = profile.current_sentence_combo
        if new > profile.max_sentence_combo_ever:
            profile.max_sentence_combo_ever = new
        milestone = new in SENTENCE_COMBO_BONUSES
        return new, milestone
    else:
        profile.current_sentence_combo = 0
        return 0, False


def check_badges(profile, context):
    """
    프로필 상태에 따라 새로 획득한 배지 확인.
    context: {
      'is_correct_first_try': bool,
      'perfect_count_total': int,  // 누적 1차 정답 단어 수 (DB에서 계산)
      'was_perfect_sentence': bool,
      'was_perfect_unit': bool,
      'speed_bonus_count': int,  // 누적 speed bonus 횟수
      'current_hour': int,  // 0~23
    }

    Returns: list of (achievement_code, ...) — caller가 DB에서 매핑
    """
    earned_codes = []

    # 첫 단어 정답
    if context.get('is_correct_first_try') and context.get('perfect_count_total', 0) == 1:
        earned_codes.append('first_word')

    perfect_count = context.get('perfect_count_total', 0)
    if perfect_count >= 10:
        earned_codes.append('ten_perfect')
    if perfect_count >= 100:
        earned_codes.append('hundred_perfect')

    word_combo = profile.current_word_combo
    if word_combo >= 5:
        earned_codes.append('combo_5')
    if word_combo >= 10:
        earned_codes.append('combo_10')
    if word_combo >= 50:
        earned_codes.append('combo_50')

    if context.get('was_perfect_sentence'):
        earned_codes.append('perfect_sentence')
    if context.get('was_perfect_unit'):
        earned_codes.append('perfect_unit')

    streak = profile.login_streak_days
    if streak >= 7:
        earned_codes.append('streak_7')
    if streak >= 30:
        earned_codes.append('streak_30')

    if context.get('speed_bonus_count', 0) >= 50:
        earned_codes.append('speed_demon')

    hour = context.get('current_hour', 12)
    if hour < 7:
        earned_codes.append('early_bird')
    if hour >= 23:
        earned_codes.append('night_owl')

    return earned_codes


def compute_level(total_xp):
    return total_xp // 100 + 1


def compute_title(level):
    if level <= 2:
        return '새내기'
    elif level <= 5:
        return '견습생'
    elif level <= 10:
        return '영작러'
    elif level <= 20:
        return '영작러+'
    elif level <= 50:
        return '영작마스터'
    else:
        return '영작신'


def get_hint_content(problem, word_index, hint_level):
    """
    힌트 단계별 내용 반환.
    """
    words = problem.english_words
    if word_index >= len(words):
        return None

    correct_word = words[word_index]

    if hint_level == 1:
        # 한글뜻
        hints = problem.word_hints or []
        if word_index < len(hints) and isinstance(hints[word_index], dict):
            return {'type': 'korean_meaning', 'content': hints[word_index].get('meaning', '?')}
        return {'type': 'korean_meaning', 'content': '(뜻 미생성)'}
    elif hint_level == 2:
        # 첫글자
        return {'type': 'first_letter', 'content': correct_word[0] + '_' * (len(correct_word) - 1)}
    elif hint_level == 3:
        # 정답
        return {'type': 'answer', 'content': correct_word}

    return None
