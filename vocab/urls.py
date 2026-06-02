from django.urls import path
from . import views

app_name = 'vocab'

urlpatterns = [
    # 학생
    path('', views.student_home, name='home'),
    path('unit/<int:unit_id>/flashcard/', views.flashcard_view, name='flashcard'),

    # AJAX API
    path('api/star/toggle/', views.star_toggle_api, name='star_toggle'),

    # 선생님 / 관리자 — 단원 관리
    path('admin/units/', views.unit_list, name='unit_list'),
    path('admin/units/delete/', views.unit_delete, name='unit_delete'),
    path('admin/units/<int:unit_id>/assignments/', views.assignment_list, name='assignment_list'),
    path('admin/units/<int:unit_id>/assignments/update/', views.assignment_update, name='assignment_update'),

    # 선생님 / 관리자 — 학생 관리 + 배정
    path('admin/students/', views.student_admin, name='student_admin'),
    path('admin/students/upload/', views.student_upload, name='student_upload'),
    path('admin/students/action/', views.student_action, name='student_action'),
    path('admin/students/template.xlsx', views.student_template_xlsx, name='student_template'),
    path('admin/api/students/<int:student_id>/assignments/', views.student_assignments, name='student_assignments'),
    path('admin/api/students/<int:student_id>/assignments/update/', views.student_assignments_update, name='student_assignments_update'),
]
