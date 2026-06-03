"""
엑셀 파일 파싱 — 영작 문제 데이터 추출 + 정제 + 파일명 메타 파싱
"""
import re
from typing import Dict

import openpyxl


REQUIRED_COLUMNS = ['색인', '영어', '한글']

# 양쪽 가장자리 노이즈: 회화 표지(Q:/A:/B:/G:) · 번호(1./2./3)) · 불릿·따옴표(- • * " ')
# 정상 종결 구두점(.?!)과 단어 끝 글자는 보호.
# - 시작: 단일 알파벳 다음에 알파벳 없을 때만 (Quick: 같은 일반 단어는 안 잡힘)
# - 끝: 앞에 공백 있어야 단일 토큰 (well. 의 'l.' 같은 단어 꼬리는 안 잡힘)
_LEADING_NOISE = re.compile(
    r'^\s*(?:'
    r'[A-Za-z](?![A-Za-z])\s*[.,:]\s*'
    r'|\d+(?!\d)\s*[.)]\s*'
    r'|[-•*"\']\s*'
    r')+',
    re.UNICODE,
)
_TRAILING_NOISE = re.compile(
    r'(?:'
    r'\s+[A-Za-z]\s*[.,:]'
    r'|\s+\d+\s*[.)]'
    r'|\s*[-•*"\']'
    r')+\s*$',
    re.UNICODE,
)


def clean_prefix(text):
    """양쪽 가장자리 노이즈(Q:, A:, 1., 2., -, •, " 등) 반복 제거."""
    if text is None:
        return ''
    text = str(text).strip()
    prev = None
    while prev != text:
        prev = text
        text = _LEADING_NOISE.sub('', text)
        text = _TRAILING_NOISE.sub('', text)
        text = text.strip()
    return text


def parse_writing_excel(file) -> Dict:
    """
    엑셀에서 영작 문제 파싱 + 정제.

    엑셀 형식: 1행 헤더 (색인 | 영어 | 한글), 2행부터 데이터
    정제 규칙:
      1) 영어/한글 모두 줄 앞 노이즈 제거
      2) 영어 단어 수 ≤ 3 행은 제외

    Returns:
        {
          'success': bool,
          'problems': [{'index', 'korean', 'english'}, ...],
          'errors': [str, ...],
          'skipped_short': int,
        }
    """
    errors = []
    problems = []
    skipped_short = 0

    try:
        wb = openpyxl.load_workbook(file, data_only=True)
        ws = wb.active

        rows = list(ws.iter_rows(values_only=True))
        if len(rows) < 2:
            return {
                'success': False, 'problems': [],
                'errors': ['엑셀에 데이터가 없습니다.'], 'skipped_short': 0,
            }

        header = [str(c or '').strip() for c in rows[0]]
        if len(header) < 3:
            errors.append('컬럼이 최소 3개 필요합니다 (색인, 영어, 한글).')

        for row in rows[1:]:
            if not row or all(c is None for c in row):
                continue

            english_val = row[1] if len(row) > 1 else None
            korean_val = row[2] if len(row) > 2 else None

            # 헤더가 다시 등장하면 skip (영어 컬럼 기준)
            if isinstance(english_val, str) and english_val.strip() in ('영어', '영어 정답'):
                continue

            if not korean_val or not english_val:
                continue

            english = clean_prefix(english_val)
            korean = clean_prefix(korean_val)

            if not english or not korean:
                continue

            if len(english.split()) <= 3:
                skipped_short += 1
                continue

            # 색인 컬럼(row[0])은 무시 — 엑셀에 중복/공백이 있어도 안전하게 행 순서대로 자동 부여
            problems.append({'index': len(problems) + 1, 'korean': korean, 'english': english})

        if not problems:
            errors.append('유효한 문제 행이 없습니다.')

        return {
            'success': len(problems) > 0,
            'problems': problems,
            'errors': errors,
            'skipped_short': skipped_short,
        }
    except Exception as e:
        return {
            'success': False, 'problems': [],
            'errors': [f'엑셀 파싱 실패: {e}'], 'skipped_short': 0,
        }


# ── 파일명 → 학년/출판사/단원명 ──

_GRADE_PATTERN = re.compile(r'^(초[1-6]|중[1-3]|고[1-3])(?:\s+|$)')
# 학교명에 박힌 학년 패턴 (예: "동백중3", "성신여중1", "분당고2")
_EMBEDDED_GRADE_PATTERN = re.compile(r'(초[1-6]|중[1-3]|고[1-3])(?=\s|$)')
_TITLE_PATTERNS = [
    re.compile(r'((?:\d+\s*-\s*\d+|\d+)\s*과)'),
    re.compile(r'(\d+\s*단원)'),
    re.compile(r'(외부지문\s*\d*)'),
    re.compile(r'(Wrap\s*Up\s*\d*)', re.IGNORECASE),
    re.compile(r'(Lesson\s*\d+)', re.IGNORECASE),
    re.compile(r'(Review\s*\d*)', re.IGNORECASE),
]
# 학교 시험명 경계 (예: "기말고사", "중간고사") → '고사' 직후를 출판사/단원명 구분점으로
_EXAM_BOUNDARY = re.compile(r'고사')


def parse_filename(raw: str) -> Dict[str, str]:
    """파일명에서 학년/출판사/단원명 추출. (upload.html JS 로직과 동일)

    1) '_'가 있으면 첫 '_'를 출판사/단원명 구분자로 사용 (부교재 패턴)
       예: "리딩튜터 스타터 1_S1-1.Nature 나를 맞혀봐! (R)"
           → 출판사="리딩튜터 스타터 1", 단원명="S1-1.Nature 나를 맞혀봐! (R)"
    2) '_'가 없으면 '과/단원/Lesson/Wrap Up/Review' 키워드 기반 분리 (내신 교과서 패턴)
    """
    name = re.sub(r'\.[^.]+$', '', raw)

    grade = ''
    title = ''
    publisher = ''

    if '_' in name:
        head, _, tail = name.partition('_')
        head = head.strip()
        # 첫 '_' 앞에 학년 prefix가 있을 수 있음
        gm = _GRADE_PATTERN.match(head)
        head_grade = ''
        if gm:
            head_grade = gm.group(1)
            head = head[gm.end():].strip()
        # head가 학년만 있고 비었으면 (예: "중2_동아_3과") → 기존 로직으로 폴백
        if head:
            grade = head_grade
            publisher = re.sub(r'\s+', ' ', head).strip()
            title = re.sub(r'\s+', ' ', tail.replace('_', ' ')).strip()
            return {'grade': grade, 'publisher': publisher, 'title': title}

    name = re.sub(r'[_\-]+', ' ', name).strip()
    name = re.sub(r'\s+', ' ', name)

    gm = _GRADE_PATTERN.match(name)
    if gm:
        grade = gm.group(1)
        name = name[gm.end():].strip()
    else:
        # 시작에 학년이 없으면 본문 내 임베디드 패턴 (학교명 안의 학년) 검색
        # 예: "2026년 동백중3 1학기 기말고사 외부지문 1" → "중3"
        em = _EMBEDDED_GRADE_PATTERN.search(name)
        if em:
            grade = em.group(1)
            # 출판사 문자열은 그대로 유지 (학교명 포함된 채로)

    # 시험명(기말고사/중간고사 등)이 있으면 '고사' 직후를 출판사/단원명 경계로 사용
    # 예: "2026년 동백고2 1학기 기말고사 올림포스2 전국연합 part1"
    #     → 출판사 "2026년 동백고2 1학기 기말고사" / 단원명 "올림포스2 전국연합 part1"
    exam_m = _EXAM_BOUNDARY.search(name)
    if exam_m:
        head = re.sub(r'\s+', ' ', name[:exam_m.end()]).strip()
        tail = re.sub(r'\s+', ' ', name[exam_m.end():]).strip()
        if tail:
            return {'grade': grade, 'publisher': head, 'title': tail}

    match_idx = -1
    for re_p in _TITLE_PATTERNS:
        m = re_p.search(name)
        if m:
            # 첫 매치 위치부터 파일명 끝까지를 단원명으로 (예: "1과 본문1", "3과 Wrap Up")
            title = re.sub(r'\s+', ' ', name[m.start():]).strip()
            match_idx = m.start()
            break

    if match_idx >= 0:
        publisher = name[:match_idx].strip()
    else:
        tokens = name.split()
        if len(tokens) >= 2:
            title = tokens[-1]
            publisher = ' '.join(tokens[:-1])
        elif len(tokens) == 1 and tokens[0]:
            title = tokens[0]

    return {'grade': grade, 'publisher': publisher, 'title': title}
