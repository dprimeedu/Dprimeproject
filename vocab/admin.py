from django.contrib import admin

from .models import (
    VocabUnit, VocabWord, VocabAssignment,
    StudentWordStar, VocabSession, VocabAttempt,
)


class VocabWordInline(admin.TabularInline):
    model = VocabWord
    extra = 0
    fields = ('index', 'word', 'meaning', 'sub_unit', 'source')
    ordering = ('index',)


@admin.register(VocabUnit)
class VocabUnitAdmin(admin.ModelAdmin):
    list_display = ('title', 'school', 'exam', 'grade', 'word_count', 'is_active', 'created_at')
    list_filter = ('grade', 'is_active')
    search_fields = ('title', 'school', 'exam')
    inlines = [VocabWordInline]


@admin.register(VocabWord)
class VocabWordAdmin(admin.ModelAdmin):
    list_display = ('word', 'meaning', 'sub_unit', 'source', 'unit', 'index')
    list_filter = ('unit', 'sub_unit')
    search_fields = ('word', 'meaning')


@admin.register(VocabAssignment)
class VocabAssignmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'unit', 'assigned_by', 'assigned_at', 'due_date')
    search_fields = ('student__username', 'student__login_id', 'unit__title')


@admin.register(StudentWordStar)
class StudentWordStarAdmin(admin.ModelAdmin):
    list_display = ('student', 'word', 'created_at')
    search_fields = ('student__username', 'student__login_id', 'word__word')


@admin.register(VocabSession)
class VocabSessionAdmin(admin.ModelAdmin):
    list_display = ('student', 'unit', 'star_only', 'correct_count', 'total_count', 'started_at', 'finished_at')


@admin.register(VocabAttempt)
class VocabAttemptAdmin(admin.ModelAdmin):
    list_display = ('session', 'word', 'is_correct', 'score_earned', 'created_at')
