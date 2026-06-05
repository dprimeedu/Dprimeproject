from django.urls import path
from . import views

app_name = 'report'

urlpatterns = [
    path('', views.daily_input, name='input'),
    path('list/', views.report_list, name='list'),
    path('autofill/', views.autofill, name='autofill'),
    path('generate/', views.generate_date, name='generate_date'),
    path('generate/<int:record_id>/', views.generate_one, name='generate_one'),

    # 하이브리드 카톡용 API (토큰)
    path('api/kakao/today/', views.kakao_today_api, name='kakao_today'),
]
