from django.contrib import admin

from .models import ExamPaper, ExamQuestion, ExamAssignment, ExamSession, ExamAnswer


class ExamQuestionInline(admin.TabularInline):
    model = ExamQuestion
    extra = 0
    fields = ('number', 'answer', 'qtype')


@admin.register(ExamPaper)
class ExamPaperAdmin(admin.ModelAdmin):
    list_display = ('resolved_title', 'source', 'school_grade', 'season', 'category',
                    'exam_date', 'grade', 'year', 'month', 'created_at')
    list_editable = ('exam_date',)
    list_filter = ('source', 'school_grade', 'season', 'grade', 'year')
    search_fields = ('title', 'school_grade', 'season', 'category')
    inlines = [ExamQuestionInline]


@admin.register(ExamAssignment)
class ExamAssignmentAdmin(admin.ModelAdmin):
    list_display = ('student', 'paper', 'assigned_by', 'assigned_at')
    search_fields = ('student__username', 'student__login_id')


class ExamAnswerInline(admin.TabularInline):
    model = ExamAnswer
    extra = 0
    fields = ('number', 'qtype', 'student_choice', 'correct_answer', 'is_correct')
    readonly_fields = fields


@admin.register(ExamSession)
class ExamSessionAdmin(admin.ModelAdmin):
    list_display = ('student', 'title', 'status', 'correct_count', 'total_questions', 'submitted_at')
    list_filter = ('status',)
    search_fields = ('student__username', 'student__login_id')
    inlines = [ExamAnswerInline]
