"""시험 응시·자동채점 모델 (통합형).

하나의 ExamPaper(시험지)로 출처 두 종류를 모두 표현한다.
- source='mock' : 모의고사. academy.QuestionData(managed=False)를 (학년·연도·강)으로
                  실시간 조회해 출제(문항을 따로 저장하지 않음).
- source='naesin': 내신. 외부(엑셀답지생성 흐름)에서 import API로 푸시한 정답을
                   ExamQuestion 으로 저장해 출제. category(Part1~4/내신TEST/내신객관식빈칸)별 1장.

채점은 객관식(1~5) 숫자 비교 자동채점(제출 즉시 graded). 구조·컨벤션은 summary 앱을 따른다.
"""
from django.conf import settings
from django.db import models


class ExamPaper(models.Model):
    """시험지 1장. 모의고사 1회분 또는 내신 카테고리 1개."""
    SOURCE_MOCK = 'mock'
    SOURCE_NAESIN = 'naesin'
    SOURCE_CHOICES = [(SOURCE_MOCK, '모의고사'), (SOURCE_NAESIN, '내신')]

    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, db_index=True)
    title = models.CharField('시험명', max_length=200, blank=True, default='')

    # 모의고사용 (QuestionData 조회 키)
    grade = models.CharField('학년', max_length=10, blank=True, default='')
    year = models.CharField('연도', max_length=4, blank=True, default='')
    month = models.CharField('강', max_length=50, blank=True, default='')

    # 내신용
    school_grade = models.CharField('학교학년', max_length=50, blank=True, default='')  # 예: 동백고2
    season = models.CharField('시험명/시즌', max_length=100, blank=True, default='')     # 예: 2026 1학기 기말
    category = models.CharField('카테고리', max_length=50, blank=True, default='')        # Part1~4/내신TEST/내신객관식빈칸

    # 시험일 — 응시 화면에서 'D-day / 남은 수업' 계산용 (선택)
    exam_date = models.DateField('시험일', null=True, blank=True)
    # 하루 목표 문항 수 — 제출 확인창에 '오늘 목표 N 중 M 제출' (0이면 전체 기준)
    daily_goal = models.IntegerField('하루 목표 문항', default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'exam_paper'
        verbose_name = '시험지'
        verbose_name_plural = '시험지'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'grade', 'year', 'month', 'school_grade', 'season', 'category'],
                name='exam_paper_identity',
            ),
        ]

    def __str__(self):
        return self.resolved_title

    @property
    def resolved_title(self):
        if self.title:
            return self.title
        if self.source == self.SOURCE_MOCK:
            return f'{self.year} {self.grade} {self.month}'.strip()
        return f'{self.school_grade} {self.season} {self.category}'.strip()

    def get_questions(self):
        """출제 문항을 정규화된 dict 리스트로 반환.

        반환 항목: {number, qtype, answer, passage, question, choices}
        - mock  : academy.QuestionData 실시간 조회 (passage/question/choices 포함)
        - naesin: ExamQuestion (passage/question/choices 없음 — 번호+정답만)
        """
        if self.source == self.SOURCE_MOCK:
            from academy.models import QuestionData
            qs = (QuestionData.objects
                  .filter(학년=self.grade, 연도=self.year, 강=self.month)
                  .order_by('번호'))
            return [{
                'number': q.번호,
                'qtype': q.유형 or '',
                'answer': (q.정답 or '').strip(),
                'passage': q.지문 or '',
                'question': q.문제 or '',
                'choices': q.보기 or '',
                'ref_number': '', 'text': '', 'explanation': '', 'explanation_image': '',
            } for q in qs]
        return [{
            'number': q.number,
            'qtype': q.qtype or '',
            'answer': (q.answer or '').strip(),
            'passage': '', 'question': '', 'choices': '',
            'ref_number': q.ref_number or '',
            'text': q.text or '',
            'explanation': q.explanation or '',
            'explanation_image': (q.explanation_image.url if q.explanation_image else ''),
        } for q in self.questions.all().order_by('number')]


class ExamQuestion(models.Model):
    """내신 시험지의 문항(번호·정답·유형 + 지문/관련번호/해설). 모의고사는 QuestionData를 쓴다."""
    paper = models.ForeignKey(ExamPaper, on_delete=models.CASCADE, related_name='questions')
    number = models.IntegerField('번호')
    answer = models.CharField('정답', max_length=50, blank=True, default='')
    qtype = models.CharField('유형', max_length=100, blank=True, default='')
    # 추가 자료(2026-06-12~) — 답지 푸시에서 같이 올림. 채점/리뷰·오답 DB 활용용.
    ref_number = models.CharField('관련번호', max_length=50, blank=True, default='')   # 예: 모고번호/출처번호
    text = models.TextField('지문/문제', blank=True, default='')
    explanation = models.TextField('상세 해설', blank=True, default='')
    # 빨파정답 등 해설 이미지 — 로컬→서버 업로드(구글드라이브 대체). /media/ 로 서빙.
    explanation_image = models.ImageField('해설 이미지', upload_to='exam/explain/%Y/%m/',
                                          null=True, blank=True)

    class Meta:
        db_table = 'exam_question'
        verbose_name = '시험 문항'
        verbose_name_plural = '시험 문항'
        ordering = ['paper', 'number']
        unique_together = [['paper', 'number']]

    def __str__(self):
        return f'{self.paper_id} #{self.number}={self.answer}'


class ExamAssignment(models.Model):
    """선생님이 학생에게 시험지를 배정."""
    paper = models.ForeignKey(ExamPaper, on_delete=models.CASCADE, related_name='assignments')
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='exam_assignments', verbose_name='학생',
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='exam_assignments_made', verbose_name='배정자',
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    due_date = models.DateTimeField(null=True, blank=True, verbose_name='마감일')

    class Meta:
        db_table = 'exam_assignment'
        verbose_name = '시험 배정'
        verbose_name_plural = '시험 배정'
        unique_together = [['paper', 'student']]
        ordering = ['-assigned_at']

    def __str__(self):
        return f'{self.student.username} ← {self.paper.resolved_title}'


class ExamSession(models.Model):
    """학생이 한 시험지를 응시한 한 번의 세션."""
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_SUBMITTED = 'submitted'
    STATUS_GRADED = 'graded'
    STATUS_CHOICES = [
        (STATUS_IN_PROGRESS, '진행 중'),
        (STATUS_SUBMITTED, '제출됨'),
        (STATUS_GRADED, '채점 완료'),
    ]

    paper = models.ForeignKey(ExamPaper, on_delete=models.CASCADE, related_name='sessions')
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='exam_sessions',
    )
    status = models.CharField(
        max_length=12, choices=STATUS_CHOICES, default=STATUS_IN_PROGRESS,
        db_index=True, verbose_name='상태',
    )
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True, verbose_name='제출 시각')

    correct_count = models.IntegerField(default=0, verbose_name='맞은 개수')
    total_questions = models.IntegerField(default=0, verbose_name='전체 문항 수')

    # 회차: 1=1차 채점 완료, 2=틀린문제 재시험(2차)까지 완료
    round = models.IntegerField('회차', default=1)
    round2_at = models.DateTimeField('2차 제출 시각', null=True, blank=True)
    correct_count2 = models.IntegerField('2차 맞은 개수', default=0)

    graded_at = models.DateTimeField(null=True, blank=True)
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='exam_sessions_graded', verbose_name='채점자',
    )

    # 교사가 결과를 한 번이라도 열어 확인했는지(자동채점이라 '채점대기' 대신 '미확인' 뱃지 기준)
    teacher_checked = models.BooleanField('교사 확인', default=False, db_index=True)

    class Meta:
        db_table = 'exam_session'
        verbose_name = '시험 세션'
        verbose_name_plural = '시험 세션'
        ordering = ['-started_at']

    def __str__(self):
        return f'{self.student.username} - {self.paper.resolved_title} ({self.started_at:%Y-%m-%d %H:%M})'

    @property
    def title(self):
        return self.paper.resolved_title

    @property
    def percent(self):
        return round(self.correct_count / self.total_questions * 100) if self.total_questions else 0

    @property
    def score_text(self):
        return f'{self.correct_count}/{self.total_questions} {self.percent}점'


class ExamAnswer(models.Model):
    """세션 × 문항 한 칸의 응답 + 자동 채점 결과."""
    session = models.ForeignKey(ExamSession, on_delete=models.CASCADE, related_name='answers')
    number = models.IntegerField(verbose_name='번호')
    qtype = models.CharField(max_length=100, blank=True, default='', verbose_name='유형')
    student_choice = models.CharField(max_length=50, blank=True, default='', verbose_name='학생 답')
    correct_answer = models.CharField(max_length=255, blank=True, default='', verbose_name='정답(스냅샷)')
    is_correct = models.BooleanField(default=False, verbose_name='정답 여부')
    # 학생이 '오류 문제'로 X 표시 → 채점 제외 + 다음 풀이에서 숨김
    flagged = models.BooleanField('오류표시', default=False)
    # 2차(틀린문제 재시험) 응답
    second_choice = models.CharField('2차 학생 답', max_length=50, blank=True, default='')
    is_correct2 = models.BooleanField('2차 정답 여부', default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'exam_answer'
        verbose_name = '시험 응답'
        verbose_name_plural = '시험 응답'
        ordering = ['session', 'number']
        unique_together = [['session', 'number']]
        indexes = [models.Index(fields=['session', 'number'])]

    def __str__(self):
        return f'{self.session_id} #{self.number} {self.student_choice}->{"O" if self.is_correct else "X"}'
