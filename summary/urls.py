from django.urls import path
from . import views

app_name = 'summary'

urlpatterns = [
    # 학생
    path('', views.student_home, name='home'),
    path('unit/<int:unit_id>/start/', views.start_session, name='start_session'),
    path('session/<int:session_id>/', views.session_view, name='session'),
    path('result/<int:session_id>/', views.result_view, name='result'),

    # 학생 — AJAX
    path('api/check-blank/', views.check_blank_api, name='check_blank'),
    path('api/submit/', views.submit_session_api, name='submit'),

    # 선생님 / 관리자 — 채점
    path('admin/grading/', views.grade_list, name='grade_list'),
    path('admin/grading/<int:session_id>/', views.grade_detail, name='grade_detail'),
    path('admin/grading/<int:session_id>/update/', views.grade_update_api, name='grade_update'),

    # 선생님 / 관리자 — 단원 관리 + 배정
    path('admin/units/', views.unit_list, name='unit_list'),
    path('admin/units/delete/', views.unit_delete, name='unit_delete'),
    path('admin/units/<int:unit_id>/assignments/', views.assignment_list, name='assignment_list'),
    path('admin/units/<int:unit_id>/assignments/update/', views.assignment_update, name='assignment_update'),

    # 외부 자동화(AI 자동화 요약문 생성) 연동 — 토큰 인증
    path('api/import/', views.import_api, name='import'),
    # 오늘 볼 TEST 범위 등록 (학생관리표 '요약문완성' → 요약문TEST_웹동기화.py)
    path('api/range/import/', views.range_import_api, name='range_import'),
]
