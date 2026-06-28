# -*- coding: utf-8 -*-
"""빈칸 추론 변형문제 1층 룰 기반 필터 (docs/빈칸 삭제spec.md 1층).

목적: AI 생성 빈칸 문제 중 '선지가 서로 너무 비슷해서 변별이 안 되는 결함 후보'를
정규식·집합 연산만으로 빠르게 골라낸다. 여기서 걸린 건 '제외'가 아니라 '2층(LLM)
판정 후보' — 형식이 닮았다는 것 자체가 결함은 아니므로, 1층은 후보 선별용.

룰 (하나라도 걸리면 layer1_flagged):
  (a) 선지 5개 중 3개 이상이 동일/유사 도입구로 시작
      (첫 5~7단어 정규화 후 일치율 ≥ 0.8)
  (b) 선지 5개 중 4개 이상이 동일 꼬리구로 끝남
      (마지막 5~7단어 정규화 후 일치율 ≥ 0.8)
  (c) 선지 쌍 간 평균 토큰 중복률(Jaccard) ≥ 0.5
  (d) 선지 길이(토큰 수) 표준편차 비정상적으로 작음 (≤ 평균의 5%)
  (e) 선지 5개 중 3개 이상이 공백 포함 100자 이상

진입: classify_cloze_choices(choices) -> {'flagged': bool, 'rules': [...]}
"""
import re as _re
import statistics as _stat


# 도입/꼬리 비교용 단어 개수 (5~7 사이에서 표본 추출)
_PREFIX_WORDS_MIN = 5
_PREFIX_WORDS_MAX = 7

# 임계값 (spec.md 기본값)
_PREFIX_RATIO = 0.8       # 도입구 일치율
_SUFFIX_RATIO = 0.8       # 꼬리구 일치율
_JACCARD_AVG = 0.5        # 평균 토큰 중복률
_STDEV_RATIO = 0.05       # 토큰 수 표준편차 / 평균 임계값
_LONG_CHARS = 100         # 글자수 기준
_PREFIX_HITS = 3          # (a): 3개 이상
_SUFFIX_HITS = 4          # (b): 4개 이상
_LONG_HITS = 3            # (e): 3개 이상


_MARKER_RE = _re.compile(r'^[①②③④⑤⑥⑦⑧⑨⑩]\s*')
_WORD_RE = _re.compile(r"[A-Za-z][A-Za-z'\-]*")


def _strip_marker(c):
    """선지 앞 마커(①②...)와 양옆 공백을 제거."""
    return _MARKER_RE.sub('', (c or '').strip()).strip()


def _norm_words(text):
    """소문자화 + 영문 단어만 추출."""
    return [w.lower() for w in _WORD_RE.findall(text or '')]


def _prefix_norm(text, n):
    """앞 n단어를 소문자 영문 단어로 정규화한 튜플."""
    return tuple(_norm_words(text)[:n])


def _suffix_norm(text, n):
    """뒤 n단어를 소문자 영문 단어로 정규화한 튜플."""
    return tuple(_norm_words(text)[-n:])


def _ratio_eq(a, b):
    """두 튜플의 동일 비율 (앞에서부터 같은 위치 매칭, 길이 다르면 짧은 쪽 기준)."""
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    same = sum(1 for i in range(n) if a[i] == b[i])
    return same / n


def _max_group(items, ratio_threshold):
    """items 중 한 쌍 일치율이 threshold 이상인 '가장 큰 그룹' 크기.

    그리디로 첫 미할당 원소를 기준 삼아 임계 이상인 항목을 묶고, 그 그룹 크기를 기록.
    그 후 미할당 원소로 다시 그룹 형성. 최대 그룹 크기 반환.
    """
    assigned = [False] * len(items)
    max_size = 0
    for i in range(len(items)):
        if assigned[i]:
            continue
        group = [i]
        assigned[i] = True
        for j in range(i + 1, len(items)):
            if assigned[j]:
                continue
            if _ratio_eq(items[i], items[j]) >= ratio_threshold:
                group.append(j)
                assigned[j] = True
        if len(group) > max_size:
            max_size = len(group)
    return max_size


def _check_prefix(choices):
    """(a) 도입구 일치 그룹 크기 ≥ _PREFIX_HITS 이면 True."""
    # 5~7 윈도 중 가장 많이 묶이는 크기를 보수적으로 채택.
    best = 0
    for n in range(_PREFIX_WORDS_MIN, _PREFIX_WORDS_MAX + 1):
        prefs = [_prefix_norm(c, n) for c in choices]
        prefs = [p for p in prefs if p]   # 빈 튜플 제외
        if len(prefs) < _PREFIX_HITS:
            continue
        size = _max_group(prefs, _PREFIX_RATIO)
        if size > best:
            best = size
    return best >= _PREFIX_HITS


def _check_suffix(choices):
    """(b) 꼬리구 일치 그룹 크기 ≥ _SUFFIX_HITS 이면 True."""
    best = 0
    for n in range(_PREFIX_WORDS_MIN, _PREFIX_WORDS_MAX + 1):
        sufs = [_suffix_norm(c, n) for c in choices]
        sufs = [s for s in sufs if s]
        if len(sufs) < _SUFFIX_HITS:
            continue
        size = _max_group(sufs, _SUFFIX_RATIO)
        if size > best:
            best = size
    return best >= _SUFFIX_HITS


def _check_jaccard(choices):
    """(c) 선지 쌍 간 평균 Jaccard 중복률 ≥ _JACCARD_AVG 이면 True."""
    token_sets = [set(_norm_words(c)) for c in choices]
    token_sets = [s for s in token_sets if s]
    if len(token_sets) < 2:
        return False
    sims = []
    for i in range(len(token_sets)):
        for j in range(i + 1, len(token_sets)):
            inter = len(token_sets[i] & token_sets[j])
            union = len(token_sets[i] | token_sets[j])
            sims.append(inter / union if union else 0.0)
    return (sum(sims) / len(sims)) >= _JACCARD_AVG if sims else False


def _check_stdev(choices):
    """(d) 선지 토큰 수 표준편차가 비정상적으로 작으면 True (≤ 평균의 _STDEV_RATIO)."""
    lengths = [len(_norm_words(c)) for c in choices]
    lengths = [n for n in lengths if n > 0]
    if len(lengths) < 3:
        return False
    mean = sum(lengths) / len(lengths)
    if mean == 0:
        return False
    try:
        sd = _stat.pstdev(lengths)
    except _stat.StatisticsError:
        return False
    return (sd / mean) <= _STDEV_RATIO


def _check_long(choices):
    """(e) 보기 '모두'가 _LONG_CHARS(100자) 이상이면 True.

    사용자 정책(2026-06-28): 5개 보기 중 단 하나라도 100자 미만이면 결함
    후보에서 제외 (다른 룰도 무시). 짧은 보기('① the latest digital
    technology')가 섞여 있다면 그 문제는 결함이 아니라고 본다.
    """
    if not choices:
        return False
    return all(len(c) >= _LONG_CHARS for c in choices)


def classify_cloze_choices(choices):
    """빈칸 선지 5개를 받아 1층 룰 판정 결과를 반환.

    Parameters
    ----------
    choices : list[str]
        선지 5개 (마커 ①②③④⑤ 포함 가능, _strip_marker 로 자동 제거).

    Returns
    -------
    dict
        - flagged : bool — 한 룰이라도 걸리면 True
        - rules   : list[str] — 걸린 룰 알파벳 ('a','b','c','d','e')
        - long_count : int — 100자 이상 선지 개수 (참고용)
    """
    if not choices:
        return {'flagged': False, 'rules': [], 'long_count': 0}
    cs = [_strip_marker(c) for c in choices]
    cs = [c for c in cs if c]
    long_count = sum(1 for c in cs if len(c) >= _LONG_CHARS)
    # 사용자 정책 게이트: 보기 5개 중 하나라도 100자 미만이면 결함 후보 아님.
    # 짧은 보기가 섞인 문제는 변별이 명확하다고 본다 (1층 룰 자체를 건너뜀).
    if not all(len(c) >= _LONG_CHARS for c in cs):
        return {'flagged': False, 'rules': [], 'long_count': long_count}
    rules = []
    if _check_prefix(cs):
        rules.append('a')
    if _check_suffix(cs):
        rules.append('b')
    if _check_jaccard(cs):
        rules.append('c')
    if _check_stdev(cs):
        rules.append('d')
    if _check_long(cs):
        rules.append('e')
    return {
        'flagged': bool(rules),
        'rules': rules,
        'long_count': long_count,
    }


__all__ = ['classify_cloze_choices']
