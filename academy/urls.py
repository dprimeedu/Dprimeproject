from django.contrib import admin
from django.urls import path, include
from django.urls import path
from .views import download_pdf
from . import views

app_name = 'academy'

urlpatterns = [
    path('academy_list/', views.academy_list, name='academy_list'),
    path('academy_list_result/', views.academy_list_result, name='academy_list_result'),
    path('exam_list_result/', views.exam_list_result, name='exam_list_result'),
    path('download_pdf/', download_pdf, name='download_pdf'),
    #path('create/', views.academy_create, name='academy_create'),
    #path('<int:academy_id>/edit/', views.academy_edit, name='academy_edit'),
    #path('<int:academy_id>/delete/', views.academy_delete, name='academy_delete'),
    #path('<int:academy_id>/courses/', views.course_list, name='course_list'),
    #path('<int:academy_id>/courses/create/', views.course_create, name='course_create'),
    #path('<int:academy_id>/courses/<int:course_id>/', views.course_detail, name='course_detail'),
    #path('<int:academy_id>/courses/<int:course_id>/edit/', views.course_edit, name='course_edit'),
    #path('<int:academy_id>/courses/<int:course_id>/delete/', views.course_delete, name='course_delete'),
    #path('<int:academy_id>/reviews/', views.review_list, name='review_list'),
    #path('<int:academy_id>/courses/<int:course_id>/reviews/create/', views.review_create, name='review_create'),
    #path('<int:academy_id>/events/', views.event_list, name='event_list'),
    #path('<int:academy_id>/events/create/', views.event_create, name='event_create'),
]
