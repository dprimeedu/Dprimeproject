from django import template

register = template.Library()

@register.filter
def line_feed(value):
    """
    개행 바꾸는 커스텀 태그
    """
    if not value: return
    return value.replace("\\r\\n", "<br>")


@register.filter
def underline(value):
    """
    밑줄 치는 커스텀 태그

    "￰"(U+FFF0) 사용
    """
    if not value: return

    import re
    pattern = r"\uFFF0(.*?)\uFFF0"

    text = re.sub(pattern, r"<ins>\1</ins>", value)
    return text