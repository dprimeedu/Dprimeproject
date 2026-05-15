"""
엑셀 파일 파싱 — 영작 문제 데이터 추출
"""
from typing import List, Dict
import openpyxl


REQUIRED_COLUMNS = ['색인', '한글', '영어']


def parse_writing_excel(file) -> Dict:
    """
    엑셀 파일에서 영작 문제 파싱.

    엑셀 형식: 1행에 헤더 (색인 | 한글 및 힌트 | 영어)
              2행부터 데이터

    Returns:
        {
          'success': bool,
          'problems': [{'index': 1, 'korean': '...', 'english': '...'}, ...],
          'errors': ['...']
        }
    """
    errors = []
    problems = []

    try:
        wb = openpyxl.load_workbook(file, data_only=True)
        ws = wb.active

        rows = list(ws.iter_rows(values_only=True))
        if len(rows) < 2:
            return {'success': False, 'problems': [], 'errors': ['엑셀에 데이터가 없습니다.']}

        # 헤더 검증 (느슨하게 — 컬럼명 포함만 확인)
        header = [str(c or '').strip() for c in rows[0]]
        if len(header) < 3:
            errors.append('컬럼이 최소 3개 필요합니다 (색인, 한글, 영어).')

        # 데이터 행 파싱
        for row_num, row in enumerate(rows[1:], start=2):
            if not row or all(c is None for c in row):
                continue

            index_val = row[0] if len(row) > 0 else None
            korean_val = row[1] if len(row) > 1 else None
            english_val = row[2] if len(row) > 2 else None

            # 헤더가 다시 등장하면 skip
            if isinstance(korean_val, str) and korean_val.strip() == '한글 및 힌트':
                continue
            if isinstance(korean_val, str) and korean_val.strip() == '한글':
                continue

            if not korean_val or not english_val:
                continue  # 빈 행 skip

            try:
                if index_val is None or index_val == '':
                    idx = len(problems) + 1
                else:
                    idx = int(index_val)
            except (ValueError, TypeError):
                idx = len(problems) + 1

            problems.append({
                'index': idx,
                'korean': str(korean_val).strip(),
                'english': str(english_val).strip(),
            })

        if not problems:
            errors.append('유효한 문제 행이 없습니다.')

        return {
            'success': len(problems) > 0,
            'problems': problems,
            'errors': errors,
        }

    except Exception as e:
        return {
            'success': False,
            'problems': [],
            'errors': [f'엑셀 파싱 실패: {e}'],
        }
