"""학교·학년 기반 단원 자동배정 공용 헬퍼.

학생(Member)은 school(예 '동백중') + grade(예 '중2')를 가진다.
단원은 학교 토큰이 박힌 문자열을 가진다(앱마다 필드가 다름):
  - writing : unit.publisher  ('2026년 동백중2 1학기 기말고사')
  - summary : unit.school     ('동백고2')
  - vocab   : unit.school     ('청덕고3')

매칭 규칙: 학생.grade == 단원.grade  AND  학생.school 이 단원 토큰 문자열에 포함.
(grade가 학교토큰의 학년(동백중2 vs 동백중3)을 구분해 주므로 교차배정 방지.)
"""
import re

from django.contrib.auth import get_user_model

# '동백중2' / '청덕고3' / '성신여중1' → (학교, 학년)
_SG_RE = re.compile(r'^(.*[초중고])\s*([1-3])$')


def split_school_grade(token):
    """학교학년 토큰을 (school, grade)로 분해.
    '동백중2' → ('동백중', '중2'),  '청덕고3' → ('청덕고', '고3').
    형식이 안 맞으면 (원문, '')."""
    token = (token or '').strip()
    m = _SG_RE.match(token)
    if not m:
        return token, ''
    school = m.group(1).strip()
    grade = school[-1] + m.group(2)  # '중' + '2'
    return school, grade


def matching_student_ids(grade, token_text):
    """grade('중2')와 token_text(학교토큰 포함 문자열)에 매칭되는 활성 학생 id 목록."""
    grade = (grade or '').strip()
    token_text = (token_text or '').strip()
    if not grade or not token_text:
        return []
    User = get_user_model()
    cands = (User.objects
             .filter(member_type='user', is_active=True, grade=grade)
             .exclude(school='')
             .values_list('id', 'school'))
    return [pk for pk, sch in cands if sch and sch in token_text]


def auto_assign_unit(unit, token_text, AssignmentModel, assigned_by=None):
    """단원 1개를 매칭 학생들에게 배정. 이미 배정된 건 무시(ignore_conflicts).
    매칭된 학생 수를 반환."""
    grade = getattr(unit, 'grade', '') or ''
    ids = matching_student_ids(grade, token_text)
    if not ids:
        return 0
    AssignmentModel.objects.bulk_create(
        [AssignmentModel(student_id=i, unit=unit, assigned_by=assigned_by) for i in ids],
        ignore_conflicts=True,
    )
    return len(ids)
