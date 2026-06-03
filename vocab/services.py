"""단어훈련 채점 로직.

영→한 주관식 테스트: 영어 단어를 보고 한글 뜻을 입력 → 채점.
뜻은 보통 쉼표로 여러 개(예: '값이 비싼, 귀중한')이고 괄호 보충(예: '평형 (균형)')도 있어,
그 중 하나만 맞아도 정답으로 인정한다.
"""
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
