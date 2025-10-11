from django.contrib import admin
from .models import Member

# admin.site.register(Member, UserAdmin)
@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ('username', 'email', 'is_active', 'member_type', 'phone')
    search_fields = ('username', 'email', 'phone')
    list_filter = ('member_type',)

    add_fieldsets = ( 
        (None, {
            'classes': ('wide', ),
            'flelds': ('email', 'password', 'is_active', 'is_staff', 'is_superuser')

        })
    )