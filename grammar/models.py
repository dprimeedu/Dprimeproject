"""어법(문법) 시험 — 구글 어법시험을 웹으로. vocab/summary 패턴.

문항: 문장(어법포인트 [표시]/①~⑤) + 정답키('O' / 'wrong->right' / 다중 'a, b').
채점: services.auto_grade (엑셀 채점공식 동일) → 자동채점 후 X 위주 교사 검수.
"""
from django.conf import settings
from django.db import models


GRADE_CHOICES = [(g, g) for g in (
    '초1', '초2', '초3', '초4', '초5', '초6',
    '중1', '중2', '중3', '고1', '고2', '고3', '기타',
)]


class GrammarUnit(models.Model):
    """어법 단원 (학교/교재 단위)."""
    school = models.CharField(max_length=50, blank=True, default='', verbose_name='학교')
    exam = models.CharField(max_length=100, blank=True, default='', verbose_name='시험/교재')
    title = models.CharField(max_length=200, verbose_name='단원명')
    grade = models.CharField(max_length=10, choices=GRADE_CHOICES, default='기타', verbose_name='학년')
    description = models.CharField(max_length=300, blank=True, default='')
    is_active = models.BooleanField(default=True, verbose_name='활성화')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='grammar_units_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'grammar_unit'
        verbose_name = '어법 단원'
        verbose_name_plural = '어법 단원'
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    @property
    def problem_count(self):
        return self.problems.count()


class GrammarProblem(models.Model):
    """어법 문항 — 문장 + 정답키."""
    unit = models.ForeignKey(GrammarUnit, on_delete=models.CASCADE, related_name='problems')
    index = models.IntegerField(verbose_name='번호')
    sentence = models.TextField(verbose_name='문장')               # 어법포인트 [표시]/①~⑤ 포함
    answer = models.CharField(max_length=300, blank=True, default='', verbose_name='정답키')  # 'O' / 'had->has' / 'a, b'
    sub_unit = models.CharField(max_length=50, blank=True, default='', verbose_name='소단원')  # 3-1 등
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'grammar_problem'
        verbose_name = '어법 문항'
        verbose_name_plural = '어법 문항'
        ordering = ['unit', 'index']
        unique_together = [['unit', 'index']]

    def __str__(self):
        return f'{self.unit_id} #{self.index}'


class GrammarAssignment(models.Model):
    """선생님이 학생에게 어법 단원 배정."""
    unit = models.ForeignKey(GrammarUnit, on_delete=models.CASCADE, related_name='assignments')
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='grammar_assignments')
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='grammar_assignments_made')
    assigned_at = models.DateTimeField(auto_now_add=True)
    due_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'grammar_assignment'
        verbose_name = '어법 배정'
        verbose_name_plural = '어법 배정'
        unique_together = [['student', 'unit']]


class GrammarSession(models.Model):
    """학생이 어법 TEST를 보는 한 번의 세션."""
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_SUBMITTED = 'submitted'
    STATUS_GRADED = 'graded'
    STATUS_CHOICES = [
        (STATUS_IN_PROGRESS, '진행 중'),
        (STATUS_SUBMITTED, '채점 대기'),
        (STATUS_GRADED, '채점 완료'),
    ]
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='grammar_sessions')
    unit = models.ForeignKey(GrammarUnit, on_delete=models.CASCADE, related_name='sessions')
    start_index = models.IntegerField(null=True, blank=True, verbose_name='시작 문항')
    end_index = models.IntegerField(null=True, blank=True, verbose_name='끝 문항')
    # 이 세션이 실제 출제한 문항 번호들(JSON 리스트). 랜덤 40개 비순차 출제용 — 있으면 start/end보다 우선.
    problem_indices = models.TextField(blank=True, default='', verbose_name='출제 문항(JSON)')
    set_no = models.IntegerField(null=True, blank=True, verbose_name='세트 번호')
    # 차시 — 1차시(처음 풀기) → 2차시(교사가 X 준 문제만 다시 풀기) → 3차시 …
    round_no = models.IntegerField(default=1, verbose_name='차시')
    parent = models.ForeignKey(
        'self', on_delete=models.CASCADE, null=True, blank=True,
        related_name='retries', verbose_name='이전 차시')
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_IN_PROGRESS, db_index=True)
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    correct_count = models.IntegerField(default=0)
    total_count = models.IntegerField(default=0)
    graded_at = models.DateTimeField(null=True, blank=True)
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='grammar_sessions_graded')

    class Meta:
        db_table = 'grammar_session'
        verbose_name = '어법 세션'
        verbose_name_plural = '어법 세션'
        ordering = ['-started_at']

    @property
    def percent(self):
        return round(self.correct_count / self.total_count * 100) if self.total_count else 0

    @property
    def round_label(self):
        return f'{self.round_no}차시'

    @property
    def range_label(self):
        if self.set_no:
            base = f'세트{self.set_no}'
        elif self.start_index and self.end_index:
            base = f'{self.start_index}~{self.end_index}'
        else:
            base = '전체'
        return f'{base} · {self.round_no}차시' if self.round_no and self.round_no > 1 else base


class GrammarWrongAnswer(models.Model):
    """학생 개인 어법 오답 — 교사 검수에서 X 확정된 문항. 틀린횟수 누적(구글 E열 패턴)."""
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='grammar_wrong_answers')
    problem = models.ForeignKey(GrammarProblem, on_delete=models.CASCADE, related_name='wrong_answers')
    wrong_count = models.IntegerField(default=1, verbose_name='틀린 횟수')
    resolved = models.BooleanField(default=False, verbose_name='해결됨(맞춤)')
    last_wrong_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'grammar_wrong_answer'
        verbose_name = '어법 개인오답'
        verbose_name_plural = '어법 개인오답'
        unique_together = [['student', 'problem']]
        ordering = ['-wrong_count', '-last_wrong_at']


class GrammarAnswer(models.Model):
    """세션 × 문항 한 칸의 응답 + 자동채점/교사판정."""
    VERDICT_CHOICES = [('O', 'O'), ('X', 'X')]
    session = models.ForeignKey(GrammarSession, on_delete=models.CASCADE, related_name='answers')
    problem = models.ForeignKey(GrammarProblem, on_delete=models.CASCADE)
    student_input = models.CharField(max_length=300, blank=True, default='', verbose_name='학생 입력')
    auto_correct = models.BooleanField(default=False, verbose_name='자동채점 정답')   # auto_grade 결과
    correct_answer = models.CharField(max_length=300, blank=True, default='', verbose_name='정답(스냅샷)')
    admin_verdict = models.CharField(
        max_length=1, null=True, blank=True, choices=VERDICT_CHOICES, verbose_name='관리자 판정')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'grammar_answer'
        verbose_name = '어법 응답'
        verbose_name_plural = '어법 응답'
        ordering = ['session', 'problem__index']
        unique_together = [['session', 'problem']]

    @property
    def is_correct(self):
        """최종 정오 — 교사 판정 우선, 없으면 자동채점."""
        if self.admin_verdict:
            return self.admin_verdict == 'O'
        return self.auto_correct


class GrammarRangeTest(models.Model):
    """오늘 볼 어법 TEST — 학생관리표 '어법TEST' 열에서 동기화(단어 RangeTest 패턴)."""
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='grammar_range_tests')
    unit = models.ForeignKey(GrammarUnit, on_delete=models.CASCADE, related_name='range_tests')
    start_index = models.IntegerField(null=True, blank=True)
    end_index = models.IntegerField(null=True, blank=True)
    source_label = models.CharField(max_length=100, blank=True, default='어법TEST')
    pass_threshold = models.IntegerField(default=90, verbose_name='합격 기준(%)')
    is_active = models.BooleanField(default=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='grammar_range_tests_made')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'grammar_range_test'
        verbose_name = '어법 오늘볼TEST'
        verbose_name_plural = '어법 오늘볼TEST'
        ordering = ['-created_at']

    @property
    def range_label(self):
        if self.start_index and self.end_index:
            return f'{self.start_index}~{self.end_index}'
        return '전체'
