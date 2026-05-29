from django.urls import path
from . import views

app_name = 'writing'

urlpatterns = [
    # 데모 (시연용 자동 로그인)
    path('demo/', views.demo_login, name='demo'),

    # 학생
    path('', views.student_home, name='home'),
    path('unit/<int:unit_id>/start/', views.start_session, name='start_session'),
    path('unit/<int:unit_id>/flashcard/', views.flashcard_view, name='flashcard'),
    path('session/<int:session_id>/', views.session_view, name='session'),
    path('result/<int:session_id>/', views.result_view, name='result'),

    # AJAX API
    path('api/check-word/', views.check_word_api, name='api_check_word'),
    path('api/complete-problem/', views.complete_problem_api, name='api_complete_problem'),
    path('api/reset-problem/', views.reset_problem_api, name='api_reset_problem'),
    path('api/complete-session/', views.complete_session_api, name='api_complete_session'),
    path('api/leaderboard/<int:unit_id>/', views.leaderboard_api, name='api_leaderboard'),

    # 선생님 / admin
    path('admin/upload/', views.upload_view, name='upload'),
    path('admin/units/', views.unit_list, name='unit_list'),
    path('admin/units/<int:unit_id>/', views.unit_detail, name='unit_detail'),
    path('admin/units/<int:unit_id>/replace-excel/', views.unit_replace_excel, name='unit_replace_excel'),
    path('admin/units/<int:unit_id>/problem-insert/', views.problem_insert, name='problem_insert'),
    path('admin/units/<int:unit_id>/problem-reorder/', views.problem_reorder, name='problem_reorder'),
    path('admin/problems/<int:problem_id>/update/', views.problem_update, name='problem_update'),
    path('admin/problems/<int:problem_id>/hints/', views.problem_hints_get, name='problem_hints_get'),
    path('admin/problems/delete/', views.problems_delete, name='problems_delete'),
    path('admin/units/delete/', views.unit_delete, name='unit_delete'),
    path('admin/units/generate-hints-bulk/', views.generate_hints_bulk_ajax, name='generate_hints_bulk'),
    path('admin/units/assignments-bulk/', views.assignments_bulk_update, name='assignments_bulk'),

    # 학생 관리
    path('admin/students/', views.student_admin, name='student_admin'),
    path('admin/students/upload/', views.student_upload, name='student_upload'),
    path('admin/students/action/', views.student_action, name='student_action'),
    path('admin/students/template.xlsx', views.student_template_xlsx, name='student_template'),
    path('admin/api/students/', views.student_list_api, name='student_list_api'),
    path('admin/api/students/<int:student_id>/info/', views.student_info_api, name='student_info_api'),
    path('admin/api/students/<int:student_id>/assignments/', views.student_assignments, name='student_assignments'),
    path('admin/api/students/<int:student_id>/assignments/update/', views.student_assignments_update, name='student_assignments_update'),
    path('admin/students/<int:student_id>/report/', views.student_report, name='student_report'),
    path('admin/students/<int:student_id>/goal/', views.student_goal_update, name='student_goal_update'),
    path('admin/api/students/<int:student_id>/goal/', views.student_goal_api, name='student_goal_api'),
    path('admin/api/students/goal/', views.student_goal_save_api, name='student_goal_save_api'),
    path('admin/api/students/plan/', views.student_plan_save_api, name='student_plan_save_api'),
    path('admin/live/', views.live_dashboard, name='live_dashboard'),
    path('admin/api/live/sessions/', views.live_sessions_api, name='live_sessions_api'),
    path('api/live/typing/', views.live_typing_update_api, name='live_typing_update'),
    path('api/flashcard/heartbeat/', views.flashcard_heartbeat_api, name='flashcard_heartbeat'),

    # 대전 모드
    path('admin/match/create/', views.match_create, name='match_create'),
    path('match/ai/', views.match_quick_ai, name='match_quick_ai'),
    path('match/<str:code>/', views.match_room, name='match_room'),
    path('api/match/<str:code>/state/', views.match_state_api, name='match_state_api'),
    path('api/match/<str:code>/start/', views.match_start_api, name='match_start_api'),
    path('api/match/<str:code>/finish/', views.match_finish_api, name='match_finish_api'),
    path('api/match/<str:code>/add_ai/', views.match_add_ai_api, name='match_add_ai_api'),
    path('api/match/<str:code>/remove_ai/', views.match_remove_ai_api, name='match_remove_ai_api'),

    # 영작 단원 업로드용 양식
    path('admin/template.xlsx', views.writing_template_xlsx, name='writing_template'),

    path('admin/units/<int:unit_id>/generate-hints/', views.generate_hints_ajax, name='generate_hints'),
    path('admin/units/<int:unit_id>/generate-hints/status/', views.generate_hints_status, name='generate_hints_status'),
    path('admin/units/<int:unit_id>/assignments/', views.assignment_list, name='assignment_list'),
    path('admin/units/<int:unit_id>/assignments/update/', views.assignment_update, name='assignment_update'),

    # 버그 신고
    path('api/bug-report/', views.bug_report_create, name='bug_report_create'),
    path('admin/bugs/', views.bug_report_list, name='bug_report_list'),
    path('admin/bugs/<int:report_id>/', views.bug_report_detail, name='bug_report_detail'),
    path('admin/bugs/<int:report_id>/rollback/', views.bug_report_rollback, name='bug_report_rollback'),
]
