from django.contrib import admin

from .models import (
    GrammarUnit, GrammarProblem, GrammarAssignment,
    GrammarSession, GrammarAnswer, GrammarRangeTest,
)


@admin.register(GrammarUnit)
class GrammarUnitAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'school', 'grade', 'is_active', 'created_at')
    list_filter = ('is_active', 'grade')
    search_fields = ('title', 'school', 'exam')


@admin.register(GrammarProblem)
class GrammarProblemAdmin(admin.ModelAdmin):
    list_display = ('id', 'unit', 'index', 'sentence', 'answer', 'sub_unit')
    search_fields = ('sentence', 'answer')


admin.site.register(GrammarAssignment)
admin.site.register(GrammarSession)
admin.site.register(GrammarAnswer)
admin.site.register(GrammarRangeTest)
