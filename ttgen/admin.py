from django.contrib import admin
from .models import *


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ['dept_name']
    search_fields = ['dept_name']


@admin.register(Division)
class DivisionAdmin(admin.ModelAdmin):
    list_display = ['division_name', 'department', 'total_students']
    list_filter = ['department']
    search_fields = ['division_name']


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ['batch_name', 'division', 'student_count']
    list_filter = ['division']
    search_fields = ['batch_name']
    ordering = ['division', 'batch_name']


@admin.register(Instructor)
class InstructorAdmin(admin.ModelAdmin):
    list_display = ['uid', 'name']
    search_fields = ['uid', 'name']


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ['r_number', 'room_type', 'seating_capacity']
    list_filter = ['room_type']
    search_fields = ['r_number']
    ordering = ['room_type', 'r_number']


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ['course_number', 'course_name', 'course_type', 'max_numb_students']
    list_filter = ['course_type']
    search_fields = ['course_number', 'course_name']
    filter_horizontal = ['instructors']


@admin.register(MeetingTime)
class MeetingTimeAdmin(admin.ModelAdmin):
    list_display = ['pid', 'day', 'time', 'slot_type']
    list_filter = ['day', 'slot_type']
    search_fields = ['pid']
    ordering = ['day', 'time']


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ['section_id', 'department', 'division', 'batch', 'course', 'instructor', 'room', 'meeting_time']
    list_filter = ['department', 'division', 'course']
    search_fields = ['section_id']
    autocomplete_fields = ['course', 'instructor', 'room', 'meeting_time']