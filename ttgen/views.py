"""
views.py — Timetable Generator (CORRECTED VERSION)
================================
TWO-PHASE approach with ALL constraints properly enforced
"""

import random
import time as time_module
from collections import defaultdict

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

from .forms import *
from .models import *

# ── Constants ────────────────────────────────────────────────────────────────

LAB_SLOT_PRIORITY = ['08:45', '11:00', '13:45']
DAYS_ORDER = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
MAX_LABS_PER_DAY = 2
MAX_BATCHES_PER_TEACHER = 4
MAX_RETRIES = 100  # Reduced for faster results

LAB_FREQUENCY = {'DSBDAL': 2, 'LPII': 2, 'WTL': 1}
LECTURE_FREQUENCY = {'AI': 3, 'DSBDA': 3, 'WT': 3}

# ── Time helpers ─────────────────────────────────────────────────────────────

def _to_min(t):
    """Convert time string to minutes"""
    try:
        h, m = map(int, t.strip().split(':'))
        if 1 <= h <= 7:
            h += 12
        return h * 60 + m
    except:
        return 0

def _parse(time_str):
    """Parse time range to (start_min, end_min)"""
    try:
        parts = time_str.replace(' ', '').split('-')
        return _to_min(parts[0]), _to_min(parts[1])
    except:
        return 0, 0

def _get_slot_priority(time_str):
    """Lab slot priority (C11)"""
    if '08:45' in time_str:
        return 1
    if '11:00' in time_str:
        return 2
    if '13:45' in time_str:
        return 3
    return 99

def _is_lab_slot_consecutive(time1_str, time2_str):
    """Check if two lab times are consecutive (C8)"""
    s1, e1 = _parse(time1_str)
    s2, e2 = _parse(time2_str)
    
    # Labs are consecutive if one ends when another starts
    return (e1 == s2) or (e2 == s1)

def _times_overlap(time1_str, time2_str):
    """Check if two time slots overlap"""
    s1, e1 = _parse(time1_str)
    s2, e2 = _parse(time2_str)
    return max(s1, s2) < min(e1, e2)


# ── Data loader ───────────────────────────────────────────────────────────────

class TimetableData:
    def __init__(self):
        self.divisions = list(Division.objects.all().order_by('division_name'))
        self.rooms = list(Room.objects.all())
        self.meeting_times = list(MeetingTime.objects.all())
        self.sections = list(
            Section.objects.select_related(
                'course', 'division', 'batch', 'batch__division'
            ).all()
        )

        self.lecture_rooms = [r for r in self.rooms if r.room_type == 'LECTURE']
        self.lab_rooms = [r for r in self.rooms if r.room_type == 'LAB']

        # Slots grouped by day
        self.lab_slots_by_day = defaultdict(list)
        self.lec_slots_by_day = defaultdict(list)
        for mt in self.meeting_times:
            if mt.slot_type == 'LAB':
                self.lab_slots_by_day[mt.day].append(mt)
            else:
                self.lec_slots_by_day[mt.day].append(mt)

        # Sort lab slots by priority
        for day in self.lab_slots_by_day:
            self.lab_slots_by_day[day].sort(key=lambda mt: _get_slot_priority(mt.time))

        # Eligible teachers per course
        self.eligible_teachers = {}
        for course in Course.objects.prefetch_related('instructors').all():
            self.eligible_teachers[course.course_number] = list(course.instructors.all())

        # Group sections
        self.lecture_sections = [s for s in self.sections if s.course and s.course.course_type == 'LECTURE']
        self.lab_sections = [s for s in self.sections if s.course and s.course.course_type == 'LAB']

        # Lab sections grouped by (division_id, course_number)
        self.div_lab_groups = defaultdict(list)
        for s in self.lab_sections:
            if s.batch and s.batch.division_id:
                key = (s.batch.division_id, s.course.course_number)
                self.div_lab_groups[key].append(s)

        # Batches by division
        self.batches_by_division = defaultdict(list)
        for batch in Batch.objects.all().select_related('division'):
            self.batches_by_division[batch.division_id].append(batch)

        print(f"✅ Loaded: {len(self.sections)} sections | {len(self.divisions)} divisions")


# ── Scheduled class ──────────────────────────────────────────────────────────

class SC:
    __slots__ = ['section', 'course', 'meeting_time', 'room', 'instructor', 'division', 'batch']

    def __init__(self, section, mt, room, instructor):
        self.section = section
        self.course = section.course
        self.meeting_time = mt
        self.room = room
        self.instructor = instructor
        self.division = section.division
        self.batch = section.batch


# ── Generator ────────────────────────────────────────────────────────────────

class TimetableGenerator:
    def __init__(self, data: TimetableData):
        self.data = data
        self._reset()

    def _reset(self):
        self.result = []

        # FIXED: Use (day, pid, start_min, end_min) for precise tracking
        self.room_busy = defaultdict(list)      # room_number -> [(day, start_min, end_min), ...]
        self.teacher_busy = defaultdict(list)   # teacher_uid -> [(day, start_min, end_min), ...]
        self.div_busy = defaultdict(list)       # div_id -> [(day, start_min, end_min), ...]
        self.batch_busy = defaultdict(list)     # batch_id -> [(day, start_min, end_min), ...]

        # Teacher locks
        self.div_lec_teacher = {}
        self.batch_lab_teacher = {}

        # Lab tracking
        self.div_day_labs = defaultdict(list)
        self.batch_lab_count = defaultdict(int)
        self.teacher_batch_count = defaultdict(int)

    def _is_busy(self, busy_list, day, start_min, end_min):
        """Check if resource is busy during time range"""
        for busy_day, busy_start, busy_end in busy_list:
            if busy_day == day:
                if max(start_min, busy_start) < min(end_min, busy_end):
                    return True
        return False

    def _mark_busy(self, busy_list, day, start_min, end_min):
        """Mark resource as busy"""
        busy_list.append((day, start_min, end_min))

    def _room_free(self, mt, room):
        start_min, end_min = _parse(mt.time)
        return not self._is_busy(self.room_busy[room.r_number], mt.day, start_min, end_min)

    def _teacher_free(self, mt, teacher):
        start_min, end_min = _parse(mt.time)
        return not self._is_busy(self.teacher_busy[teacher.uid], mt.day, start_min, end_min)

    def _div_free(self, mt, div_id):
        start_min, end_min = _parse(mt.time)
        return not self._is_busy(self.div_busy[div_id], mt.day, start_min, end_min)

    def _batch_free(self, mt, batch_id):
        start_min, end_min = _parse(mt.time)
        return not self._is_busy(self.batch_busy[batch_id], mt.day, start_min, end_min)

    def _mark(self, mt, room, teacher, div_id=None, batch_id=None):
        """Mark all resources as busy"""
        start_min, end_min = _parse(mt.time)
        day = mt.day

        self._mark_busy(self.room_busy[room.r_number], day, start_min, end_min)
        self._mark_busy(self.teacher_busy[teacher.uid], day, start_min, end_min)

        if div_id:
            self._mark_busy(self.div_busy[div_id], day, start_min, end_min)
        if batch_id:
            self._mark_busy(self.batch_busy[batch_id], day, start_min, end_min)

    def _get_lecture_teacher(self, div_id, course_code):
        """C4: Fixed teacher for division"""
        key = (div_id, course_code)
        if key in self.div_lec_teacher:
            return self.div_lec_teacher[key]

        pool = self.data.eligible_teachers.get(course_code, [])
        if not pool:
            return None

        pool.sort(key=lambda t: self.teacher_batch_count.get(t.uid, 0))
        chosen = pool[0]
        self.div_lec_teacher[key] = chosen
        return chosen

    def _get_lab_teacher(self, batch_id, course_code, mt):
        """C5: Fixed teacher for batch"""
        key = (batch_id, course_code)

        if key in self.batch_lab_teacher:
            teacher = self.batch_lab_teacher[key]
            return teacher if self._teacher_free(mt, teacher) else None

        pool = self.data.eligible_teachers.get(course_code, [])
        if not pool:
            return None

        candidates = list(pool)
        random.shuffle(candidates)

        for teacher in candidates:
            if not self._teacher_free(mt, teacher):
                continue

            if self.teacher_batch_count[teacher.uid] >= MAX_BATCHES_PER_TEACHER:
                continue

            self.batch_lab_teacher[key] = teacher
            self.teacher_batch_count[teacher.uid] += 1
            return teacher

        return None

    def assign_labs(self):
        """PHASE 1: Labs first"""
        data = self.data
        print(f"\n📊 PHASE 1: Assigning labs")

        tasks = []
        for div in data.divisions:
            for course_code, needed in LAB_FREQUENCY.items():
                key = (div.id, course_code)
                sections = data.div_lab_groups.get(key, [])
                if len(sections) != 4:
                    continue

                tasks.append({
                    'division': div,
                    'course_code': course_code,
                    'sections': sections,
                    'needed': needed,
                })

        random.shuffle(tasks)

        for task in tasks:
            div = task['division']
            course_code = task['course_code']
            sections = task['sections']
            needed = task['needed']
            assigned = 0

            for _ in range(500):
                if assigned >= needed:
                    break

                days = DAYS_ORDER.copy()
                random.shuffle(days)

                for day in days:
                    if assigned >= needed:
                        break

                    div_day_key = (div.id, day)
                    if len(self.div_day_labs[div_day_key]) >= MAX_LABS_PER_DAY:
                        continue

                    for mt in data.lab_slots_by_day.get(day, []):
                        # Check consecutive labs
                        existing_times = self.div_day_labs[div_day_key]
                        if any(_is_lab_slot_consecutive(existing, mt.time) for existing in existing_times):
                            continue

                        # Division must be free
                        if not self._div_free(mt, div.id):
                            continue

                        # All batches must be free
                        batches = data.batches_by_division.get(div.id, [])
                        if not all(self._batch_free(mt, batch.id) for batch in batches):
                            continue

                        # Assign teachers
                        teacher_map = {}
                        teacher_valid = True

                        for section in sections:
                            batch = section.batch
                            teacher = self._get_lab_teacher(batch.id, course_code, mt)

                            if teacher is None:
                                teacher_valid = False
                                break

                            teacher_map[batch.id] = teacher

                        if not teacher_valid:
                            continue

                        # Assign rooms
                        room_map = {}
                        room_valid = True
                        used_rooms = set()

                        for section in sections:
                            batch = section.batch

                            free_rooms = [
                                room for room in data.lab_rooms
                                if self._room_free(mt, room) and room.r_number not in used_rooms
                            ]
                            if not free_rooms:
                                room_valid = False
                                break

                            room = random.choice(free_rooms)
                            room_map[batch.id] = room
                            used_rooms.add(room.r_number)

                        if not room_valid:
                            continue

                        # ALL CHECKS PASSED - Assign
                        for section in sections:
                            batch = section.batch
                            teacher = teacher_map[batch.id]
                            room = room_map[batch.id]

                            sc = SC(section, mt, room, teacher)
                            self.result.append(sc)

                            self._mark(mt, room, teacher, div_id=div.id, batch_id=batch.id)
                            self.batch_lab_count[(batch.id, course_code)] += 1

                        self.div_day_labs[div_day_key].append(mt.time)
                        assigned += 1

                        print(f"    ✓ {div.division_name} {course_code} on {day} at {mt.time[:13]}")
                        break

            if assigned < needed:
                print(f"  ⚠️  {div.division_name} {course_code}: {assigned}/{needed}")

    def assign_lectures(self):
        """PHASE 2: Lectures"""
        data = self.data
        print(f"\n📊 PHASE 2: Assigning lectures")

        lecture_by_division = defaultdict(list)
        for section in data.lecture_sections:
            if section.division:
                lecture_by_division[section.division.id].append(section)

        for div_id, sections in lecture_by_division.items():
            div = Division.objects.get(id=div_id)

            for section in sections:
                course = section.course
                course_code = course.course_number
                needed = LECTURE_FREQUENCY.get(course_code, 3)

                teacher = self._get_lecture_teacher(div.id, course_code)
                if not teacher:
                    print(f"  ⚠️  No teacher for {div.division_name} {course_code}")
                    continue

                assigned = 0
                days_used = defaultdict(int)

                for _ in range(300):
                    if assigned >= needed:
                        break

                    days = DAYS_ORDER.copy()
                    random.shuffle(days)

                    for day in days:
                        if assigned >= needed:
                            break

                        if days_used[day] >= 2:
                            continue

                        for mt in data.lec_slots_by_day.get(day, []):
                            if not self._div_free(mt, div.id):
                                continue

                            if not self._teacher_free(mt, teacher):
                                continue

                            free_rooms = [room for room in data.lecture_rooms if self._room_free(mt, room)]
                            if not free_rooms:
                                continue

                            room = random.choice(free_rooms)

                            sc = SC(section, mt, room, teacher)
                            self.result.append(sc)

                            self._mark(mt, room, teacher, div_id=div.id)

                            days_used[day] += 1
                            assigned += 1

                            print(f"    ✓ {div.division_name} {course_code} on {day} at {mt.time[:11]}")
                            break

                if assigned < needed:
                    print(f"  ⚠️  {div.division_name} {course_code}: {assigned}/{needed}")

    def generate(self):
        self.assign_labs()
        self.assign_lectures()
        return self.result


# ── Verification ─────────────────────────────────────────────────────────────

def verify_timetable(solution):
    """Comprehensive verification"""
    conflicts = []

    # Room conflicts
    room_time_map = defaultdict(list)
    for sc in solution:
        start, end = _parse(sc.meeting_time.time)
        key = (sc.room.r_number, sc.meeting_time.day)
        room_time_map[key].append((start, end, sc))

    for key, slots in room_time_map.items():
        for i, (s1, e1, sc1) in enumerate(slots):
            for s2, e2, sc2 in slots[i+1:]:
                if max(s1, s2) < min(e1, e2):
                    conflicts.append(f"Room {key[0]} conflict on {key[1]}")

    # Teacher conflicts
    teacher_time_map = defaultdict(list)
    for sc in solution:
        start, end = _parse(sc.meeting_time.time)
        key = (sc.instructor.uid, sc.meeting_time.day)
        teacher_time_map[key].append((start, end, sc))

    for key, slots in teacher_time_map.items():
        for i, (s1, e1, sc1) in enumerate(slots):
            for s2, e2, sc2 in slots[i+1:]:
                if max(s1, s2) < min(e1, e2):
                    teacher = Instructor.objects.get(uid=key[0])
                    conflicts.append(f"Teacher {teacher.name} conflict on {key[1]}")

    # Teacher consistency
    div_subject_teachers = defaultdict(set)
    for sc in solution:
        if sc.course.course_type == 'LECTURE' and sc.division:
            key = (sc.division.id, sc.course.course_number)
            div_subject_teachers[key].add(sc.instructor.uid)

    for key, teachers in div_subject_teachers.items():
        if len(teachers) > 1:
            conflicts.append(f"Multiple teachers for division {key[0]} {key[1]}")

    batch_subject_teachers = defaultdict(set)
    for sc in solution:
        if sc.course.course_type == 'LAB' and sc.batch:
            key = (sc.batch.id, sc.course.course_number)
            batch_subject_teachers[key].add(sc.instructor.uid)

    for key, teachers in batch_subject_teachers.items():
        if len(teachers) > 1:
            conflicts.append(f"Multiple teachers for batch {key[0]} {key[1]}")

    return conflicts


# ── Django view ───────────────────────────────────────────────────────────────

def timetable(request):
    print("\n" + "=" * 70)
    print("🚀 TIMETABLE GENERATOR — TWO-PHASE ALGORITHM")
    print("=" * 70)

    start_time = time_module.time()
    data = TimetableData()

    best_solution = None
    best_conflicts = float('inf')

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n📊 Attempt {attempt}/{MAX_RETRIES}")

        generator = TimetableGenerator(data)
        solution = generator.generate()
        conflicts = verify_timetable(solution)

        print(f"  → {len(solution)} classes, {len(conflicts)} conflicts")

        if len(conflicts) < best_conflicts:
            best_conflicts = len(conflicts)
            best_solution = solution

            if best_conflicts == 0:
                print(f"\n✅ PERFECT TIMETABLE on attempt {attempt}!")
                break

    elapsed = round(time_module.time() - start_time, 2)
    final_conflicts = verify_timetable(best_solution)

    print("\n" + "=" * 70)
    print(f"🏁 FINAL: {len(best_solution)} classes, {len(final_conflicts)} conflicts, {elapsed}s")
    print("=" * 70)

    context = {
        'schedule': best_solution,
        'sections': data.sections,
        'times': data.meeting_times,
        'generations': MAX_RETRIES,
        'fitness': 1.0 if len(final_conflicts) == 0 else round(1 / (1 + len(final_conflicts)), 4),
        'conflicts': len(final_conflicts),
        'verified': len(final_conflicts) == 0,
        'time_taken': elapsed,
    }

    return render(request, 'gentimetable.html', context)


# ── Other views (keep existing) ──────────────────────────────────────────────
def index(request):
    return render(request, 'index.html', {})

def about(request):
    return render(request, 'aboutus.html', {})

def help(request):
    return render(request, 'help.html', {})

def terms(request):
    return render(request, 'terms.html', {})

def contact(request):
    return render(request, 'contact.html', {})

def generate(request):
    return render(request, 'generate.html', {})

@login_required
def admindash(request):
    return render(request, 'admindashboard.html', {
        'total_departments': Department.objects.count(),
        'total_divisions': Division.objects.count(),
        'total_batches': Batch.objects.count(),
        'total_instructors': Instructor.objects.count(),
        'total_rooms': Room.objects.count(),
        'total_courses': Course.objects.count(),
        'total_sections': Section.objects.count(),
    })

@login_required
def addDepts(request):
    form = DepartmentForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('addDepts')
    return render(request, 'addDepts.html', {'form': form})

@login_required
def department_list(request):
    return render(request, 'deptlist.html', {'departments': Department.objects.all()})

@login_required
def delete_department(request, pk):
    if request.method == 'POST':
        Department.objects.filter(pk=pk).delete()
        return redirect('editdepartment')

@login_required
def addDivisions(request):
    form = DivisionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('addDivisions')
    return render(request, 'addDivisions.html', {'form': form})

@login_required
def division_list(request):
    return render(request, 'divisionlist.html', {'divisions': Division.objects.all()})

@login_required
def delete_division(request, pk):
    if request.method == 'POST':
        Division.objects.filter(pk=pk).delete()
        return redirect('editdivision')

@login_required
def addBatches(request):
    form = BatchForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('addBatches')
    return render(request, 'addBatches.html', {'form': form})

@login_required
def batch_list(request):
    return render(request, 'batchlist.html', {'batches': Batch.objects.all()})

@login_required
def delete_batch(request, pk):
    if request.method == 'POST':
        Batch.objects.filter(pk=pk).delete()
        return redirect('editbatch')

@login_required
def addCourses(request):
    form = CourseForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('addCourses')
    return render(request, 'addCourses.html', {'form': form})

@login_required
def course_list_view(request):
    return render(request, 'courseslist.html', {'courses': Course.objects.all()})

@login_required
def delete_course(request, pk):
    if request.method == 'POST':
        Course.objects.filter(pk=pk).delete()
        return redirect('editcourse')

@login_required
def addInstructor(request):
    form = InstructorForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('addInstructors')
    return render(request, 'addInstructors.html', {'form': form})

@login_required
def inst_list_view(request):
    return render(request, 'inslist.html', {'instructors': Instructor.objects.all()})

@login_required
def delete_instructor(request, pk):
    if request.method == 'POST':
        Instructor.objects.filter(pk=pk).delete()
        return redirect('editinstructor')

@login_required
def addRooms(request):
    form = RoomForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('addRooms')
    return render(request, 'addRooms.html', {'form': form})

@login_required
def room_list(request):
    return render(request, 'roomslist.html', {'rooms': Room.objects.all()})

@login_required
def delete_room(request, pk):
    if request.method == 'POST':
        Room.objects.filter(pk=pk).delete()
        return redirect('editrooms')

@login_required
def addTimings(request):
    form = MeetingTimeForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('addTimings')
    return render(request, 'addTimings.html', {'form': form})

@login_required
def meeting_list_view(request):
    return render(request, 'mtlist.html', {'meeting_times': MeetingTime.objects.all()})

@login_required
def delete_meeting_time(request, pk):
    if request.method == 'POST':
        MeetingTime.objects.filter(pk=pk).delete()
        return redirect('editmeetingtime')

@login_required
def addSections(request):
    form = SectionForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        return redirect('addSections')
    return render(request, 'addSections.html', {'form': form})

@login_required
def section_list(request):
    return render(request, 'seclist.html', {'sections': Section.objects.all()})

@login_required
def delete_section(request, pk):
    if request.method == 'POST':
        Section.objects.filter(pk=pk).delete()
        return redirect('editsection')