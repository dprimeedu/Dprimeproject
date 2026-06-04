from django.contrib import admin

from .models import (
    SummaryUnit, SummaryProblem, SummaryAssignment,
    SummarySession, SummaryBlankAnswer,
)


class SummaryProblemInline(admin.TabularInline):
    model = SummaryProblem
    extra = 0
    fields = ('index', 'sentence1_answer', 'korean1', 'sentence2_answer', 'korean2')


@admin.register(SummaryUnit)
class SummaryUnitAdmin(admin.ModelAdmin):
    list_display = ('id', 'school', 'unit', 'title', 'grade', 'problem_count', 'is_active', 'created_at')
    list_filter = ('grade', 'is_active')
    search_fields = ('school', 'unit', 'title')
    inlines = [SummaryProblemInline]


@admin.register(SummaryProblem)
class SummaryProblemAdmin(admin.ModelAdmin):
    list_display = ('id', 'unit', 'index', 'sentence1_answer', 'sentence2_answer')
    list_filter = ('unit',)
    search_fields = ('sentence1_answer', 'sentence2_answer')


@admin.register(SummaryAssignment)
class SummaryAssignmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'student', 'unit', 'assigned_by', 'assigned_at')
    search_fields = ('student__username',)


@admin.register(SummarySession)
class SummarySessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'student', 'unit', 'status', 'correct_count', 'total_blanks', 'submitted_at', 'graded_at')
    list_filter = ('status',)
    search_fields = ('student__username',)


@admin.register(SummaryBlankAnswer)
class SummaryBlankAnswerAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'problem', 'blank', 'first_input', 'first_auto_correct', 'second_input', 'admin_verdict')
    list_filter = ('blank', 'first_auto_correct', 'admin_verdict')
