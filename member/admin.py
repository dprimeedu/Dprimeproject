from django.contrib import admin

from .models import IPAccessLog, Member, UserIP


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = (
        'login_id', 'username', 'email', 'member_type',
        'is_active', 'is_approved', 'is_academy', 'academy_access',
        'max_allowed_ips', 'date_joined',
    )
    list_editable = ('academy_access', 'max_allowed_ips')
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
        ('접속 제한', {
            'fields': ('max_allowed_ips',),
            'description': '0 = 무제한. 1 이상이면 등록된 IP에서만 로그인 가능합니다.',
        }),
        ('연락처/기타', {
            'fields': ('phone', 'business_registration'),
        }),
        ('이력', {
            'fields': ('date_joined', 'last_login'),
        }),
    )


@admin.register(UserIP)
class UserIPAdmin(admin.ModelAdmin):
    list_display = ('user', 'ip_address', 'access_count', 'first_seen', 'last_seen')
    list_filter = ('user',)
    search_fields = ('user__email', 'user__login_id', 'user__username', 'ip_address')
    readonly_fields = ('first_seen', 'last_seen', 'access_count')
    ordering = ('-last_seen',)


@admin.register(IPAccessLog)
class IPAccessLogAdmin(admin.ModelAdmin):
    list_display = ('accessed_at', 'user', 'ip_address', 'status', 'path')
    list_filter = ('status', 'accessed_at')
    search_fields = ('user__email', 'user__login_id', 'user__username', 'ip_address')
    readonly_fields = ('user', 'ip_address', 'status', 'path', 'user_agent', 'accessed_at')
    date_hierarchy = 'accessed_at'
    ordering = ('-accessed_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
