from django.urls import path
from . import views

app_name = 'exam'

urlpatterns = [
    # 학생/교사 홈
    path('', views.student_home, name='home'),

    # 응시
    path('mock-redblue/', views.mock_redblue, name='mock_redblue'),
    path('start/mock/', views.start_mock, name='start_mock'),
    path('start/paper/<int:paper_id>/', views.start_paper, name='start_paper'),
    path('session/<int:session_id>/', views.session_view, name='session'),
    path('result/<int:session_id>/', views.result_view, name='result'),

    # 학생 — AJAX
    path('api/save/', views.save_progress_api, name='save_progress'),
    path('api/submit/', views.submit_session_api, name='submit'),
    path('api/submit2/', views.submit_round2_api, name='submit2'),
    path('api/set-exam-date/', views.set_exam_date, name='set_exam_date'),

    # 교사 — 빨파정답 학생 공개
    path('api/release-redblue/<int:session_id>/', views.release_redblue, name='release_redblue'),
    # 학생 — 빨파채점 완료 표시(공개된 빨파답으로 자기채점 끝)
    path('api/mark-redblue-done/<int:session_id>/', views.mark_redblue_done, name='mark_redblue_done'),
    # 교사 — 학생 빨파채점 검토 후 최종 확인(이전 시험을 학생 홈에서 숨김)
    path('api/final-confirm/<int:session_id>/', views.final_confirm, name='final_confirm'),

    # 빨파 정답 PDF (내신) — nginx X-Accel-Redirect 로 NAS 교재폴더에서 스트리밍
    path('redblue/<int:question_id>.pdf', views.redblue_pdf, name='redblue_pdf'),

    # 선생님 / 관리자
    path('admin/results/', views.result_list, name='result_list'),
    path('admin/paper/<int:paper_id>/wrong/', views.wrong_summary, name='wrong_summary'),
    path('admin/assign/mock/', views.mock_assign_redirect, name='mock_assign'),
    path('admin/assign/<int:paper_id>/', views.assign_view, name='assign'),

    # 외부 연동 — 내신 정답 import (토큰)
    path('api/import-naesin/', views.import_naesin_api, name='import_naesin'),
    path('api/import-image/', views.import_image_api, name='import_image'),
    path('api/import-student-schedule/', views.import_student_schedule, name='import_student_schedule'),
    path('api/import-student-mock/', views.import_student_mock_api, name='import_student_mock'),
    path('api/student-pending/', views.student_pending_api, name='student_pending'),
]
