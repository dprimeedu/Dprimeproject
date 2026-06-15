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

    CATEGORY_NAESIN = 'naesin'
    CATEGORY_WORDBOOK = 'wordbook'
    CATEGORY_CHOICES = [(CATEGORY_NAESIN, '내신 단어'), (CATEGORY_WORDBOOK, '교재 단어장')]

    title = models.CharField(max_length=200, verbose_name='단원명')
    category = models.CharField(
        max_length=12, choices=CATEGORY_CHOICES, default=CATEGORY_NAESIN,
        db_index=True, verbose_name='분류',
    )
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


class VocabRangeTest(models.Model):
    """개인별 시험 범위 (학생관리자료 '내신단어TEST' 기반).

    학생관리표: A=이름, C=학교학년(→단원), O=단어장('내신단어TEST'), Q=오늘시작, R=오늘끝.
    학생은 이 범위에서 영→한 40문제 시험을 보고, 같은 범위만 따로 떼어 플래시카드로 훈련한다.
    """
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='vocab_range_tests', verbose_name='학생',
    )
    unit = models.ForeignKey(
        VocabUnit, on_delete=models.CASCADE,
        related_name='range_tests', verbose_name='단원(내신 단어장)',
    )
    start_index = models.IntegerField(verbose_name='시작 번호')
    end_index = models.IntegerField(verbose_name='끝 번호')
    source_label = models.CharField(max_length=100, default='내신단어TEST', verbose_name='단어장 라벨')
    # 학생관리표 행 번호 — '오늘 단어 TEST' 정렬을 시트 순서와 맞추기 위함(0=미지정→뒤로).
    sort_order = models.IntegerField(default=0, verbose_name='관리표 행순서')

    question_count = models.IntegerField(default=40, verbose_name='문제 수')
    time_limit_seconds = models.IntegerField(default=1200, verbose_name='제한시간(초)')
    pass_threshold = models.IntegerField(default=90, verbose_name='합격 기준 점수')

    is_active = models.BooleanField(default=True, verbose_name='활성화')
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vocab_range_tests_made', verbose_name='배정자',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vocab_range_test'
        verbose_name = '시험 범위'
        verbose_name_plural = '시험 범위'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['student', 'is_active'])]

    def __str__(self):
        return f'{self.student.username} | {self.unit.title} {self.start_index}~{self.end_index}'


class VocabSession(models.Model):
    """학생이 한 단원을 훈련하는 한 번의 세션 (퀴즈/테스트)."""
    MODE_PRACTICE = 'practice'
    MODE_TEST = 'test'
    MODE_CHOICES = [(MODE_PRACTICE, '연습'), (MODE_TEST, '정식 시험')]

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='vocab_sessions',
    )
    unit = models.ForeignKey(VocabUnit, on_delete=models.CASCADE, related_name='sessions')
    star_only = models.BooleanField(default=False, verbose_name='별표만 훈련')
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default=MODE_PRACTICE, verbose_name='모드')
    range_test = models.ForeignKey(
        VocabRangeTest, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sessions', verbose_name='시험 범위',
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    total_score = models.IntegerField(default=0, verbose_name='획득 점수')
    correct_count = models.IntegerField(default=0, verbose_name='맞은 개수')
    total_count = models.IntegerField(default=0, verbose_name='출제 개수')

    # 사람(교사) 검수
    is_reviewed = models.BooleanField(default=False, verbose_name='검수 완료')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vocab_sessions_reviewed', verbose_name='검수자',
    )

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

    @property
    def percent(self):
        return round(self.correct_count / self.total_count * 100) if self.total_count else 0

    @property
    def passed(self):
        """검수 후 합격 여부. range_test 있으면 그 기준, 없으면 기본 90."""
        threshold = self.range_test.pass_threshold if self.range_test else 90
        return self.percent >= threshold


class WordCardStar(models.Model):
    """학생 × 낱말카드 별표. 개별 단어장(WordCard) 플래시카드에서 별표한 카드."""
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wordcard_stars',
        verbose_name='학생',
    )
    card = models.ForeignKey(
        'WordCard', on_delete=models.CASCADE,
        related_name='stars', verbose_name='낱말카드',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vocab_wordcard_star'
        verbose_name = '낱말카드 별표'
        verbose_name_plural = '낱말카드 별표'
        unique_together = [['student', 'card']]
        indexes = [models.Index(fields=['student', 'card'])]

    def __str__(self):
        return f'⭐ {self.student.username} — {self.card.word}'


class WordCardSet(models.Model):
    """학생이 직접 만든 낱말카드 세트 (퀴즈렛식 '낱말카드 만들기').

    영어 단어를 입력하면 영→한 사전(교재 단어DB → 없으면 AI)으로 뜻을 채우고,
    완성하면 플래시카드로 바로 학습한다. 다 못 만들고 나가면 임시저장(draft).
    번호(start~end)는 학생별로 이어서 연속 매김 (기존 퀴즈렛 100단어 세트와 동일).
    """
    STATUS_DRAFT = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUS_CHOICES = [(STATUS_DRAFT, '임시저장'), (STATUS_PUBLISHED, '완성')]

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='word_card_sets', verbose_name='학생',
    )
    title = models.CharField(max_length=200, verbose_name='제목')
    description = models.TextField(blank=True, default='', verbose_name='설명')
    start_index = models.IntegerField(default=1, verbose_name='시작 번호')
    end_index = models.IntegerField(default=20, verbose_name='끝 번호')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT, verbose_name='상태')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vocab_word_card_set'
        verbose_name = '낱말카드 세트'
        verbose_name_plural = '낱말카드 세트'
        ordering = ['-updated_at']
        indexes = [models.Index(fields=['student', 'status'])]

    def __str__(self):
        return f'{self.student.username} | {self.title} ({self.get_status_display()})'

    @property
    def filled_count(self):
        if '_filled_count' in self.__dict__:
            return self._filled_count
        return self.cards.exclude(word='').count()


class WordCard(models.Model):
    """낱말카드 세트 안의 한 장 (영어 단어 → 한글 뜻)."""
    card_set = models.ForeignKey(
        WordCardSet, on_delete=models.CASCADE,
        related_name='cards', verbose_name='세트',
    )
    index = models.IntegerField(verbose_name='순번')           # 세트 내 1-based
    word = models.CharField(max_length=200, blank=True, default='', verbose_name='단어')
    meaning = models.TextField(blank=True, default='', verbose_name='뜻')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vocab_word_card'
        verbose_name = '낱말카드'
        verbose_name_plural = '낱말카드'
        ordering = ['card_set', 'index']
        unique_together = [['card_set', 'index']]

    def __str__(self):
        return f'{self.index}. {self.word} — {self.meaning[:20]}'


class DictionaryEntry(models.Model):
    """전체 단어장 모음 사전 (영어 → 한글). 낱말카드 '사전 기능' 1순위 소스.

    출처: '단어장 전체 영영전체모음.xlsm' 시트 '출제지' B열(영어)/C열(한글).
    management command `import_dictionary`로 적재. key=영어 소문자(매칭용).
    """
    word = models.CharField(max_length=255, verbose_name='영어')
    key = models.CharField(max_length=255, unique=True, db_index=True, verbose_name='매칭키(소문자)')
    meaning = models.TextField(verbose_name='한글 뜻')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vocab_dictionary_entry'
        verbose_name = '사전 단어'
        verbose_name_plural = '사전 단어'

    def __str__(self):
        return f'{self.word} → {self.meaning[:20]}'


class DictionaryCache(models.Model):
    """영→한 사전 조회 캐시 — 같은 단어 반복 조회/AI 재호출 방지."""
    SRC_DB = 'db'
    SRC_AI = 'ai'
    SRC_CHOICES = [(SRC_DB, '교재 단어DB'), (SRC_AI, 'AI')]

    word = models.CharField(max_length=200, unique=True, verbose_name='단어(소문자)')
    meaning = models.TextField(verbose_name='뜻')
    source = models.CharField(max_length=10, choices=SRC_CHOICES, default=SRC_DB, verbose_name='출처')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'vocab_dictionary_cache'
        verbose_name = '사전 캐시'
        verbose_name_plural = '사전 캐시'

    def __str__(self):
        return f'{self.word} → {self.meaning[:20]} ({self.source})'


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
