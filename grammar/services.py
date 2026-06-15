"""어법 자동채점 — 원본 엑셀 채점공식과 1:1 동일.

원본 공식:
=IF(TRIM(F3)="","",IF(OR(
  ISNUMBER(SEARCH(","&N(C3)&",", ","&N(F3)&",")),
  ISNUMBER(SEARCH("-"&N(C3)&",", ","&N(F3)&","))),"O","X"))
  N(x) = 공백 제거 + '=>'·'->'·'→' → '-' (SUBSTITUTE 4중)
  C3 = 학생 입력, F3 = 정답키
"""
import re


def _norm(s):
    """공백 제거 + 화살표(=> -> →)를 '-' 로 통일. SEARCH가 대소문자 무시이므로 소문자화."""
    s = (s or '').replace(' ', '').lower()
    for a in ('=>', '->', '→'):
        s = s.replace(a, '-')
    return s


def auto_grade(student_input, answer_key):
    """엑셀 채점공식 동일. 정답키 비면 None(채점 안 함). 그 외 True(O)/False(X)."""
    if not (answer_key or '').strip():
        return None
    si = _norm(student_input)
    hay = ',' + _norm(answer_key) + ','
    # (1) ,학생답, 토큰 완전일치   (2) -학생답, 화살표 교정 오른쪽 일치
    return (',' + si + ',') in hay or ('-' + si + ',') in hay


# 학교학년 토큰(예 '동백고2')에서 학년 추출 — 단어/요약문 패턴.
_GRADE_RE = re.compile(r'(고|중|초)\s*([1-3])')


def grade_from_school(school):
    m = _GRADE_RE.search(school or '')
    if m:
        g = m.group(1) + m.group(2)
        valid = {'초1', '초2', '초3', '초4', '초5', '초6',
                 '중1', '중2', '중3', '고1', '고2', '고3'}
        if g in valid:
            return g
    return '기타'
