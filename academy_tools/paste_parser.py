"""
스프레드시트 일괄 입력 파서.

Tkinter PasteSheetFrame 규약을 그대로 따른다:
    [학교명] <TAB> [교재구분] <TAB> [교재명] <TAB> [시험범위]

시험범위는 줄바꿈 가능. 두 가지 모드를 지원:
    - 부교재 모드: '9 - 5,6,7,8' 형식 (단원 - 번호 리스트)
    - 모의고사 모드: 교재명에 'YYYY년 M월 고N' 포함, 시험범위는 번호 리스트
"""
import csv
import io
import re


UNIT_NUM_LINE_RE = re.compile(r'^([^-–]+?)\s*[-–]\s*(.+)$')
RANGE_TOKEN_RE = re.compile(r'^(\d+)\s*[~–]\s*(\d+)$')


def _expand_tokens(text: str):
    out = []
    for token in re.split(r'[,/\s]+', text or ''):
        token = token.strip()
        if not token:
            continue
        m = RANGE_TOKEN_RE.match(token)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            lo, hi = (a, b) if a <= b else (b, a)
            for n in range(lo, hi + 1):
                s = str(n)
                if s not in out:
                    out.append(s)
        else:
            if token not in out:
                out.append(token)
    return out


def _parse_row(text: str):
    """붙여넣은 텍스트를 (학교명, 교재구분, 교재명, 시험범위) 튜플로 분리."""
    try:
        rows = [r for r in csv.reader(io.StringIO(text), delimiter='\t')
                if any(c.strip() for c in r)]
    except Exception:
        rows = []

    if rows:
        cells = [c.strip() for c in rows[0]]
        while cells and not cells[-1]:
            cells.pop()
        if len(cells) >= 4:
            return cells[0], cells[1], cells[2], cells[3]
        if len(cells) == 3:
            return cells[0], '', cells[1], cells[2]
        if len(cells) == 2:
            return cells[0], '', '', cells[1]
        if len(cells) == 1:
            if '\n' in text or re.search(r'\d+\s*[-–]\s*\d', text):
                return '', '', '', text

    if re.search(r'\d+\s*[-–]\s*\d', text):
        return '', '', '', text
    return None


def _is_test_kind(kind: str, book: str) -> bool:
    return bool((kind and '모의고사' in kind) or (book and '모의고사' in book))


def _parse_ranges(ranges_text: str):
    """'9 - 5,6,7,8\\n10 - 5,6,7,8' → 단원·번호 양쪽 unique 리스트."""
    units, numbers = [], []
    for raw in (ranges_text or '').splitlines():
        line = raw.strip().strip('"').strip()
        if not line:
            continue
        m = UNIT_NUM_LINE_RE.match(line)
        if not m:
            continue
        for u in _expand_tokens(m.group(1)):
            if u not in units:
                units.append(u)
        for n in _expand_tokens(m.group(2)):
            if n not in numbers:
                numbers.append(n)
    return units, numbers


def _parse_test_meta(book: str, school: str):
    """교재명/학교명에서 학년/연도/월 추출. 실패 시 None."""
    grade_m = re.search(r'고(\d)', book or '') or re.search(r'고(\d)', school or '')
    year_m = re.search(r'(\d{4})\s*년', book or '')
    month_m = re.search(r'(\d{1,2})\s*월', book or '')
    if not (grade_m and year_m and month_m):
        return None
    return {
        'grade': f'고{grade_m.group(1)}',
        'year': year_m.group(1),
        'month': month_m.group(1).lstrip('0') or '0',  # KEY_TABLE.month는 '3' 형태
    }


def _parse_test_numbers(ranges_text: str):
    """모의고사 번호 토큰을 풀어 unique 리스트로."""
    nums = []
    for tok in re.split(r'[,/\s]+', ranges_text or ''):
        tok = tok.strip().strip('"').strip()
        if not tok:
            continue
        rm = re.match(r'^(\d+)\s*[~–-]\s*(\d+)$', tok)
        if rm:
            a, b = int(rm.group(1)), int(rm.group(2))
            lo, hi = (a, b) if a <= b else (b, a)
            for n in range(lo, hi + 1):
                s = str(n)
                if s not in nums:
                    nums.append(s)
        elif tok.isdigit():
            if tok not in nums:
                nums.append(tok)
    return nums


def parse_paste(text: str) -> dict:
    """
    붙여넣기 텍스트를 파싱해 JSON-friendly dict 반환.

    Returns:
        {
            'ok': bool,
            'error': str | None,
            'mode': '부교재' | '모의고사' | None,
            'school': str,
            'book': str,
            'grade': str | None,
            'units': [str],     # 부교재: 단원 / 모의고사: [월]
            'numbers': [str],
        }
    """
    text = (text or '').strip()
    if not text:
        return {'ok': False, 'error': '입력된 내용이 없습니다.'}

    parsed = _parse_row(text)
    if parsed is None:
        return {'ok': False, 'error': '형식을 인식할 수 없습니다.'}

    school, kind, book, ranges_text = parsed

    if _is_test_kind(kind, book):
        meta = _parse_test_meta(book, school)
        if meta is None:
            return {'ok': False, 'error': '모의고사 학년/연도/월을 인식할 수 없습니다.'}
        nums = _parse_test_numbers(ranges_text)
        if not nums:
            return {'ok': False, 'error': '모의고사 번호를 인식할 수 없습니다.'}
        return {
            'ok': True,
            'error': None,
            'mode': '모의고사',
            'school': school,
            'book': book,
            'grade': meta['grade'],
            'year': meta['year'],
            'units': [meta['month']],
            'numbers': nums,
        }

    units, numbers = _parse_ranges(ranges_text)
    if not units or not numbers:
        return {'ok': False, 'error': "시험범위를 인식할 수 없습니다. (예: '9 - 5,6,7,8')"}

    return {
        'ok': True,
        'error': None,
        'mode': '부교재',
        'school': school,
        'book': book,
        'grade': None,  # 부교재는 학년 정보 없음
        'units': units,
        'numbers': numbers,
    }
