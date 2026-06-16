"""교사용 '채점대기' 뱃지 — 전역 템플릿에서 쓸 수 있게 카운트를 주입.

- grammar_pending : 어법 채점대기(학생 제출 후 교사 검수 전) 세션 수
- exam_pending    : 내신/모의 교사 미확인(자동채점됐지만 교사가 결과를 아직 안 연) 세션 수

교사(is_teacher)가 아니면 0 — 학생 페이지엔 영향 없음.
"""


def pending_badges(request):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}

    try:
        from writing.views import is_teacher
        if not is_teacher(user):
            return {}
    except Exception:
        return {}

    grammar_pending = exam_pending = 0
    try:
        from grammar.models import GrammarSession
        grammar_pending = GrammarSession.objects.filter(
            status=GrammarSession.STATUS_SUBMITTED).count()
    except Exception:
        pass
    try:
        from exam.models import ExamSession
        exam_pending = ExamSession.objects.filter(
            status=ExamSession.STATUS_GRADED, teacher_checked=False).count()
    except Exception:
        pass

    return {'grammar_pending': grammar_pending, 'exam_pending': exam_pending}
