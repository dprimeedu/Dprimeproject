from django.apps import AppConfig


class SummaryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'summary'
    verbose_name = '요약문완성훈련'
