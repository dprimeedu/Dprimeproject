from django.contrib import admin
from django.utils.safestring import mark_safe

from .models import Academy, SyncLog


@admin.register(Academy)
class AcademyAdmin(admin.ModelAdmin):
    list_display = ('academy_name', 'admin', 'academy_address', 'academy_phone')
    search_fields = ('academy_name', 'academy_address')


@admin.register(SyncLog)
class SyncLogAdmin(admin.ModelAdmin):
    list_display = (
        'status_icon',
        'started_at',
        'duration_display',
        'triggered_by',
        'dry_run_label',
        'target_grade',
        'target_sheet',
        'added',
        'updated',
        'skipped',
        'errors',
    )
    list_filter = ('dry_run', 'triggered_by', 'target_grade')
    readonly_fields = (
        'started_at',
        'finished_at',
        'duration_seconds',
        'triggered_by',
        'dry_run',
        'target_grade',
        'target_sheet',
        'added',
        'updated',
        'skipped',
        'errors',
        'sheet_results_pretty',
        'error_details_pretty',
        'notes',
    )
    fields = readonly_fields
    date_hierarchy = 'started_at'
    ordering = ('-started_at',)

    def status_icon(self, obj):
        return obj.status_emoji()
    status_icon.short_description = '상태'

    def duration_display(self, obj):
        if obj.duration_seconds is None:
            return '-'
        s = obj.duration_seconds
        if s < 60:
            return f'{s:.1f}초'
        return f'{int(s // 60)}분 {int(s % 60)}초'
    duration_display.short_description = '소요'

    def dry_run_label(self, obj):
        return '🔸 DRY' if obj.dry_run else ''
    dry_run_label.short_description = ''

    def sheet_results_pretty(self, obj):
        """학년×시트 결과를 표로 표시"""
        data = obj.sheet_results or {}
        if not data:
            return '(없음)'

        rows_html = [
            '<table style="border-collapse:collapse;font-size:0.9em">'
            '<thead><tr style="background:#7c3aed;color:#fff">'
            '<th style="padding:4px 8px">학년</th>'
            '<th style="padding:4px 8px">시트</th>'
            '<th style="padding:4px 8px">추가</th>'
            '<th style="padding:4px 8px">수정</th>'
            '<th style="padding:4px 8px">변경없음</th>'
            '<th style="padding:4px 8px">오류</th>'
            '</tr></thead><tbody>'
        ]
        for grade in sorted(data.keys()):
            for sheet, s in data[grade].items():
                added = s.get('added', 0)
                updated = s.get('updated', 0)
                skipped = s.get('skipped', 0)
                error = s.get('error', 0)
                err_style = 'background:#fee' if error else ''
                rows_html.append(
                    f'<tr style="{err_style}">'
                    f'<td style="padding:4px 8px;border-bottom:1px solid #eee">{grade}</td>'
                    f'<td style="padding:4px 8px;border-bottom:1px solid #eee">{sheet}</td>'
                    f'<td style="padding:4px 8px;border-bottom:1px solid #eee;text-align:right">{added:,}</td>'
                    f'<td style="padding:4px 8px;border-bottom:1px solid #eee;text-align:right">{updated:,}</td>'
                    f'<td style="padding:4px 8px;border-bottom:1px solid #eee;text-align:right">{skipped:,}</td>'
                    f'<td style="padding:4px 8px;border-bottom:1px solid #eee;text-align:right">{error:,}</td>'
                    '</tr>'
                )
        rows_html.append('</tbody></table>')
        return mark_safe(''.join(rows_html))
    sheet_results_pretty.short_description = '시트별 결과'

    def error_details_pretty(self, obj):
        details = obj.error_details or []
        if not details:
            return '(오류 없음)'
        items = []
        for d in details[:50]:
            items.append(
                f'<li><b>{d.get("sheet", "?")}</b> 행 {d.get("row", "?")}: '
                f'<code>{d.get("message", "")}</code></li>'
            )
        more = f'<p>...외 {len(details) - 50}건</p>' if len(details) > 50 else ''
        return mark_safe(f'<ul style="margin:0;padding-left:20px">{"".join(items)}</ul>{more}')
    error_details_pretty.short_description = '오류 상세'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
