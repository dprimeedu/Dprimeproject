from django.contrib import admin
from .models import (
    WritingUnit, WritingProblem, UnitAssignment,
    WritingSession, WritingAttempt,
    StudentProfile, Achievement, StudentAchievement,
)


class WritingProblemInline(admin.TabularInline):
    model = WritingProblem
    extra = 0
    fields = ('index', 'korean', 'english', 'word_hints')


@admin.register(WritingUnit)
class WritingUnitAdmin(admin.ModelAdmin):
    list_display = ('title', 'grade', 'publisher', 'problem_count', 'is_active', 'created_by', 'created_at')
    list_filter = ('grade', 'is_active', 'publisher')
    search_fields = ('title', 'description')
    inlines = [WritingProblemInline]


@admin.register(WritingProblem)
class WritingProblemAdmin(admin.ModelAdmin):
    list_display = ('unit', 'index', 'korean_short', 'english_short')
    list_filter = ('unit',)
    search_fields = ('korean', 'english')

    def korean_short(self, obj):
        return obj.korean[:40] + '...' if len(obj.korean) > 40 else obj.korean
    korean_short.short_description = '한글'

    def english_short(self, obj):
        return obj.english[:50] + '...' if len(obj.english) > 50 else obj.english
    english_short.short_description = '영어'


@admin.register(UnitAssignment)
class UnitAssignmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'unit', 'assigned_by', 'assigned_at', 'due_date')
    list_filter = ('unit', 'assigned_at')
    search_fields = ('student__username',)


@admin.register(WritingSession)
class WritingSessionAdmin(admin.ModelAdmin):
    list_display = ('student', 'unit', 'started_at', 'finished_at', 'total_score', 'max_word_combo')
    list_filter = ('unit', 'started_at')
    search_fields = ('student__username',)
    readonly_fields = ('started_at',)


@admin.register(WritingAttempt)
class WritingAttemptAdmin(admin.ModelAdmin):
    list_display = ('session', 'problem', 'word_index', 'input_value', 'correct_answer', 'is_correct', 'attempt_num', 'score_earned')
    list_filter = ('is_correct', 'hint_level', 'attempt_num')
    search_fields = ('input_value', 'correct_answer')


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ('student', 'total_xp', 'level', 'title', 'max_word_combo_ever', 'login_streak_days')
    search_fields = ('student__username',)
    readonly_fields = ('updated_at',)


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ('icon', 'name', 'code', 'condition_type', 'condition_value', 'order')
    list_editable = ('order',)


@admin.register(StudentAchievement)
class StudentAchievementAdmin(admin.ModelAdmin):
    list_display = ('student', 'achievement', 'earned_at')
    list_filter = ('achievement', 'earned_at')
    search_fields = ('student__username',)
