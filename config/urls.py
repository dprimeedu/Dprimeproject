from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.contrib.auth.views import LogoutView
from django.urls import path, include, re_path, reverse_lazy
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
    # base.html 이 {% url 'logout' %} 를 참조 — allauth.urls 는 'account_logout' 만
    # 제공하므로 Django 기본 LogoutView 를 같은 이름으로 노출.
    path('logout/', LogoutView.as_view(next_page='/'), name='logout'),

    # 비밀번호 재설정 — Django 기본 뷰 4단계.
    path(
        'accounts/password-reset/',
        auth_views.PasswordResetView.as_view(
            template_name='registration/password_reset_form.html',
            email_template_name='registration/password_reset_email.html',
            subject_template_name='registration/password_reset_subject.txt',
            success_url=reverse_lazy('password_reset_done'),
        ),
        name='password_reset',
    ),
    path(
        'accounts/password-reset/done/',
        auth_views.PasswordResetDoneView.as_view(
            template_name='registration/password_reset_done.html',
        ),
        name='password_reset_done',
    ),
    path(
        'accounts/reset/<uidb64>/<token>/',
        auth_views.PasswordResetConfirmView.as_view(
            template_name='registration/password_reset_confirm.html',
            success_url=reverse_lazy('password_reset_complete'),
        ),
        name='password_reset_confirm',
    ),
    path(
        'accounts/reset/done/',
        auth_views.PasswordResetCompleteView.as_view(
            template_name='registration/password_reset_complete.html',
        ),
        name='password_reset_complete',
    ),
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
