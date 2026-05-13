from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """الحصول على عنصر من dictionary باستخدام key"""
    try:
        return dictionary.get(int(key), 0)
    except (ValueError, AttributeError):
        return 0


@register.filter
def multiply(value, arg):
    """ضرب قيمتين"""
    try:
        return float(value) * float(arg)
    except (ValueError, TypeError):
        return 0


@register.filter
def divide(value, arg):
    """قسمة قيمتين"""
    try:
        if float(arg) == 0:
            return 0
        return float(value) / float(arg)
    except (ValueError, TypeError):
        return 0


@register.filter
def percentage(value, total):
    """حساب النسبة المئوية"""
    try:
        if float(total) == 0:
            return 0
        return round((float(value) / float(total)) * 100, 1)
    except (ValueError, TypeError):
        return 0


@register.filter
def stars_range(value):
    """إنشاء range للنجوم"""
    try:
        return range(1, int(value) + 1)
    except (ValueError, TypeError):
        return range(0)