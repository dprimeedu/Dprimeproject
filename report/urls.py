from django.urls import path
from . import views

app_name = 'report'

urlpatterns = [
    path('', views.daily_input, name='input'),
    path('list/', views.report_list, name='list'),

    # 종합 학습 현황 (4과목 세션 자동 집계)
    path('study/', views.study_board, name='study_board'),
    path('study/<int:student_id>/', views.study_report, name='study_report'),

    # 학생 본인용 '나의 학습 리포트'
    path('me/', views.my_report, name='my_report'),
    path('autofill/', views.autofill, name='autofill'),
    path('generate/', views.generate_date, name='generate_date'),
    path('generate/<int:record_id>/', views.generate_one, name='generate_one'),

    # 하이브리드 카톡용 API (토큰)
    path('api/kakao/today/', views.kakao_today_api, name='kakao_today'),
]
