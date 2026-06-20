from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve as _media_serve
from . import views
from .views import CustomLoginView

urlpatterns = [
    # 업로드 미디어 — 운영(DEBUG=False)에서도 Django가 서빙(nginx가 /media/를 여기로 프록시).
    re_path(r'^media/(?P<path>.*)$', _media_serve, {'document_root': settings.MEDIA_ROOT}),
    path('admin/', admin.site.urls),
    path("", views.HomeView.as_view(), name='index'),
    path('mock-exam/', views.MockExamView.as_view(), name='mock_exam'),
    path('training/', views.TrainingView.as_view(), name='training'),
    path('accounts/', include('allauth.urls')),
    path('accounts/register/', views.UserCreateView.as_view(), name='register'),
    path('accounts/register/done/', views.UserCreateDoneTV.as_view(), name='register_done'),
    path('login/', CustomLoginView.as_view(), name='login'),
    #path('profile/', views.profile_view, name='profile_view'),
    #path('profile/edit/', views.profile_edit_view, name='profile_edit'),
    #path('profile/', include('member.urls')),
    path('acad/', include('acad.urls')),  # 'acad.urls'에서 URL을 처리하도록 변경
    path('', include('academy.urls')),
    path('course/', include('course.urls')),
    path('member/', include('member.urls')),
    path('training/writing/', include('writing.urls')),
    path('training/vocab/', include('vocab.urls')),
    path('training/summary/', include('summary.urls')),
    path('training/exam/', include('exam.urls')),
    path('training/grammar/', include('grammar.urls')),
    path('report/', include('report.urls')),
    path('tools/', include('academy_tools.urls')),
]

handler404 = 'config.views.custom_404'
handler500 = 'config.views.custom_500'
handler403 = 'config.views.custom_403'
handler400 = 'config.views.custom_400'

# 개발 환경에서 정적/미디어 파일 제공
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
