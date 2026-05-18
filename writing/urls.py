from django.urls import path
from . import views

app_name = 'writing'

urlpatterns = [
    # 학생
    path('', views.student_home, name='home'),
    path('unit/<int:unit_id>/start/', views.start_session, name='start_session'),
    path('session/<int:session_id>/', views.session_view, name='session'),
    path('result/<int:session_id>/', views.result_view, name='result'),

    # AJAX API
    path('api/check-word/', views.check_word_api, name='api_check_word'),
    path('api/complete-problem/', views.complete_problem_api, name='api_complete_problem'),
    path('api/reset-problem/', views.reset_problem_api, name='api_reset_problem'),
    path('api/complete-session/', views.complete_session_api, name='api_complete_session'),

    # 선생님 / admin
    path('admin/upload/', views.upload_view, name='upload'),
    path('admin/units/', views.unit_list, name='unit_list'),
    path('admin/units/<int:unit_id>/', views.unit_detail, name='unit_detail'),
    path('admin/units/<int:unit_id>/delete/', views.unit_delete, name='unit_delete'),
    path('admin/units/<int:unit_id>/generate-hints/', views.generate_hints_ajax, name='generate_hints'),
    path('admin/units/<int:unit_id>/generate-hints/status/', views.generate_hints_status, name='generate_hints_status'),
    path('admin/units/<int:unit_id>/assignments/', views.assignment_list, name='assignment_list'),
    path('admin/units/<int:unit_id>/assignments/update/', views.assignment_update, name='assignment_update'),
]
