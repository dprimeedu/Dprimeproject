from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from . import views
from .views import CustomLoginView

urlpatterns = [
    path('admin/', admin.site.urls),
    path("", views.HomeView.as_view(), name='index'),
    path('accounts/', include('django.contrib.auth.urls')),
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
]

handler404 = 'config.views.custom_404'
handler500 = 'config.views.custom_500'
handler403 = 'config.views.custom_403'
handler400 = 'config.views.custom_400'

# 개발 환경에서 정적 파일 제공
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
