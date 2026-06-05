from django.urls import path
from . import views

app_name = 'vocab'

urlpatterns = [
    # 학생
    path('', views.student_home, name='home'),
    path('unit/<int:unit_id>/flashcard/', views.flashcard_view, name='flashcard'),

    # 학생 — 개인별 시험범위(내신단어TEST)
    path('range/<int:range_test_id>/test/', views.range_test_take, name='range_test'),
    path('range/<int:range_test_id>/flashcard/', views.range_flashcard_view, name='range_flashcard'),

    # 학생 — 별표 모음
    path('stars/', views.star_flashcard, name='star_flashcard'),

    # 학생 — 단어찾기 (낱말카드 만들기)
    path('cards/', views.wordcard_list, name='wordcard_list'),
    path('cards/new/', views.wordcard_new, name='wordcard_new'),
    path('cards/<int:set_id>/edit/', views.wordcard_edit, name='wordcard_edit'),
    path('cards/<int:set_id>/flashcard/', views.wordcard_flashcard, name='wordcard_flashcard'),
    path('cards/<int:set_id>/delete/', views.wordcard_delete, name='wordcard_delete'),
    path('api/cards/save/', views.wordcard_save_api, name='wordcard_save'),
    path('api/dict/lookup/', views.dict_lookup_api, name='dict_lookup'),

    # AJAX API
    path('api/star/toggle/', views.star_toggle_api, name='star_toggle'),
    path('api/wordcard-star/toggle/', views.wordcard_star_toggle_api, name='wordcard_star_toggle'),
    path('api/test/answer/', views.test_answer_api, name='test_answer'),
    path('api/test/finish/', views.test_finish_api, name='test_finish'),
    path('api/range/start/', views.range_test_start_api, name='range_start'),

    # 선생님 / 관리자 — 시험 검수
    path('admin/reviews/', views.review_list, name='review_list'),
    path('admin/reviews/<int:session_id>/', views.review_detail, name='review_detail'),
    path('admin/reviews/<int:session_id>/update/', views.review_update_api, name='review_update'),
    path('admin/range/threshold/', views.range_threshold_api, name='range_threshold'),

    # 외부 자동화(개별단어장생성.py) 연동 — 토큰 인증
    path('api/range/import/', views.range_import_api, name='range_import'),
    path('api/range/results/', views.range_results_api, name='range_results'),
    path('api/unit/word-counts/', views.unit_word_counts_api, name='unit_word_counts'),

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
