from django.urls import path

from . import views

app_name = 'academy_tools'

urlpatterns = [
    path('sub-book/', views.SubBookView.as_view(), name='sub_book'),
    path('sub-book/parse-paste/', views.PastePreviewView.as_view(), name='parse_paste'),
    path('sub-book/download/', views.DownloadView.as_view(), name='download'),
]
