from django.contrib import admin

from .models import ClassRoom, StudentInfo, DailyRecord


@admin.register(ClassRoom)
class ClassRoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'weekday_time', 'teacher')
    search_fields = ('name',)


@admin.register(StudentInfo)
class StudentInfoAdmin(admin.ModelAdmin):
    list_display = ('student', 'school', 'school_grade', 'class_room', 'chatroom_name')
    list_filter = ('school_grade', 'class_room')
    search_fields = ('student__username', 'student__login_id', 'school_grade')
    autocomplete_fields = ()


@admin.register(DailyRecord)
class DailyRecordAdmin(admin.ModelAdmin):
    list_display = ('student', 'date', 'attendance', 'hw1_rate', 'hw2_rate',
                    'vocab_result', 'report_generated_at')
    list_filter = ('date', 'attendance')
    search_fields = ('student__username', 'student__login_id')
    date_hierarchy = 'date'
