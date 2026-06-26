from django.urls import path
from . import views
from .views import profile_edit_view

app_name = 'member'

urlpatterns = [
    # Authentication
    # path('login/', views.login_view, name='login'),
    # path('logout/', views.logout_view, name='logout'),
    # path('signup/', views.signup_view, name='signup'),
    # path('signup/done/', views.signup_done_view, name='signup_done'),
    
    # Social Auth
    # path('login/kakao/', views.kakao_login, name='kakao_login'),
    # path('login/kakao/callback/', views.kakao_callback, name='kakao_callback'),
    
    # 소셜 가입 후 학생/학원 유형 1회 선택
    path('select-type/', views.select_type, name='select_type'),

    # Profile
    path('profile/', views.profile_view, name='profile_view'),
    path('profile/edit/', views.profile_edit_view, name='profile_edit'),
    path('password/change/', views.change_password_view, name='change_password'),  # 비밀번호 변경 (추가 예정)
    
    # Messages
    # path('messages/', views.message_list_view, name='message_list'),
    # path('messages/<int:message_id>/', views.message_detail_view, name='message_detail'),
    # path('messages/send/', views.message_send_view, name='message_send'),
    
    # Notifications
    # path('notifications/', views.notification_list_view, name='notification_list'),
    # path('notifications/mark-read/', views.mark_notifications_read, name='mark_notifications_read'),
    
    # Favorites
    # path('favorites/', views.favorite_list_view, name='favorite_list'),
    # path('favorites/add/<int:course_id>/', views.favorite_add_view, name='favorite_add'),
    # path('favorites/remove/<int:course_id>/', views.favorite_remove_view, name='favorite_remove'),
]