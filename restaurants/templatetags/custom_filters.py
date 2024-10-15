from django import template
from django.utils.timezone import localtime
import datetime

register = template.Library()

@register.filter
def get_attribute(obj, attr):
    """
    Gets an attribute of an object dynamically from a string name
    """
    if hasattr(obj, str(attr)):
        value = getattr(obj, attr)
        if value is None:
            return ''
        if isinstance(value, datetime.time):
            return value.strftime('%H:%M')
        return value
    elif hasattr(obj, 'get'):
        return obj.get(attr) or ''
    else:
        return ''
    


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)