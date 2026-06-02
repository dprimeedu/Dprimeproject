from django.db import models
from django.conf import settings


class VocabUnit(models.Model):
    """단어 훈련 단원 — 학교/시험 단위 (예: 동백고1 1학기 기말고사).

    하나의 '통합본' xlsx '내신단어' 시트 = 하나의 VocabUnit.
    그 안의 개별 단어들은 VocabWord, 단어별 소단원/출처는 VocabWord.sub_unit/source.
    """
    GRADE_CHOICES = [
        ('초1', '초1'), ('초2', '초2'), ('초3', '초3'),
        ('초4', '초4'), ('초5', '초5'), ('초6', '초6'),
        ('중1', '중1'), ('중2', '중2'), ('중3', '중3'),
        ('고1', '고1'), ('고2', '고2'), ('고3', '고3'),
        ('기타', '기타'),
    ]

    title = models.CharField(max_length=200, verbose_name='단원명')
    school = models.CharField(max_length=100, blank=True, default='', verbose_name='학교')
    exam = models.CharField(max_length=100, blank=True, default='', verbose_name='시험')
    grade = models.CharField(max_length=10, choices=GRADE_CHOICES, default='기타', verbose_name='학년')
    description = models.TextField(blank=True, verbose_name='설명')
    is_active = models.BooleanField(default=True, verbose_name='활성화')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_vocab_units',
        verbose_name='등록자',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vocab_unit'
        verbose_name = '단어 단원'
        verbose_name_plural = '단어 단원'
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    @property
    def word_count(self):
        # bulk prefetch가 self._word_count 를 채워두면 그 값을 사용 (N+1 방지)
        if '_word_count' in self.__dict__:
            return self._word_count
        return self.words.count()


class VocabWord(models.Model):
    """단원 내 한 단어 (영어 단어 → 한글 뜻)."""
    unit = models.ForeignKey(
        VocabUnit, on_delete=models.CASCADE,
        related_name='words', verbose_name='단원',
    )
    index = models.IntegerField(verbose_name='색인')
    word = models.CharField(max_length=200, verbose_name='단어')
    meaning = models.TextField(verbose_name='해석')
    sub_unit = models.CharField(max_length=100, blank=True, default='', verbose_name='단원(소단원)')
    source = models.CharField(max_length=100, blank=True, default='', verbose_name='출처')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vocab_word'
        verbose_name = '단어'
        verbose_name_plural = '단어'
        ordering = ['unit', 'index']
        unique_together = [['unit', 'index']]
        indexes = [
            models.Index(fields=['unit', 'sub_unit']),
        ]

    def __str__(self):
        return f'{self.word} — {self.meaning[:20]}'


class VocabAssignment(models.Model):
    """선생님이 학생에게 단어 단원 배정."""
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='vocab_assignments',
        verbose_name='학생',
    )
    unit = models.ForeignKey(
        VocabUnit, on_delete=models.CASCADE,
        related_name='assignments', verbose_name='단원',
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='vocab_assignments_made',
        verbose_name='배정자',
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    due_date = models.DateTimeField(null=True, blank=True, verbose_name='마감일')

    class Meta:
        db_table = 'vocab_assignment'
        verbose_name = '단어 단원 배정'
        verbose_name_plural = '단어 단원 배정'
        unique_together = [['student', 'unit']]
        ordering = ['-assigned_at']

    def __str__(self):
        return f'{self.student.username} ← {self.unit.title}'


class StudentWordStar(models.Model):
    """학생 × 단어 별표 (= '모르는 단어'). Quizlet '어려운 단어' 집중훈련용.

    학생 구글시트 '내신단어' 탭 D열 체크에서 이식하거나,
    홈페이지 플래시카드에서 직접 별표 토글로 생성.
    """
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='vocab_word_stars',
        verbose_name='학생',
    )
    word = models.ForeignKey(
        VocabWord, on_delete=models.CASCADE,
        related_name='stars', verbose_name='단어',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vocab_word_star'
        verbose_name = '별표 단어'
        verbose_name_plural = '별표 단어'
        unique_together = [['student', 'word']]
        indexes = [
            models.Index(fields=['student', 'word']),
        ]

    def __str__(self):
        return f'⭐ {self.student.username} — {self.word.word}'


class VocabSession(models.Model):
    """학생이 한 단원을 훈련하는 한 번의 세션 (퀴즈/테스트)."""
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='vocab_sessions',
    )
    unit = models.ForeignKey(VocabUnit, on_delete=models.CASCADE, related_name='sessions')
    star_only = models.BooleanField(default=False, verbose_name='별표만 훈련')
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    total_score = models.IntegerField(default=0, verbose_name='획득 점수')
    correct_count = models.IntegerField(default=0, verbose_name='맞은 개수')
    total_count = models.IntegerField(default=0, verbose_name='출제 개수')

    class Meta:
        db_table = 'vocab_session'
        verbose_name = '단어 세션'
        verbose_name_plural = '단어 세션'
        ordering = ['-started_at']

    def __str__(self):
        return f'{self.student.username} - {self.unit.title} ({self.started_at:%Y-%m-%d %H:%M})'

    @property
    def is_completed(self):
        return self.finished_at is not None


class VocabAttempt(models.Model):
    """단어 단위 시도 기록 (1단어 입력/응답 = 1 row)."""
    session = models.ForeignKey(
        VocabSession, on_delete=models.CASCADE, related_name='attempts',
    )
    word = models.ForeignKey(VocabWord, on_delete=models.CASCADE)
    input_value = models.CharField(max_length=200, blank=True, default='', verbose_name='학생 입력')
    is_correct = models.BooleanField()
    time_taken_seconds = models.IntegerField(default=0)
    score_earned = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vocab_attempt'
        verbose_name = '단어 시도'
        verbose_name_plural = '단어 시도'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['session', 'word']),
        ]

    def __str__(self):
        result = 'O' if self.is_correct else 'X'
        return f'{self.session.student.username} | {self.word.word} → {result}'
