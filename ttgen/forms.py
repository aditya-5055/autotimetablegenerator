from django.forms import ModelForm
from .models import *
from django import forms


class DepartmentForm(ModelForm):
    class Meta:
        model = Department
        fields = ['dept_name']
        labels = {
            "dept_name": "Department Name"
        }


class DivisionForm(ModelForm):
    class Meta:
        model = Division
        fields = ['division_name', 'department', 'total_students']
        labels = {
            "division_name": "Division Name",
            "department": "Department",
            "total_students": "Total Students"
        }


class BatchForm(ModelForm):
    class Meta:
        model = Batch
        fields = ['batch_name', 'division', 'student_count']
        labels = {
            "batch_name": "Batch Name",
            "division": "Division",
            "student_count": "Student Count"
        }


class InstructorForm(ModelForm):
    class Meta:
        model = Instructor
        fields = ['uid', 'name']
        labels = {
            "uid": "Teacher ID",
            "name": "Full Name"
        }


class RoomForm(ModelForm):
    class Meta:
        model = Room
        fields = ['r_number', 'seating_capacity', 'room_type']
        labels = {
            "r_number": "Room Number",
            "seating_capacity": "Capacity",
            "room_type": "Room Type"
        }


class CourseForm(ModelForm):
    class Meta:
        model = Course
        fields = ['course_number', 'course_name', 'max_numb_students', 'course_type', 'instructors']
        labels = {
            "course_number": "Course Code",
            "course_name": "Course Name",
            "max_numb_students": "Max Students",
            "course_type": "Course Type",
            "instructors": "Qualified Instructors"
        }


class MeetingTimeForm(ModelForm):
    class Meta:
        model = MeetingTime
        fields = ['pid', 'time', 'day', 'slot_type']
        labels = {
            "pid": "Meeting ID",
            "time": "Time Slot",
            "day": "Day",
            "slot_type": "Slot Type"
        }


class SectionForm(ModelForm):
    class Meta:
        model = Section
        fields = ['section_id', 'department', 'num_class_in_week', 'division', 'batch', 'course']
        labels = {
            "section_id": "Section ID",
            "department": "Department",
            "num_class_in_week": "Classes Per Week",
            "division": "Division (for Lecture)",
            "batch": "Batch (for Lab)",
            "course": "Course"
        }
        help_texts = {
            "division": "Select for Lecture courses (whole division)",
            "batch": "Select for Lab courses (single batch)"
        }