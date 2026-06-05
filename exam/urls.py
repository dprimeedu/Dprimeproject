from django.urls import path
from . import views

app_name = 'exam'

urlpatterns = [
    # 학생/교사 홈
    path('', views.student_home, name='home'),

    # 응시
    path('start/mock/', views.start_mock, name='start_mock'),
    path('start/paper/<int:paper_id>/', views.start_paper, name='start_paper'),
    path('session/<int:session_id>/', views.session_view, name='session'),
    path('result/<int:session_id>/', views.result_view, name='result'),

    # 학생 — AJAX
    path('api/submit/', views.submit_session_api, name='submit'),

    # 선생님 / 관리자
    path('admin/results/', views.result_list, name='result_list'),
    path('admin/assign/mock/', views.mock_assign_redirect, name='mock_assign'),
    path('admin/assign/<int:paper_id>/', views.assign_view, name='assign'),

    # 외부 연동 — 내신 정답 import (토큰)
    path('api/import-naesin/', views.import_naesin_api, name='import_naesin'),
]
