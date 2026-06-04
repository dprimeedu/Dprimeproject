"""단어훈련 채점 로직.

영→한 주관식 테스트: 영어 단어를 보고 한글 뜻을 입력 → 채점.
뜻은 보통 쉼표로 여러 개(예: '값이 비싼, 귀중한')이고 괄호 보충(예: '평형 (균형)')도 있어,
그 중 하나만 맞아도 정답으로 인정한다.
"""
import random
import re

# 뜻 구분자: 쉼표·슬래시·세미콜론·가운뎃점 + ' 또는 '
_SPLIT_RE = re.compile(r'[,/;·∙・]|\s또는\s')
_PAREN_RE = re.compile(r'\(([^)]*)\)')
_STRIP_RE = re.compile(r'[\s()\[\]{}~\-–—.,/·∙・;:!?\'"`]')


def _norm(text):
    """채점용 정규화: 소문자 + 공백·구두점·괄호 제거."""
    if not text:
        return ''
    return _STRIP_RE.sub('', str(text).strip().lower())


def meaning_variants(meaning):
    """정답 뜻 문자열에서 인정 가능한 정규화 답안 집합을 만든다.

    '평형 (균형)'  → {'평형', '균형', '평형균형'}
    '값이 비싼, 귀중한' → {'값이비싼', '귀중한'}
    """
    out = set()
    for part in _SPLIT_RE.split(meaning or ''):
        part = part.strip()
        if not part:
            continue
        # 괄호 안 내용도 각각 독립 답안으로 인정
        for inner in _PAREN_RE.findall(part):
            for x in _SPLIT_RE.split(inner):
                n = _norm(x)
                if n:
                    out.add(n)
        # 괄호 제거 버전
        without = _norm(_PAREN_RE.sub('', part))
        if without:
            out.add(without)
        # 괄호 포함(괄호 기호만 제거) 버전
        full = _norm(part)
        if full:
            out.add(full)
    return out


def grade_meaning(student_input, correct_meaning):
    """학생이 입력한 한글 뜻이 정답 뜻의 한 갈래와 일치하면 True."""
    si = _norm(student_input)
    if not si:
        return False
    return si in meaning_variants(correct_meaning)


# ─────────────────────────────────────────────
# 시험 문제 추출
# ─────────────────────────────────────────────

def _wrong_rate_map(word_ids):
    """단어별 과거 오답률 (= 난이도 proxy). 시도 기록이 있는 단어만 반환."""
    from django.db.models import Count, Q
    from .models import VocabAttempt
    rows = (
        VocabAttempt.objects.filter(word_id__in=word_ids)
        .values('word_id')
        .annotate(total=Count('id'), wrong=Count('id', filter=Q(is_correct=False)))
    )
    return {r['word_id']: (r['wrong'] / r['total']) for r in rows if r['total']}


def select_test_words(student, unit, start_index, end_index, count=40, star_ratio=0.7):
    """범위(start~end 번호)에서 시험 문제용 단어를 골라 반환 (셔플된 VocabWord 리스트).

    규칙: 별표(모르는 단어) 70% 랜덤 + 비별표 30% 난이도 어려운 순.
    난이도 = 과거 오답률(기록 있을 때) → 없으면 단어 길이. 한쪽이 모자라면 다른 쪽에서 채움.
    """
    from .models import StudentWordStar

    words = list(
        unit.words.filter(index__gte=start_index, index__lte=end_index).order_by('index')
    )
    if not words:
        return []
    if len(words) <= count:
        random.shuffle(words)
        return words

    word_ids = [w.id for w in words]
    starred = set(
        StudentWordStar.objects
        .filter(student=student, word_id__in=word_ids)
        .values_list('word_id', flat=True)
    )
    starred_words = [w for w in words if w.id in starred]
    non_starred = [w for w in words if w.id not in starred]

    n_star = min(len(starred_words), round(count * star_ratio))
    n_non = count - n_star
    if n_non > len(non_starred):  # 비별표 부족 → 별표에서 더
        n_star = min(len(starred_words), n_star + (n_non - len(non_starred)))
        n_non = count - n_star

    # 별표: 랜덤
    random.shuffle(starred_words)
    pick = starred_words[:n_star]

    # 비별표: 난이도 어려운 순 (오답률 → 길이)
    diff = _wrong_rate_map([w.id for w in non_starred])
    non_sorted = sorted(
        non_starred,
        key=lambda w: (diff.get(w.id, 0.0), len(w.word or '')),
        reverse=True,
    )
    pick += non_sorted[:n_non]

    # 그래도 모자라면 남은 단어로 채움
    if len(pick) < count:
        chosen = {w.id for w in pick}
        rest = [w for w in words if w.id not in chosen]
        random.shuffle(rest)
        pick += rest[: count - len(pick)]

    random.shuffle(pick)
    return pick[:count]


def sync_pairs_to_dictionary(pairs):
    """[(영어, 한글)] 목록 중 통합 사전(DictionaryEntry)에 없는 단어만 추가.

    내신단어 등 단어 import 시 호출 → 통합 사전이 자동으로 커진다.
    기존 사전 항목(전체 단어장 모음 등)은 덮어쓰지 않고 '없는 것만' 추가.
    반환: 새로 추가한 개수.
    """
    from .models import DictionaryEntry

    seen = set()
    cleaned = []  # [(word, key, meaning)]
    for word, meaning in pairs:
        word = (str(word) if word is not None else '').strip()[:255]
        meaning = (str(meaning) if meaning is not None else '').strip()
        key = word.lower()
        if not (word and meaning and key) or key in seen:
            continue
        seen.add(key)
        cleaned.append((word, key, meaning))
    if not cleaned:
        return 0

    keys = [k for _, k, _ in cleaned]
    existing = set(
        DictionaryEntry.objects.filter(key__in=keys).values_list('key', flat=True)
    )
    objs = [
        DictionaryEntry(word=w, key=k, meaning=m)
        for w, k, m in cleaned if k not in existing
    ]
    if objs:
        DictionaryEntry.objects.bulk_create(objs, batch_size=2000, ignore_conflicts=True)
    return len(objs)
