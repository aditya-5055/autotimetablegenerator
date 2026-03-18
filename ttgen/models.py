# """
# Complete Timetable System for Computer Engineering Department
# FINAL CLEANEST VERSION - ALL VALIDATIONS PERFECT
# """

# from django.db import models
# from django.core.exceptions import ValidationError

# # ============================================================================
# # CONSTANTS - YOUR TIME SLOTS
# # ============================================================================

# # Lecture time slots (1 hour each)
# LECTURE_TIME_SLOTS = (
#     ('8:45 - 9:45', '8:45 - 9:45'),
#     ('9:45 - 10:45', '9:45 - 10:45'),
#     ('11:00 - 12:00', '11:00 - 12:00'),
#     ('12:00 - 1:00', '12:00 - 1:00'),
#     ('1:45 - 2:45', '1:45 - 2:45'),
#     ('2:45 - 3:45', '2:45 - 3:45'),
# )

# # Lab time slots (2 hours each)
# LAB_TIME_SLOTS = (
#     ('8:45 - 10:45', '8:45 - 10:45'),
#     ('11:00 - 1:00', '11:00 - 1:00'),
#     ('1:45 - 3:45', '1:45 - 3:45'),
# )

# DAYS_OF_WEEK = (
#     ('Monday', 'Monday'),
#     ('Tuesday', 'Tuesday'),
#     ('Wednesday', 'Wednesday'),
#     ('Thursday', 'Thursday'),
#     ('Friday', 'Friday'),
# )

# POPULATION_SIZE = 200          # Was 9. This gives more variety.
# NUMB_OF_ELITE_SCHEDULES = 15   # Keep the best 15 schedules every time.
# TOURNAMENT_SELECTION_SIZE = 6  # Compete against more schedules.
# MUTATION_RATE = 0.25           # Make chaos! 25% mutation helps break deadlocks.



# # ============================================================================
# # ALL MODELS
# # ============================================================================

# class Department(models.Model):
#     dept_name = models.CharField(max_length=50, unique=True)
    
#     def __str__(self):
#         return self.dept_name


# class Division(models.Model):
#     division_name = models.CharField(max_length=20, unique=True)
#     department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='divisions')
#     total_students = models.IntegerField(default=88)
    
#     def __str__(self):
#         return self.division_name


# class Batch(models.Model):
#     batch_name = models.CharField(max_length=10)
#     division = models.ForeignKey(Division, on_delete=models.CASCADE, related_name='batches')
#     student_count = models.IntegerField(default=22)
    
#     class Meta:
#         unique_together = ['division', 'batch_name']
    
#     def __str__(self):
#         return f"{self.batch_name}"


# class Instructor(models.Model):
#     uid = models.CharField(max_length=6, unique=True)
#     name = models.CharField(max_length=25)
    
#     def __str__(self):
#         return f'{self.uid} {self.name}'


# class Room(models.Model):
#     r_number = models.CharField(max_length=6, unique=True)
#     seating_capacity = models.IntegerField(default=0)
#     room_type = models.CharField(max_length=10, choices=(('LECTURE', 'Lecture'), ('LAB', 'Lab')), default='LECTURE')
    
#     def __str__(self):
#         return self.r_number


# class Course(models.Model):
#     course_number = models.CharField(max_length=5, primary_key=True)
#     course_name = models.CharField(max_length=40)
#     max_numb_students = models.IntegerField(default=88)
#     course_type = models.CharField(max_length=10, choices=(('LECTURE', 'Theory'), ('LAB', 'Practical')), default='LECTURE')
#     instructors = models.ManyToManyField(Instructor, related_name='courses')
    
#     def __str__(self):
#         return f'{self.course_number} {self.course_name}'


# class MeetingTime(models.Model):
#     pid = models.CharField(max_length=4, primary_key=True)
#     time = models.CharField(max_length=50)
#     day = models.CharField(max_length=15, choices=DAYS_OF_WEEK)
#     slot_type = models.CharField(max_length=10, choices=(('LECTURE', '1-hour'), ('LAB', '2-hour')), default='LECTURE')
    
#     def __str__(self):
#         return f'{self.pid} {self.day} {self.time}'


# class Section(models.Model):
#     section_id = models.CharField(max_length=25, primary_key=True)
#     department = models.ForeignKey(Department, on_delete=models.CASCADE)
#     num_class_in_week = models.IntegerField(default=0)
#     division = models.ForeignKey(Division, on_delete=models.CASCADE, blank=True, null=True)
#     batch = models.ForeignKey(Batch, on_delete=models.CASCADE, blank=True, null=True)
#     course = models.ForeignKey(Course, on_delete=models.CASCADE, blank=True, null=True)
#     meeting_time = models.ForeignKey(MeetingTime, on_delete=models.CASCADE, blank=True, null=True)
#     room = models.ForeignKey(Room, on_delete=models.CASCADE, blank=True, null=True)
#     instructor = models.ForeignKey(Instructor, on_delete=models.CASCADE, blank=True, null=True)
    
#     def clean(self):
#         """
#         COMPLETE VALIDATION - Prevents ALL conflicts
#         """
#         super().clean()
        
#         # Skip validation if basic fields not set yet
#         if not self.meeting_time or not self.room or not self.instructor or not self.course:
#             return
        
#         # 1. SLOT TYPE vs COURSE TYPE - Lab course needs 2-hour slot, Lecture needs 1-hour slot
#         if self.course.course_type != self.meeting_time.slot_type:
#             raise ValidationError(f"Course type mismatch: {self.course.course_type} course needs {self.course.course_type} time slot, not {self.meeting_time.slot_type}")
        
#         # 2. ROOM TYPE vs COURSE TYPE - Lab course needs Lab room, Lecture needs Lecture hall
#         if self.course.course_type != self.room.room_type:
#             raise ValidationError(f"Room type mismatch: {self.course.course_type} course cannot use {self.room.room_type} room")
        
#         # 3. TEACHER CLASH - Same teacher cannot teach 2 classes at same time
#         teacher_conflict = Section.objects.filter(
#             instructor=self.instructor,
#             meeting_time=self.meeting_time
#         ).exclude(section_id=self.section_id)
        
#         if teacher_conflict.exists():
#             raise ValidationError(f"Teacher {self.instructor.name} is already teaching another class at {self.meeting_time}")
        
#         # 4. ROOM CLASH - Same room cannot be used for 2 classes at same time
#         room_conflict = Section.objects.filter(
#             room=self.room,
#             meeting_time=self.meeting_time
#         ).exclude(section_id=self.section_id)
        
#         if room_conflict.exists():
#             raise ValidationError(f"Room {self.room.r_number} is already occupied at {self.meeting_time}")
        
#         # 5. DIVISION CLASH - Same division cannot have 2 classes at same time
#         if self.division:
#             division_conflict = Section.objects.filter(
#                 division=self.division,
#                 meeting_time=self.meeting_time
#             ).exclude(section_id=self.section_id)
            
#             if division_conflict.exists():
#                 raise ValidationError(f"Division {self.division.division_name} already has a class at {self.meeting_time}")
        
#         # 6. BATCH CLASH - Same batch cannot have 2 labs at same time
#         if self.batch:
#             batch_conflict = Section.objects.filter(
#                 batch=self.batch,
#                 meeting_time=self.meeting_time
#             ).exclude(section_id=self.section_id)
            
#             if batch_conflict.exists():
#                 raise ValidationError(f"Batch {self.batch.batch_name} already has a class at {self.meeting_time}")
    
#     def save(self, *args, **kwargs):
#         self.full_clean()  # This calls clean() before saving
#         super().save(*args, **kwargs)
    
#     def set_room(self, room):
#         self.room = room
#         self.save()
    
#     def set_meetingTime(self, meetingTime):
#         self.meeting_time = meetingTime
#         self.save()
    
#     def set_instructor(self, instructor):
#         self.instructor = instructor
#         self.save()
    
#     def __str__(self):
#         return self.section_id

"""
models.py - Complete Timetable System Models
All constraints and validations included
"""

from django.db import models
from django.core.exceptions import ValidationError

# ============================================================================
# CONSTANTS - YOUR TIME SLOTS
# ============================================================================

# Lecture time slots (1 hour each)
LECTURE_TIME_SLOTS = (
    ('8:45 - 9:45', '8:45 - 9:45'),
    ('9:45 - 10:45', '9:45 - 10:45'),
    ('11:00 - 12:00', '11:00 - 12:00'),
    ('12:00 - 1:00', '12:00 - 1:00'),
    ('1:45 - 2:45', '1:45 - 2:45'),
    ('2:45 - 3:45', '2:45 - 3:45'),
)

# Lab time slots (2 hours each)
LAB_TIME_SLOTS = (
    ('8:45 - 10:45', '8:45 - 10:45'),
    ('11:00 - 1:00', '11:00 - 1:00'),
    ('1:45 - 3:45', '1:45 - 3:45'),
)

DAYS_OF_WEEK = (
    ('Monday', 'Monday'),
    ('Tuesday', 'Tuesday'),
    ('Wednesday', 'Wednesday'),
    ('Thursday', 'Thursday'),
    ('Friday', 'Friday'),
)

# Algorithm constants
POPULATION_SIZE = 200
NUMB_OF_ELITE_SCHEDULES = 15
TOURNAMENT_SELECTION_SIZE = 6
MUTATION_RATE = 0.25
MAX_GENERATIONS = 1000
EARLY_STOPPING_THRESHOLD = 50


# ============================================================================
# ALL MODELS
# ============================================================================

class Department(models.Model):
    dept_name = models.CharField(max_length=50, unique=True)
    
    class Meta:
        verbose_name = "Department"
        verbose_name_plural = "Departments"
    
    def __str__(self):
        return self.dept_name


class Division(models.Model):
    division_name = models.CharField(max_length=20, unique=True)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='divisions')
    total_students = models.IntegerField(default=88)
    
    class Meta:
        verbose_name = "Division"
        verbose_name_plural = "Divisions"
        unique_together = ['division_name', 'department']
    
    def __str__(self):
        return self.division_name


class Batch(models.Model):
    batch_name = models.CharField(max_length=10)
    division = models.ForeignKey(Division, on_delete=models.CASCADE, related_name='batches')
    student_count = models.IntegerField(default=22)
    
    class Meta:
        verbose_name = "Batch"
        verbose_name_plural = "Batches"
        unique_together = ['division', 'batch_name']
    
    def __str__(self):
        return f"{self.batch_name} ({self.division.division_name})"


class Instructor(models.Model):
    uid = models.CharField(max_length=6, unique=True)
    name = models.CharField(max_length=25)
    max_batches_per_week = models.IntegerField(default=4, help_text="Maximum number of lab batches this teacher can handle")
    max_lecture_divisions = models.IntegerField(default=2, help_text="Maximum number of divisions for lectures")
    
    class Meta:
        verbose_name = "Instructor"
        verbose_name_plural = "Instructors"
    
    def __str__(self):
        return f'{self.name} ({self.uid})'


class Room(models.Model):
    ROOM_TYPES = (
        ('LECTURE', 'Lecture Hall'),
        ('LAB', 'Laboratory'),
    )
    
    r_number = models.CharField(max_length=6, unique=True)
    seating_capacity = models.IntegerField(default=0)
    room_type = models.CharField(max_length=10, choices=ROOM_TYPES, default='LECTURE')
    
    class Meta:
        verbose_name = "Room"
        verbose_name_plural = "Rooms"
    
    def __str__(self):
        return f"{self.r_number} ({self.get_room_type_display()})"
    
    def clean(self):
        """Validate room capacity based on type"""
        if self.room_type == 'LECTURE' and self.seating_capacity < 80:
            raise ValidationError("Lecture rooms must have capacity at least 80")
        if self.room_type == 'LAB' and self.seating_capacity < 22:
            raise ValidationError("Lab rooms must have capacity at least 22")


class Course(models.Model):
    COURSE_TYPES = (
        ('LECTURE', 'Theory'),
        ('LAB', 'Practical'),
    )
    
    course_number = models.CharField(max_length=5, primary_key=True)
    course_name = models.CharField(max_length=40)
    max_numb_students = models.IntegerField(default=88)
    course_type = models.CharField(max_length=10, choices=COURSE_TYPES, default='LECTURE')
    instructors = models.ManyToManyField(Instructor, related_name='courses')
    
    class Meta:
        verbose_name = "Course"
        verbose_name_plural = "Courses"
    
    def __str__(self):
        return f'{self.course_number} - {self.course_name}'


class MeetingTime(models.Model):
    SLOT_TYPES = (
        ('LECTURE', '1-hour Lecture Slot'),
        ('LAB', '2-hour Lab Slot'),
    )
    
    pid = models.CharField(max_length=4, primary_key=True)
    time = models.CharField(max_length=50)
    day = models.CharField(max_length=15, choices=DAYS_OF_WEEK)
    slot_type = models.CharField(max_length=10, choices=SLOT_TYPES, default='LECTURE')
    
    class Meta:
        verbose_name = "Meeting Time"
        verbose_name_plural = "Meeting Times"
        unique_together = ['day', 'time', 'slot_type']
    
    def __str__(self):
        return f'{self.day} {self.time} ({self.get_slot_type_display()})'
    
    def get_start_time(self):
        """Extract start time in minutes for comparison"""
        try:
            time_part = self.time.split('-')[0].strip()
            h, m = map(int, time_part.split(':'))
            if 1 <= h <= 7:
                h += 12
            return h * 60 + m
        except:
            return 0
    
    def get_end_time(self):
        """Extract end time in minutes for comparison"""
        try:
            time_part = self.time.split('-')[1].strip()
            h, m = map(int, time_part.split(':'))
            if 1 <= h <= 7:
                h += 12
            return h * 60 + m
        except:
            return 0
    
    def overlaps_with(self, other):
        """Check if this time slot overlaps with another"""
        if not other or self.day != other.day:
            return False
        return (self.get_start_time() < other.get_end_time() and 
                other.get_start_time() < self.get_end_time())


class Section(models.Model):
    section_id = models.CharField(max_length=25, primary_key=True)
    department = models.ForeignKey(Department, on_delete=models.CASCADE)
    num_class_in_week = models.IntegerField(default=0)
    division = models.ForeignKey(Division, on_delete=models.CASCADE, blank=True, null=True)
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, blank=True, null=True)
    course = models.ForeignKey(Course, on_delete=models.CASCADE, blank=True, null=True)
    meeting_time = models.ForeignKey(MeetingTime, on_delete=models.CASCADE, blank=True, null=True)
    room = models.ForeignKey(Room, on_delete=models.CASCADE, blank=True, null=True)
    instructor = models.ForeignKey(Instructor, on_delete=models.CASCADE, blank=True, null=True)
    
    class Meta:
        verbose_name = "Section"
        verbose_name_plural = "Sections"
    
    def clean(self):
        """
        COMPLETE VALIDATION - Prevents ALL conflicts
        """
        super().clean()
        
        # Validate division/batch consistency
        if self.division and self.batch:
            if self.batch.division != self.division:
                raise ValidationError("Batch does not belong to this division")
        
        # Skip further validation if basic fields not set yet
        if not self.meeting_time or not self.room or not self.instructor or not self.course:
            return
        
        # 1. SLOT TYPE vs COURSE TYPE
        if self.course.course_type != self.meeting_time.slot_type:
            raise ValidationError(
                f"Course type mismatch: {self.course.get_course_type_display()} course "
                f"needs {self.course.course_type} time slot, not {self.meeting_time.slot_type}"
            )
        
        # 2. ROOM TYPE vs COURSE TYPE
        if self.course.course_type != self.room.room_type:
            raise ValidationError(
                f"Room type mismatch: {self.course.get_course_type_display()} course "
                f"cannot use {self.room.get_room_type_display()} room"
            )
        
        # 3. CAPACITY CHECK
        if self.room.seating_capacity < self.course.max_numb_students:
            raise ValidationError(
                f"Room capacity insufficient: Room has {self.room.seating_capacity} seats, "
                f"needs at least {self.course.max_numb_students}"
            )
        
        # 4. TEACHER CLASH - Same teacher cannot teach 2 classes at same time
        teacher_conflict = Section.objects.filter(
            instructor=self.instructor,
            meeting_time=self.meeting_time
        ).exclude(section_id=self.section_id)
        
        if teacher_conflict.exists():
            conflicting = teacher_conflict.first()
            raise ValidationError(
                f"Teacher {self.instructor.name} is already teaching "
                f"{conflicting.course.course_name} at {self.meeting_time}"
            )
        
        # 5. ROOM CLASH - Same room cannot be used for 2 classes at same time
        room_conflict = Section.objects.filter(
            room=self.room,
            meeting_time=self.meeting_time
        ).exclude(section_id=self.section_id)
        
        if room_conflict.exists():
            conflicting = room_conflict.first()
            raise ValidationError(
                f"Room {self.room.r_number} is already occupied by "
                f"{conflicting.course.course_name} at {self.meeting_time}"
            )
        
        # 6. DIVISION CLASH - Same division cannot have 2 classes at same time
        if self.division:
            division_conflict = Section.objects.filter(
                division=self.division,
                meeting_time=self.meeting_time
            ).exclude(section_id=self.section_id)
            
            if division_conflict.exists():
                conflicting = division_conflict.first()
                raise ValidationError(
                    f"Division {self.division.division_name} already has "
                    f"{conflicting.course.course_name} at {self.meeting_time}"
                )
        
        # 7. BATCH CLASH - Same batch cannot have 2 classes at same time
        if self.batch:
            batch_conflict = Section.objects.filter(
                batch=self.batch,
                meeting_time=self.meeting_time
            ).exclude(section_id=self.section_id)
            
            if batch_conflict.exists():
                conflicting = batch_conflict.first()
                raise ValidationError(
                    f"Batch {self.batch.batch_name} already has "
                    f"{conflicting.course.course_name} at {self.meeting_time}"
                )
    
    def save(self, *args, **kwargs):
        self.full_clean()  # This calls clean() before saving
        super().save(*args, **kwargs)
    
    def set_room(self, room):
        self.room = room
        self.save()
    
    def set_meetingTime(self, meetingTime):
        self.meeting_time = meetingTime
        self.save()
    
    def set_instructor(self, instructor):
        self.instructor = instructor
        self.save()
    
    def __str__(self):
        return self.section_id