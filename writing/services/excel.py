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

            index_val = row[0] if len(row) > 0 else None
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

            try:
                idx = int(index_val) if index_val not in (None, '') else len(problems) + 1
            except (ValueError, TypeError):
                idx = len(problems) + 1

            problems.append({'index': idx, 'korean': korean, 'english': english})

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
_TITLE_PATTERNS = [
    re.compile(r'((?:\d+\s*-\s*\d+|\d+)\s*과)'),
    re.compile(r'(\d+\s*단원)'),
    re.compile(r'(Wrap\s*Up\s*\d*)', re.IGNORECASE),
    re.compile(r'(Lesson\s*\d+)', re.IGNORECASE),
    re.compile(r'(Review\s*\d*)', re.IGNORECASE),
]


def parse_filename(raw: str) -> Dict[str, str]:
    """파일명에서 학년/출판사/단원명 추출. (기존 upload.html JS 로직과 동일)"""
    name = re.sub(r'\.[^.]+$', '', raw)
    name = re.sub(r'[_\-]+', ' ', name).strip()

    grade = ''
    title = ''
    publisher = ''

    gm = _GRADE_PATTERN.match(name)
    if gm:
        grade = gm.group(1)
        name = name[gm.end():].strip()

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
