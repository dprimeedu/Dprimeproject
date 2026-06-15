from django.urls import path
from . import views

app_name = 'grammar'

urlpatterns = [
    # 교사 — 단원 목록 (Phase 1 임시 랜딩)
    path('admin/units/', views.unit_list, name='unit_list'),

    # 외부 자동화 연동 — 토큰 인증
    path('api/import/', views.import_api, name='import'),
    path('api/range/import/', views.range_import_api, name='range_import'),
]
