from django import template

register = template.Library()

@register.filter
def line_feed(value):
    """
    개행 바꾸는 커스텀 태그
    """
    if not value: return
    return value.replace("\\r\\n", "<br>")