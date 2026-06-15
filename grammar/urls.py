from django.urls import path
from . import views

app_name = 'grammar'

urlpatterns = [
    # 학생
    path('', views.student_home, name='home'),
    path('unit/<int:unit_id>/start/', views.start_session, name='start_session'),
    path('session/<int:session_id>/retry/', views.start_retry, name='start_retry'),
    path('session/<int:session_id>/', views.session_view, name='session'),
    path('result/<int:session_id>/', views.result_view, name='result'),
    path('api/submit/', views.submit_session_api, name='submit'),

    # 교사 / 관리자 — 단원 + 채점
    path('admin/units/', views.unit_list, name='unit_list'),
    path('admin/grading/', views.grade_list, name='grade_list'),
    path('admin/grading/<int:session_id>/', views.grade_detail, name='grade_detail'),
    path('admin/grading/<int:session_id>/update/', views.grade_update_api, name='grade_update'),

    # 외부 자동화 연동 — 토큰 인증
    path('api/import/', views.import_api, name='import'),
    path('api/range/import/', views.range_import_api, name='range_import'),
]
