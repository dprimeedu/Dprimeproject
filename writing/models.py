from django.db import models
from django.conf import settings


class WritingUnit(models.Model):
    """영작 훈련 단원 (선생님이 엑셀로 업로드한 단원)"""
    GRADE_CHOICES = [
        ('초1', '초1'), ('초2', '초2'), ('초3', '초3'),
        ('초4', '초4'), ('초5', '초5'), ('초6', '초6'),
        ('중1', '중1'), ('중2', '중2'), ('중3', '중3'),
        ('고1', '고1'), ('고2', '고2'), ('고3', '고3'),
        ('기타', '기타'),
    ]

    title = models.CharField(max_length=200, verbose_name='단원명')
    publisher = models.CharField(max_length=50, blank=True, verbose_name='출판사')
    grade = models.CharField(max_length=10, choices=GRADE_CHOICES, default='기타', verbose_name='학년')
    description = models.TextField(blank=True, verbose_name='설명')
    target_seconds = models.IntegerField(
        null=True, blank=True,
        verbose_name='목표 완료 시간(초)',
        help_text='빈 값이면 자동 계산 (문제 수 × 30초)',
    )
    is_active = models.BooleanField(default=True, verbose_name='활성화')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='created_writing_units',
        verbose_name='등록자',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'writing_unit'
        verbose_name = '영작 단원'
        verbose_name_plural = '영작 단원'
        ordering = ['-created_at']

    def __str__(self):
        return self.title

    @property
    def problem_count(self):
        # bulk prefetch가 self._problem_count 를 채워두면 그 값을 사용 (N+1 방지)
        if '_problem_count' in self.__dict__:
            return self._problem_count
        return self.problems.count()

    @property
    def total_words(self):
        """단원 전체 영어 단어 수 (한 단원에서 학생이 입력해야 할 단어 합계)."""
        return sum(len(p.english.strip().split()) for p in self.problems.all())

    @property
    def computed_target_seconds(self):
        """도전 baseline 시간 — 수동 지정값 우선, 없으면 단어당 7초."""
        if self.target_seconds:
            return self.target_seconds
        words = self.total_words
        # 최소 60초 보장 (단원이 매우 작아도 너무 짧지 않게)
        return max(60, words * 7)


class WritingProblem(models.Model):
    """단원 내 한 문제 (한글 → 영어)"""
    unit = models.ForeignKey(
        WritingUnit, on_delete=models.CASCADE,
        related_name='problems', verbose_name='단원',
    )
    index = models.IntegerField(verbose_name='문제 번호')
    korean = models.TextField(verbose_name='한글 및 힌트')
    english = models.TextField(verbose_name='영어 정답')
    word_hints = models.JSONField(
        default=list, blank=True,
        verbose_name='단어별 한글뜻',
        help_text='AI 자동 생성. 형식: [{"word": "under", "meaning": "~아래에"}, ...]'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'writing_problem'
        verbose_name = '영작 문제'
        verbose_name_plural = '영작 문제'
        ordering = ['unit', 'index']
        unique_together = [['unit', 'index']]

    def __str__(self):
        return f'{self.unit.title} #{self.index}'

    @property
    def english_words(self):
        """영어 정답을 공백 기준으로 단어 리스트로 반환"""
        return self.english.strip().split()


class UnitAssignment(models.Model):
    """선생님이 학생에게 단원 배정"""
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='writing_assignments',
        verbose_name='학생',
    )
    unit = models.ForeignKey(
        WritingUnit, on_delete=models.CASCADE,
        related_name='assignments', verbose_name='단원',
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='assignments_made',
        verbose_name='배정자',
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    due_date = models.DateTimeField(null=True, blank=True, verbose_name='마감일')

    class Meta:
        db_table = 'writing_assignment'
        verbose_name = '단원 배정'
        verbose_name_plural = '단원 배정'
        unique_together = [['student', 'unit']]
        ordering = ['-assigned_at']

    def __str__(self):
        return f'{self.student.username} ← {self.unit.title}'


class WritingSession(models.Model):
    """학생이 한 단원을 푸는 한 번의 세션"""
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='writing_sessions',
    )
    unit = models.ForeignKey(WritingUnit, on_delete=models.CASCADE, related_name='sessions')
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    total_score = models.IntegerField(default=0, verbose_name='획득 점수')
    perfect_sentences = models.IntegerField(default=0)
    max_word_combo = models.IntegerField(default=0)
    max_sentence_combo = models.IntegerField(default=0)
    time_bonus_earned = models.IntegerField(default=0, verbose_name='시간 보너스')
    view_mode = models.BooleanField(
        default=False, verbose_name='보고 학습 모드',
        help_text='켜면 점수 ×0.5, 이 세션은 단계 재계산에서 제외',
    )

    # ── 실시간 타이핑 상태 (라이브 모니터용. 단어 제출 시 자동 클리어) ──
    live_problem = models.ForeignKey(
        'WritingProblem', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+',
        verbose_name='지금 풀고 있는 문제',
    )
    live_word_index = models.IntegerField(default=0)
    live_input = models.CharField(max_length=200, blank=True, default='')
    live_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'writing_session'
        verbose_name = '풀이 세션'
        verbose_name_plural = '풀이 세션'
        ordering = ['-started_at']

    def __str__(self):
        return f'{self.student.username} - {self.unit.title} ({self.started_at:%Y-%m-%d %H:%M})'

    @property
    def is_completed(self):
        return self.finished_at is not None


class WritingAttempt(models.Model):
    """단어 단위 시도 기록 (1단어 입력 = 1 row)"""
    HINT_LEVELS = [
        (0, '힌트 없음'),
        (1, '한글뜻'),
        (2, '첫글자'),
        (3, '정답 공개'),
    ]

    session = models.ForeignKey(
        WritingSession, on_delete=models.CASCADE, related_name='attempts',
    )
    problem = models.ForeignKey(WritingProblem, on_delete=models.CASCADE)
    word_index = models.IntegerField(verbose_name='단어 순번 (0부터)')

    input_value = models.CharField(max_length=200, verbose_name='학생 입력')
    correct_answer = models.CharField(max_length=200, verbose_name='정답')
    hint_level = models.IntegerField(choices=HINT_LEVELS, default=0)
    is_correct = models.BooleanField()
    attempt_num = models.IntegerField(verbose_name='시도 회차 (1~3)')
    time_taken_seconds = models.IntegerField(default=0)
    score_earned = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'writing_attempt'
        verbose_name = '단어 시도'
        verbose_name_plural = '단어 시도'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['session', 'problem', 'word_index']),
        ]

    def __str__(self):
        result = 'O' if self.is_correct else 'X'
        return f'{self.session.student.username} | {self.input_value} → {result}'


class StudentProfile(models.Model):
    """학생별 게임화 데이터 (XP, 레벨, 콤보 등)"""
    student = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='writing_profile',
    )
    total_xp = models.IntegerField(default=0, verbose_name='누적 XP')
    current_word_combo = models.IntegerField(default=0)
    max_word_combo_ever = models.IntegerField(default=0)
    current_sentence_combo = models.IntegerField(default=0)
    max_sentence_combo_ever = models.IntegerField(default=0)

    last_login_date = models.DateField(null=True, blank=True)
    login_streak_days = models.IntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'writing_student_profile'
        verbose_name = '학생 프로필 (게임화)'
        verbose_name_plural = '학생 프로필 (게임화)'

    def __str__(self):
        return f'{self.student.username} (Lv {self.level} / {self.total_xp} XP)'

    @property
    def level(self):
        from .services.scoring import compute_level
        return compute_level(self.total_xp)

    @property
    def title(self):
        lv = self.level
        if lv <= 2:
            return '새내기'
        elif lv <= 5:
            return '견습생'
        elif lv <= 10:
            return '영작러'
        elif lv <= 20:
            return '영작러+'
        elif lv <= 50:
            return '영작마스터'
        else:
            return '영작신'

    @property
    def xp_in_current_level(self):
        from .services.scoring import level_start_xp
        return self.total_xp - level_start_xp(self.level)

    @property
    def xp_to_next_level(self):
        from .services.scoring import xp_needed_for_level
        return xp_needed_for_level(self.level) - self.xp_in_current_level


class Achievement(models.Model):
    """배지 정의 (시스템 마스터 데이터)"""
    code = models.CharField(max_length=50, unique=True, verbose_name='코드')
    name = models.CharField(max_length=100, verbose_name='배지명')
    description = models.CharField(max_length=200)
    icon = models.CharField(max_length=10, default='🏅', help_text='이모지 1개')
    condition_type = models.CharField(
        max_length=30,
        help_text='word_combo / sentence_combo / perfect_count / login_streak / speed 등',
    )
    condition_value = models.IntegerField(help_text='해당 조건의 임계값')
    order = models.IntegerField(default=0, help_text='리스트에서 표시 순서')

    class Meta:
        db_table = 'writing_achievement'
        verbose_name = '배지 정의'
        verbose_name_plural = '배지 정의'
        ordering = ['order', 'condition_value']

    def __str__(self):
        return f'{self.icon} {self.name}'


class StudentAchievement(models.Model):
    """학생-배지 매핑 (획득 기록)"""
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='writing_achievements',
    )
    achievement = models.ForeignKey(Achievement, on_delete=models.CASCADE)
    earned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'writing_student_achievement'
        verbose_name = '획득한 배지'
        verbose_name_plural = '획득한 배지'
        unique_together = [['student', 'achievement']]
        ordering = ['-earned_at']

    def __str__(self):
        return f'{self.student.username} ← {self.achievement.name}'


class StudentUnitLevel(models.Model):
    """학생-단원별 숙련 레벨 (1/2/3).

    Lv1: 한글 → 첫글자 → 정답 (기본)
    Lv2: 한글 → 정답 (첫글자 단계 제거, XP ×1.2)
    Lv3: 정답만 (힌트 전부 제거, XP ×1.5)

    승급/강등 기준은 그 단원의 최근 N개 단어 결과 비율 (services/level.py).
    """
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='unit_levels',
    )
    unit = models.ForeignKey(
        WritingUnit,
        on_delete=models.CASCADE,
        related_name='student_levels',
    )
    level = models.IntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'writing_student_unit_level'
        verbose_name = '학생 단원 레벨'
        verbose_name_plural = '학생 단원 레벨'
        unique_together = [['student', 'unit']]

    def __str__(self):
        return f'{self.student.username} - {self.unit.title} Lv{self.level}'


class DailyStudyGoal(models.Model):
    """선생님이 학생에게 그날 지정한 학습 목표.

    측정치 3종(문제 수/학습 분/완료 단원). 0이면 그 항목 목표 없음으로 간주.
    학생×날짜 유일.
    """
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='daily_goals',
        verbose_name='학생',
    )
    date = models.DateField(verbose_name='날짜')
    target_problems = models.IntegerField(default=0, verbose_name='목표 문제 수')
    target_minutes = models.IntegerField(default=0, verbose_name='목표 학습 분')
    target_sessions = models.IntegerField(default=0, verbose_name='목표 완료 단원 수')
    note = models.CharField(max_length=200, blank=True, default='', verbose_name='메모')
    set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='+',
        verbose_name='지정 선생님',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'writing_daily_goal'
        verbose_name = '일일 학습 목표'
        verbose_name_plural = '일일 학습 목표'
        unique_together = [['student', 'date']]
        ordering = ['-date']

    def __str__(self):
        return f'{self.student.username} {self.date} 목표'

    @property
    def has_any_target(self) -> bool:
        return bool(self.target_problems or self.target_minutes or self.target_sessions)


class FlashcardActivity(models.Model):
    """학생의 현재 플래쉬카드(학습하기) 활동 상태 — 실시간 모니터용 heartbeat.

    학생 1명 = 1행 (OneToOne). 학습하기 페이지가 주기적으로 update.
    updated_at 이 일정 시간 이상 오래되면 '활동 종료'로 간주.
    """
    student = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='flashcard_activity',
    )
    unit = models.ForeignKey(WritingUnit, on_delete=models.CASCADE, related_name='+')
    current_index = models.IntegerField(default=0, verbose_name='현재 카드 0-based')
    total = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'writing_flashcard_activity'
        verbose_name = '플래쉬카드 활동'
        verbose_name_plural = '플래쉬카드 활동'


class MatchRoom(models.Model):
    """학생끼리 같은 단원을 동시에 푸는 게임 모드 방."""
    STATUS_CHOICES = [
        ('waiting', '대기 중'),
        ('active', '진행 중'),
        ('finished', '종료'),
    ]
    code = models.CharField(max_length=8, unique=True, verbose_name='입장 코드')
    unit = models.ForeignKey(WritingUnit, on_delete=models.CASCADE, related_name='match_rooms')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='+', verbose_name='생성자',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='waiting')
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'writing_match_room'
        verbose_name = '대전 방'
        verbose_name_plural = '대전 방'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.code} · {self.unit.title}'


class MatchParticipant(models.Model):
    """대전 방 참가자 — 학생 1명 = 행 1개. session은 시작 시 생성.

    is_ai=True이면 student=None, ai_difficulty/ai_name 채움.
    AI 참가자는 session/attempt 없이 match_state_api에서 즉석 계산.
    """
    AI_DIFFICULTIES = [
        ('easy', '쉬움'),
        ('medium', '중간'),
        ('hard', '어려움'),
    ]
    room = models.ForeignKey(MatchRoom, on_delete=models.CASCADE, related_name='participants')
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        null=True, blank=True, related_name='+',
    )
    session = models.ForeignKey(
        WritingSession, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    is_ai = models.BooleanField(default=False, verbose_name='AI 참가자 여부')
    ai_difficulty = models.CharField(
        max_length=10, choices=AI_DIFFICULTIES, blank=True, default='',
    )
    ai_name = models.CharField(max_length=50, blank=True, default='')
    joined_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    final_score = models.IntegerField(default=0)
    final_rank = models.IntegerField(null=True, blank=True)

    class Meta:
        db_table = 'writing_match_participant'
        verbose_name = '대전 참가자'
        verbose_name_plural = '대전 참가자'
        unique_together = [['room', 'student']]
        ordering = ['joined_at']


class BugReport(models.Model):
    """학생이 풀이 중 누른 '버그 신고' — 관리자가 검토·수정용."""
    STATUS_CHOICES = [
        ('pending', '대기'),
        ('reviewing', '검토중'),
        ('fixed', '수정 완료'),
        ('dismissed', '해당 없음'),
    ]
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='writing_bug_reports', verbose_name='신고 학생',
    )
    session = models.ForeignKey(
        WritingSession,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='bug_reports', verbose_name='세션',
    )
    problem = models.ForeignKey(
        WritingProblem,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='bug_reports', verbose_name='문제',
    )
    unit = models.ForeignKey(
        WritingUnit,
        on_delete=models.SET_NULL, null=True, blank=True,
        related_name='bug_reports', verbose_name='단원',
    )
    url = models.CharField(max_length=500, blank=True, default='', verbose_name='URL')
    description = models.TextField(blank=True, default='', verbose_name='신고 내용')
    screen_state = models.JSONField(
        default=dict, blank=True, verbose_name='화면 상태',
        help_text='입력 상태/시도 횟수/현재 단어 인덱스 등 스냅샷',
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending',
        verbose_name='상태',
    )
    admin_note = models.TextField(blank=True, default='', verbose_name='관리자 메모')
    xp_awarded = models.IntegerField(
        default=0, verbose_name='지급 XP',
        help_text='신고 즉시 학생에게 지급된 XP (PERFECT 풀이 XP × 2)',
    )
    xp_rolled_back = models.BooleanField(
        default=False, verbose_name='XP 회수됨',
        help_text='관리자 검토 후 문제 없는 신고로 판단해 학생 XP에서 회수',
    )
    xp_rolled_back_at = models.DateTimeField(null=True, blank=True, verbose_name='XP 회수 시각')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'writing_bug_report'
        verbose_name = '버그 신고'
        verbose_name_plural = '버그 신고'
        ordering = ['-created_at']

    def __str__(self):
        who = self.student.username if self.student else '알수없음'
        return f'[{self.get_status_display()}] {who} — {self.unit.title if self.unit else "?"}'
