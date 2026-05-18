"""학생 일괄 등록용 엑셀 파서.
형식: 1열 ID (login_id), 2열 이름
"""
import openpyxl


def parse_students_excel(file):
    errors = []
    students = []
    try:
        wb = openpyxl.load_workbook(file, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if len(rows) < 2:
            return {'success': False, 'students': [], 'errors': ['엑셀에 데이터가 없습니다.']}

        for row in rows[1:]:
            if not row or all(c is None for c in row):
                continue
            id_val = row[0] if len(row) > 0 else None
            name_val = row[1] if len(row) > 1 else None
            if id_val is None or name_val is None:
                continue
            login_id = str(id_val).strip()
            name = str(name_val).strip()
            if not login_id or not name:
                continue
            if login_id.lower() in ('id', '아이디', 'login_id'):
                continue
            students.append({'login_id': login_id, 'name': name})

        if not students:
            errors.append('유효한 학생 행이 없습니다.')
        return {'success': len(students) > 0, 'students': students, 'errors': errors}
    except Exception as e:
        return {'success': False, 'students': [], 'errors': [f'엑셀 파싱 실패: {e}']}
