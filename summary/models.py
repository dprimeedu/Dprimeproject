from django.db import models
from django.conf import settings


class SummaryUnit(models.Model):
    """요약문완성 훈련 단원 — 학교/단원 단위 (예: 백현고1 3과).

    하나의 통합본 xlsx 한 학교(+단원) = 하나의 SummaryUnit.
    (school, unit) 조합이 재import 시 replace 키.
    """
    GRADE_CHOICES = [
        ('초1', '초1'), ('초2', '초2'), ('초3', '초3'),
        ('초4', '초4'), ('초5', '초5'), ('초6', '초6'),
        ('중1', '중1'), ('중2', '중2'), ('중3', '중3'),
        ('고1', '고1'), ('고2', '고2'), ('고3', '고3'),
        ('기타', '기타'),
    ]

    school = models.CharField(max_length=100, blank=True, default='', verbose_name='학교')
    unit = models.CharField(max_length=100, blank=True, default='', verbose_name='단원')
    title = models.CharField(max_length=200, verbose_name='단원명')
    grade = models.CharField(max_length=10, choices=GRADE_CHOICES, default='기타', verbose_name='학년')
    description = models.TextField(blank=True, verbose_name='설명')
    is_active = models.BooleanField(default=True, verbose_name='활성화')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_summary_units',
        verbose_name='등록자',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'summary_unit'
        verbose_name = '요약문 단원'
        verbose_name_plural = '요약문 단원'
        ordering = ['-created_at']
        unique_together = [['school', 'unit']]

    def __str__(self):
        return self.title or f'{self.school} {self.unit}'

    @property
    def problem_count(self):
        # bulk prefetch가 self._problem_count 를 채워두면 그 값을 사용 (N+1 방지)
        if '_problem_count' in self.__dict__:
            return self._problem_count
        return self.problems.count()


class SummaryProblem(models.Model):
    """단원 내 한 요약문완성 문항 (2문장, 빈칸 ⓐ/ⓑ)."""
    unit = models.ForeignKey(
        SummaryUnit, on_delete=models.CASCADE,
        related_name='problems', verbose_name='단원',
    )
    index = models.IntegerField(verbose_name='색인')
    sub_unit = models.CharField(max_length=100, blank=True, default='', verbose_name='소단원')

    sentence1_template = models.TextField(verbose_name='문장1(ⓐ 포함)')
    sentence1_answer = models.CharField(max_length=200, verbose_name='정답 ⓐ')
    korean1 = models.CharField(max_length=200, blank=True, default='', verbose_name='한글뜻 ⓐ')

    sentence2_template = models.TextField(verbose_name='문장2(ⓑ 포함)')
    sentence2_answer = models.CharField(max_length=200, verbose_name='정답 ⓑ')
    korean2 = models.CharField(max_length=200, blank=True, default='', verbose_name='한글뜻 ⓑ')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'summary_problem'
        verbose_name = '요약문 문항'
        verbose_name_plural = '요약문 문항'
        ordering = ['unit', 'index']
        unique_together = [['unit', 'index']]

    def __str__(self):
        return f'{self.unit.title} #{self.index}'

    def answer_for(self, blank):
        return self.sentence1_answer if blank == 'a' else self.sentence2_answer

    def korean_for(self, blank):
        return self.korean1 if blank == 'a' else self.korean2


class SummaryAssignment(models.Model):
    """선생님이 학생에게 요약문 단원 배정."""
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='summary_assignments',
        verbose_name='학생',
    )
    unit = models.ForeignKey(
        SummaryUnit, on_delete=models.CASCADE,
        related_name='assignments', verbose_name='단원',
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='summary_assignments_made',
        verbose_name='배정자',
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    due_date = models.DateTimeField(null=True, blank=True, verbose_name='마감일')

    class Meta:
        db_table = 'summary_assignment'
        verbose_name = '요약문 단원 배정'
        verbose_name_plural = '요약문 단원 배정'
        unique_together = [['student', 'unit']]
        ordering = ['-assigned_at']

    def __str__(self):
        return f'{self.student.username} ← {self.unit.title}'


class SummarySession(models.Model):
    """학생이 한 단원 요약문완성 TEST를 보는 한 번의 세션."""
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_SUBMITTED = 'submitted'
    STATUS_GRADED = 'graded'
    STATUS_CHOICES = [
        (STATUS_IN_PROGRESS, '진행 중'),
        (STATUS_SUBMITTED, '채점 대기'),
        (STATUS_GRADED, '채점 완료'),
    ]

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='summary_sessions',
    )
    unit = models.ForeignKey(SummaryUnit, on_delete=models.CASCADE, related_name='sessions')
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_IN_PROGRESS,
        db_index=True, verbose_name='상태',
    )
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True, verbose_name='제출 시각')

    correct_count = models.IntegerField(default=0, verbose_name='맞은 개수')
    total_blanks = models.IntegerField(default=0, verbose_name='전체 빈칸 수')

    graded_at = models.DateTimeField(null=True, blank=True)
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='summary_sessions_graded', verbose_name='채점자',
    )

    class Meta:
        db_table = 'summary_session'
        verbose_name = '요약문 세션'
        verbose_name_plural = '요약문 세션'
        ordering = ['-started_at']

    def __str__(self):
        return f'{self.student.username} - {self.unit.title} ({self.started_at:%Y-%m-%d %H:%M})'

    @property
    def percent(self):
        return round(self.correct_count / self.total_blanks * 100) if self.total_blanks else 0


class SummaryBlankAnswer(models.Model):
    """세션 × 문항 × 빈칸(ⓐ/ⓑ) 한 칸의 응답 + 관리자 판정."""
    BLANK_CHOICES = [('a', 'ⓐ'), ('b', 'ⓑ')]
    VERDICT_CHOICES = [('O', 'O'), ('X', 'X')]

    session = models.ForeignKey(
        SummarySession, on_delete=models.CASCADE, related_name='blank_answers',
    )
    problem = models.ForeignKey(SummaryProblem, on_delete=models.CASCADE)
    blank = models.CharField(max_length=1, choices=BLANK_CHOICES, verbose_name='빈칸')

    first_input = models.CharField(max_length=200, blank=True, default='', verbose_name='1차 입력')
    first_auto_correct = models.BooleanField(default=False, verbose_name='1차 자동 정답')
    korean_shown = models.BooleanField(default=False, verbose_name='한글뜻 노출')
    second_input = models.CharField(max_length=200, blank=True, default='', verbose_name='2차 입력')

    correct_answer = models.CharField(max_length=200, blank=True, default='', verbose_name='정답(스냅샷)')
    admin_verdict = models.CharField(
        max_length=1, null=True, blank=True, choices=VERDICT_CHOICES, verbose_name='관리자 판정',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'summary_blank_answer'
        verbose_name = '요약문 빈칸 응답'
        verbose_name_plural = '요약문 빈칸 응답'
        ordering = ['session', 'problem__index', 'blank']
        unique_together = [['session', 'problem', 'blank']]
        indexes = [models.Index(fields=['session', 'problem'])]

    def __str__(self):
        return f'{self.session_id} #{self.problem.index}-{self.blank}'

    @property
    def final_input(self):
        """관리자 채점 대상 = 2차 입력 우선, 없으면 1차."""
        return self.second_input or self.first_input
