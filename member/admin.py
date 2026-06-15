from django.contrib import admin
from .models import Member


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = (
        'login_id', 'username', 'email', 'member_type',
        'is_active', 'is_approved', 'is_academy', 'academy_access', 'date_joined',
    )
    list_editable = ('academy_access',)
    search_fields = ('login_id', 'username', 'email', 'phone')
    list_filter = ('member_type', 'is_active', 'is_approved', 'is_academy', 'academy_access')
    readonly_fields = ('date_joined', 'last_login')
    fieldsets = (
        ('계정', {
            'fields': ('login_id', 'email', 'username', 'password'),
        }),
        ('권한', {
            'fields': ('is_active', 'is_approved', 'is_staff', 'is_superuser', 'is_academy', 'member_type', 'academy_access'),
        }),
        ('연락처/기타', {
            'fields': ('phone', 'business_registration'),
        }),
        ('이력', {
            'fields': ('date_joined', 'last_login'),
        }),
    )
