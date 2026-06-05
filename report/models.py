"""학습관리·일일리포트 모델.

기존 '0. 학생관리자료.xlsx[학생관리표]' 한 행(학생×날짜) = DailyRecord 한 건.
학습보고서.py가 쓰던 컬럼들을 필드로 미러링한다(점진적 정규화는 추후).
값은 대부분 자유 텍스트(예: "40/50 80점", "교재미지참", "첫수업")라 CharField/Text로 둔다.
"""
from django.conf import settings
from django.db import models


class ClassRoom(models.Model):
    """반(class) — 학원 내 학생 묶음. 선택적."""
    name = models.CharField('반 이름', max_length=100)
    weekday_time = models.CharField('요일시간', max_length=100, blank=True, default='')
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='classrooms', verbose_name='담당 교사',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'report_classroom'
        verbose_name = '반'
        verbose_name_plural = '반'
        ordering = ['name']

    def __str__(self):
        return self.name


class StudentInfo(models.Model):
    """학생 부가정보 — 학교/학년/반/카톡 단톡방명. member.Member 1:1."""
    student = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='report_info', verbose_name='학생',
    )
    school = models.CharField('학교', max_length=50, blank=True, default='')
    school_grade = models.CharField('학교학년', max_length=50, blank=True, default='')  # 예: 백현고2
    class_room = models.ForeignKey(
        ClassRoom, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='students', verbose_name='반',
    )
    # 카톡 대화방명 — 비우면 "{이름}({학교}) 프라임에듀 단톡방" 규칙으로 생성
    chatroom_name = models.CharField('카톡 단톡방명', max_length=200, blank=True, default='')

    class Meta:
        db_table = 'report_student_info'
        verbose_name = '학생 정보'
        verbose_name_plural = '학생 정보'

    def __str__(self):
        return f'{self.student.username} ({self.school_grade})'

    def resolved_chatroom_name(self):
        if self.chatroom_name.strip():
            return self.chatroom_name.strip()
        school = self.school or self._school_from_grade()
        return f'{self.student.username}({school}) 프라임에듀 단톡방'

    def _school_from_grade(self):
        g = self.school_grade
        return g[:-1] if len(g) > 1 and g[-1].isdigit() else g


class DailyRecord(models.Model):
    """학생 × 날짜 한 건의 일일 학습 기록 (학생관리표 한 행)."""
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='daily_records', verbose_name='학생',
    )
    date = models.DateField('날짜', db_index=True)
    weekday_time = models.CharField('요일시간', max_length=100, blank=True, default='')

    # 출결 — 원문(출석/지각/결석 등)
    attendance = models.CharField('출석', max_length=50, blank=True, default='')

    # 시험 결과 (텍스트: "40/50 80점" 등)
    grammar_summary_result = models.CharField('어법/요약문결과', max_length=200, blank=True, default='')
    vocab_result = models.CharField('단어시험결과', max_length=200, blank=True, default='')
    writing_result = models.CharField('영작시험결과', max_length=200, blank=True, default='')
    reading_result = models.CharField('TEST결과', max_length=200, blank=True, default='')

    # 과제 달성률 (텍스트: "80%", "교재미지참", "첫수업" 등)
    hw1_rate = models.CharField('과제1달성률', max_length=200, blank=True, default='')
    hw2_rate = models.CharField('과제2달성률', max_length=200, blank=True, default='')
    hw_rank = models.CharField('숙제달성률 순위', max_length=50, blank=True, default='')

    # 독해/문법 과제 결과
    reading_hw1_result = models.TextField('독해과제1결과', blank=True, default='')
    reading_hw2_result = models.TextField('독해과제2결과', blank=True, default='')
    grammar_no = models.CharField('문법번호', max_length=100, blank=True, default='')
    grammar_hw_result = models.TextField('문법과제결과', blank=True, default='')

    # 오늘 과제(교재명 라벨 추출용)
    today_reading1 = models.CharField('오늘독해과제1', max_length=200, blank=True, default='')
    today_reading2 = models.CharField('오늘독해과제2', max_length=200, blank=True, default='')

    # 다음 수업 상세 과제
    next_reading1 = models.TextField('다음독해과제1', blank=True, default='')
    next_reading2 = models.TextField('다음독해과제2', blank=True, default='')
    next_grammar = models.TextField('다음문법과제', blank=True, default='')

    # 단어 암기
    vocab_book = models.CharField('단어장', max_length=200, blank=True, default='')
    vocab_hw_start = models.CharField('단어 숙제 시작', max_length=100, blank=True, default='')
    vocab_hw_end = models.CharField('단어 숙제 끝', max_length=100, blank=True, default='')
    is_new_vocab = models.BooleanField('새 단어장', default=False)

    teacher_comment = models.CharField('선생님의 한마디', max_length=500, blank=True, default='')

    # 리포트 산출물
    report_image = models.ImageField('리포트 이미지', upload_to='reports/%Y/%m/', null=True, blank=True)
    report_generated_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='daily_records_created', verbose_name='작성자',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'report_daily_record'
        verbose_name = '일일 학습기록'
        verbose_name_plural = '일일 학습기록'
        unique_together = [['student', 'date']]
        ordering = ['-date', 'student']
        indexes = [models.Index(fields=['date', 'student'])]

    def __str__(self):
        return f'{self.student.username} {self.date}'
