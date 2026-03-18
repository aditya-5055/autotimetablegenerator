# ttgen/templatetags/custom_filters.py
from django import template

register = template.Library()

@register.filter
def split(value, key):
    """
    Splits a string by the given key and returns a list
    Usage: {{ "a,b,c"|split:"," }} returns ['a', 'b', 'c']
    """
    try:
        return value.split(key)
    except (AttributeError, TypeError):
        return [value]

@register.filter
def get_item(dictionary, key):
    """
    Get an item from a dictionary by key
    Usage: {{ mydict|get_item:key }}
    """
    try:
        return dictionary.get(key)
    except:
        return None

@register.filter
def get_division_name(obj):
    """Get division name from a class object"""
    if hasattr(obj, 'division') and obj.division:
        return obj.division.division_name
    if hasattr(obj, 'batch') and obj.batch and obj.batch.division:
        return obj.batch.division.division_name
    return 'N/A'

@register.filter
def get_batch_name(obj):
    """Get batch name from a class object"""
    if hasattr(obj, 'batch') and obj.batch:
        return obj.batch.batch_name
    return ''

@register.filter
def get_course_type_display(obj):
    """Get course type display"""
    if hasattr(obj, 'course') and obj.course:
        return obj.course.get_course_type_display()
    return ''