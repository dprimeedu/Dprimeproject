from django.urls import path
from . import views

app_name = 'vocab'

urlpatterns = [
    # 학생
    path('', views.student_home, name='home'),
    path('unit/<int:unit_id>/flashcard/', views.flashcard_view, name='flashcard'),

    # AJAX API
    path('api/star/toggle/', views.star_toggle_api, name='star_toggle'),
]
