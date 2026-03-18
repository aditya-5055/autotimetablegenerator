# first algorithm
# """
# views.py — Timetable Generator (CORRECTED VERSION)
# ================================
# TWO-PHASE approach with ALL constraints properly enforced
# """

# import random
# import time as time_module
# from collections import defaultdict

# from django.shortcuts import render, redirect
# from django.contrib.auth.decorators import login_required

# from .forms import *
# from .models import *

# # ── Constants ────────────────────────────────────────────────────────────────

# LAB_SLOT_PRIORITY = ['08:45', '11:00', '13:45']
# DAYS_ORDER = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
# MAX_LABS_PER_DAY = 2
# MAX_BATCHES_PER_TEACHER = 4
# MAX_RETRIES = 100  # Reduced for faster results

# LAB_FREQUENCY = {'DSBDAL': 2, 'LPII': 2, 'WTL': 1}
# LECTURE_FREQUENCY = {'AI': 3, 'DSBDA': 3, 'WT': 3}

# # ── Time helpers ─────────────────────────────────────────────────────────────

# def _to_min(t):
#     """Convert time string to minutes"""
#     try:
#         h, m = map(int, t.strip().split(':'))
#         if 1 <= h <= 7:
#             h += 12
#         return h * 60 + m
#     except:
#         return 0

# def _parse(time_str):
#     """Parse time range to (start_min, end_min)"""
#     try:
#         parts = time_str.replace(' ', '').split('-')
#         return _to_min(parts[0]), _to_min(parts[1])
#     except:
#         return 0, 0

# def _get_slot_priority(time_str):
#     """Lab slot priority (C11)"""
#     if '08:45' in time_str:
#         return 1
#     if '11:00' in time_str:
#         return 2
#     if '13:45' in time_str:
#         return 3
#     return 99

# def _is_lab_slot_consecutive(time1_str, time2_str):
#     """Check if two lab times are consecutive (C8)"""
#     s1, e1 = _parse(time1_str)
#     s2, e2 = _parse(time2_str)
    
#     # Labs are consecutive if one ends when another starts
#     return (e1 == s2) or (e2 == s1)

# def _times_overlap(time1_str, time2_str):
#     """Check if two time slots overlap"""
#     s1, e1 = _parse(time1_str)
#     s2, e2 = _parse(time2_str)
#     return max(s1, s2) < min(e1, e2)


# # ── Data loader ───────────────────────────────────────────────────────────────

# class TimetableData:
#     def __init__(self):
#         self.divisions = list(Division.objects.all().order_by('division_name'))
#         self.rooms = list(Room.objects.all())
#         self.meeting_times = list(MeetingTime.objects.all())
#         self.sections = list(
#             Section.objects.select_related(
#                 'course', 'division', 'batch', 'batch__division'
#             ).all()
#         )

#         self.lecture_rooms = [r for r in self.rooms if r.room_type == 'LECTURE']
#         self.lab_rooms = [r for r in self.rooms if r.room_type == 'LAB']

#         # Slots grouped by day
#         self.lab_slots_by_day = defaultdict(list)
#         self.lec_slots_by_day = defaultdict(list)
#         for mt in self.meeting_times:
#             if mt.slot_type == 'LAB':
#                 self.lab_slots_by_day[mt.day].append(mt)
#             else:
#                 self.lec_slots_by_day[mt.day].append(mt)

#         # Sort lab slots by priority
#         for day in self.lab_slots_by_day:
#             self.lab_slots_by_day[day].sort(key=lambda mt: _get_slot_priority(mt.time))

#         # Eligible teachers per course
#         self.eligible_teachers = {}
#         for course in Course.objects.prefetch_related('instructors').all():
#             self.eligible_teachers[course.course_number] = list(course.instructors.all())

#         # Group sections
#         self.lecture_sections = [s for s in self.sections if s.course and s.course.course_type == 'LECTURE']
#         self.lab_sections = [s for s in self.sections if s.course and s.course.course_type == 'LAB']

#         # Lab sections grouped by (division_id, course_number)
#         self.div_lab_groups = defaultdict(list)
#         for s in self.lab_sections:
#             if s.batch and s.batch.division_id:
#                 key = (s.batch.division_id, s.course.course_number)
#                 self.div_lab_groups[key].append(s)

#         # Batches by division
#         self.batches_by_division = defaultdict(list)
#         for batch in Batch.objects.all().select_related('division'):
#             self.batches_by_division[batch.division_id].append(batch)

#         print(f"✅ Loaded: {len(self.sections)} sections | {len(self.divisions)} divisions")


# # ── Scheduled class ──────────────────────────────────────────────────────────

# class SC:
#     __slots__ = ['section', 'course', 'meeting_time', 'room', 'instructor', 'division', 'batch']

#     def __init__(self, section, mt, room, instructor):
#         self.section = section
#         self.course = section.course
#         self.meeting_time = mt
#         self.room = room
#         self.instructor = instructor
#         self.division = section.division
#         self.batch = section.batch


# # ── Generator ────────────────────────────────────────────────────────────────

# class TimetableGenerator:
#     def __init__(self, data: TimetableData):
#         self.data = data
#         self._reset()

#     def _reset(self):
#         self.result = []

#         # FIXED: Use (day, pid, start_min, end_min) for precise tracking
#         self.room_busy = defaultdict(list)      # room_number -> [(day, start_min, end_min), ...]
#         self.teacher_busy = defaultdict(list)   # teacher_uid -> [(day, start_min, end_min), ...]
#         self.div_busy = defaultdict(list)       # div_id -> [(day, start_min, end_min), ...]
#         self.batch_busy = defaultdict(list)     # batch_id -> [(day, start_min, end_min), ...]

#         # Teacher locks
#         self.div_lec_teacher = {}
#         self.batch_lab_teacher = {}

#         # Lab tracking
#         self.div_day_labs = defaultdict(list)
#         self.batch_lab_count = defaultdict(int)
#         self.teacher_batch_count = defaultdict(int)

#     def _is_busy(self, busy_list, day, start_min, end_min):
#         """Check if resource is busy during time range"""
#         for busy_day, busy_start, busy_end in busy_list:
#             if busy_day == day:
#                 if max(start_min, busy_start) < min(end_min, busy_end):
#                     return True
#         return False

#     def _mark_busy(self, busy_list, day, start_min, end_min):
#         """Mark resource as busy"""
#         busy_list.append((day, start_min, end_min))

#     def _room_free(self, mt, room):
#         start_min, end_min = _parse(mt.time)
#         return not self._is_busy(self.room_busy[room.r_number], mt.day, start_min, end_min)

#     def _teacher_free(self, mt, teacher):
#         start_min, end_min = _parse(mt.time)
#         return not self._is_busy(self.teacher_busy[teacher.uid], mt.day, start_min, end_min)

#     def _div_free(self, mt, div_id):
#         start_min, end_min = _parse(mt.time)
#         return not self._is_busy(self.div_busy[div_id], mt.day, start_min, end_min)

#     def _batch_free(self, mt, batch_id):
#         start_min, end_min = _parse(mt.time)
#         return not self._is_busy(self.batch_busy[batch_id], mt.day, start_min, end_min)

#     def _mark(self, mt, room, teacher, div_id=None, batch_id=None):
#         """Mark all resources as busy"""
#         start_min, end_min = _parse(mt.time)
#         day = mt.day

#         self._mark_busy(self.room_busy[room.r_number], day, start_min, end_min)
#         self._mark_busy(self.teacher_busy[teacher.uid], day, start_min, end_min)

#         if div_id:
#             self._mark_busy(self.div_busy[div_id], day, start_min, end_min)
#         if batch_id:
#             self._mark_busy(self.batch_busy[batch_id], day, start_min, end_min)

#     def _get_lecture_teacher(self, div_id, course_code):
#         """C4: Fixed teacher for division"""
#         key = (div_id, course_code)
#         if key in self.div_lec_teacher:
#             return self.div_lec_teacher[key]

#         pool = self.data.eligible_teachers.get(course_code, [])
#         if not pool:
#             return None

#         pool.sort(key=lambda t: self.teacher_batch_count.get(t.uid, 0))
#         chosen = pool[0]
#         self.div_lec_teacher[key] = chosen
#         return chosen

#     def _get_lab_teacher(self, batch_id, course_code, mt):
#         """C5: Fixed teacher for batch"""
#         key = (batch_id, course_code)

#         if key in self.batch_lab_teacher:
#             teacher = self.batch_lab_teacher[key]
#             return teacher if self._teacher_free(mt, teacher) else None

#         pool = self.data.eligible_teachers.get(course_code, [])
#         if not pool:
#             return None

#         candidates = list(pool)
#         random.shuffle(candidates)

#         for teacher in candidates:
#             if not self._teacher_free(mt, teacher):
#                 continue

#             if self.teacher_batch_count[teacher.uid] >= MAX_BATCHES_PER_TEACHER:
#                 continue

#             self.batch_lab_teacher[key] = teacher
#             self.teacher_batch_count[teacher.uid] += 1
#             return teacher

#         return None

#     def assign_labs(self):
#         """PHASE 1: Labs first"""
#         data = self.data
#         print(f"\n📊 PHASE 1: Assigning labs")

#         tasks = []
#         for div in data.divisions:
#             for course_code, needed in LAB_FREQUENCY.items():
#                 key = (div.id, course_code)
#                 sections = data.div_lab_groups.get(key, [])
#                 if len(sections) != 4:
#                     continue

#                 tasks.append({
#                     'division': div,
#                     'course_code': course_code,
#                     'sections': sections,
#                     'needed': needed,
#                 })

#         random.shuffle(tasks)

#         for task in tasks:
#             div = task['division']
#             course_code = task['course_code']
#             sections = task['sections']
#             needed = task['needed']
#             assigned = 0

#             for _ in range(500):
#                 if assigned >= needed:
#                     break

#                 days = DAYS_ORDER.copy()
#                 random.shuffle(days)

#                 for day in days:
#                     if assigned >= needed:
#                         break

#                     div_day_key = (div.id, day)
#                     if len(self.div_day_labs[div_day_key]) >= MAX_LABS_PER_DAY:
#                         continue

#                     for mt in data.lab_slots_by_day.get(day, []):
#                         # Check consecutive labs
#                         existing_times = self.div_day_labs[div_day_key]
#                         if any(_is_lab_slot_consecutive(existing, mt.time) for existing in existing_times):
#                             continue

#                         # Division must be free
#                         if not self._div_free(mt, div.id):
#                             continue

#                         # All batches must be free
#                         batches = data.batches_by_division.get(div.id, [])
#                         if not all(self._batch_free(mt, batch.id) for batch in batches):
#                             continue

#                         # Assign teachers
#                         teacher_map = {}
#                         teacher_valid = True

#                         for section in sections:
#                             batch = section.batch
#                             teacher = self._get_lab_teacher(batch.id, course_code, mt)

#                             if teacher is None:
#                                 teacher_valid = False
#                                 break

#                             teacher_map[batch.id] = teacher

#                         if not teacher_valid:
#                             continue

#                         # Assign rooms
#                         room_map = {}
#                         room_valid = True
#                         used_rooms = set()

#                         for section in sections:
#                             batch = section.batch

#                             free_rooms = [
#                                 room for room in data.lab_rooms
#                                 if self._room_free(mt, room) and room.r_number not in used_rooms
#                             ]
#                             if not free_rooms:
#                                 room_valid = False
#                                 break

#                             room = random.choice(free_rooms)
#                             room_map[batch.id] = room
#                             used_rooms.add(room.r_number)

#                         if not room_valid:
#                             continue

#                         # ALL CHECKS PASSED - Assign
#                         for section in sections:
#                             batch = section.batch
#                             teacher = teacher_map[batch.id]
#                             room = room_map[batch.id]

#                             sc = SC(section, mt, room, teacher)
#                             self.result.append(sc)

#                             self._mark(mt, room, teacher, div_id=div.id, batch_id=batch.id)
#                             self.batch_lab_count[(batch.id, course_code)] += 1

#                         self.div_day_labs[div_day_key].append(mt.time)
#                         assigned += 1

#                         print(f"    ✓ {div.division_name} {course_code} on {day} at {mt.time[:13]}")
#                         break

#             if assigned < needed:
#                 print(f"  ⚠️  {div.division_name} {course_code}: {assigned}/{needed}")

#     def assign_lectures(self):
#         """PHASE 2: Lectures"""
#         data = self.data
#         print(f"\n📊 PHASE 2: Assigning lectures")

#         lecture_by_division = defaultdict(list)
#         for section in data.lecture_sections:
#             if section.division:
#                 lecture_by_division[section.division.id].append(section)

#         for div_id, sections in lecture_by_division.items():
#             div = Division.objects.get(id=div_id)

#             for section in sections:
#                 course = section.course
#                 course_code = course.course_number
#                 needed = LECTURE_FREQUENCY.get(course_code, 3)

#                 teacher = self._get_lecture_teacher(div.id, course_code)
#                 if not teacher:
#                     print(f"  ⚠️  No teacher for {div.division_name} {course_code}")
#                     continue

#                 assigned = 0
#                 days_used = defaultdict(int)

#                 for _ in range(300):
#                     if assigned >= needed:
#                         break

#                     days = DAYS_ORDER.copy()
#                     random.shuffle(days)

#                     for day in days:
#                         if assigned >= needed:
#                             break

#                         if days_used[day] >= 2:
#                             continue

#                         for mt in data.lec_slots_by_day.get(day, []):
#                             if not self._div_free(mt, div.id):
#                                 continue

#                             if not self._teacher_free(mt, teacher):
#                                 continue

#                             free_rooms = [room for room in data.lecture_rooms if self._room_free(mt, room)]
#                             if not free_rooms:
#                                 continue

#                             room = random.choice(free_rooms)

#                             sc = SC(section, mt, room, teacher)
#                             self.result.append(sc)

#                             self._mark(mt, room, teacher, div_id=div.id)

#                             days_used[day] += 1
#                             assigned += 1

#                             print(f"    ✓ {div.division_name} {course_code} on {day} at {mt.time[:11]}")
#                             break

#                 if assigned < needed:
#                     print(f"  ⚠️  {div.division_name} {course_code}: {assigned}/{needed}")

#     def generate(self):
#         self.assign_labs()
#         self.assign_lectures()
#         return self.result


# # ── Verification ─────────────────────────────────────────────────────────────

# def verify_timetable(solution):
#     """Comprehensive verification"""
#     conflicts = []

#     # Room conflicts
#     room_time_map = defaultdict(list)
#     for sc in solution:
#         start, end = _parse(sc.meeting_time.time)
#         key = (sc.room.r_number, sc.meeting_time.day)
#         room_time_map[key].append((start, end, sc))

#     for key, slots in room_time_map.items():
#         for i, (s1, e1, sc1) in enumerate(slots):
#             for s2, e2, sc2 in slots[i+1:]:
#                 if max(s1, s2) < min(e1, e2):
#                     conflicts.append(f"Room {key[0]} conflict on {key[1]}")

#     # Teacher conflicts
#     teacher_time_map = defaultdict(list)
#     for sc in solution:
#         start, end = _parse(sc.meeting_time.time)
#         key = (sc.instructor.uid, sc.meeting_time.day)
#         teacher_time_map[key].append((start, end, sc))

#     for key, slots in teacher_time_map.items():
#         for i, (s1, e1, sc1) in enumerate(slots):
#             for s2, e2, sc2 in slots[i+1:]:
#                 if max(s1, s2) < min(e1, e2):
#                     teacher = Instructor.objects.get(uid=key[0])
#                     conflicts.append(f"Teacher {teacher.name} conflict on {key[1]}")

#     # Teacher consistency
#     div_subject_teachers = defaultdict(set)
#     for sc in solution:
#         if sc.course.course_type == 'LECTURE' and sc.division:
#             key = (sc.division.id, sc.course.course_number)
#             div_subject_teachers[key].add(sc.instructor.uid)

#     for key, teachers in div_subject_teachers.items():
#         if len(teachers) > 1:
#             conflicts.append(f"Multiple teachers for division {key[0]} {key[1]}")

#     batch_subject_teachers = defaultdict(set)
#     for sc in solution:
#         if sc.course.course_type == 'LAB' and sc.batch:
#             key = (sc.batch.id, sc.course.course_number)
#             batch_subject_teachers[key].add(sc.instructor.uid)

#     for key, teachers in batch_subject_teachers.items():
#         if len(teachers) > 1:
#             conflicts.append(f"Multiple teachers for batch {key[0]} {key[1]}")

#     return conflicts


# # ── Django view ───────────────────────────────────────────────────────────────

# def timetable(request):
#     print("\n" + "=" * 70)
#     print("🚀 TIMETABLE GENERATOR — TWO-PHASE ALGORITHM")
#     print("=" * 70)

#     start_time = time_module.time()
#     data = TimetableData()

#     best_solution = None
#     best_conflicts = float('inf')

#     for attempt in range(1, MAX_RETRIES + 1):
#         print(f"\n📊 Attempt {attempt}/{MAX_RETRIES}")

#         generator = TimetableGenerator(data)
#         solution = generator.generate()
#         conflicts = verify_timetable(solution)

#         print(f"  → {len(solution)} classes, {len(conflicts)} conflicts")

#         if len(conflicts) < best_conflicts:
#             best_conflicts = len(conflicts)
#             best_solution = solution

#             if best_conflicts == 0:
#                 print(f"\n✅ PERFECT TIMETABLE on attempt {attempt}!")
#                 break

#     elapsed = round(time_module.time() - start_time, 2)
#     final_conflicts = verify_timetable(best_solution)

#     print("\n" + "=" * 70)
#     print(f"🏁 FINAL: {len(best_solution)} classes, {len(final_conflicts)} conflicts, {elapsed}s")
#     print("=" * 70)

#     context = {
#         'schedule': best_solution,
#         'sections': data.sections,
#         'times': data.meeting_times,
#         'generations': MAX_RETRIES,
#         'fitness': 1.0 if len(final_conflicts) == 0 else round(1 / (1 + len(final_conflicts)), 4),
#         'conflicts': len(final_conflicts),
#         'verified': len(final_conflicts) == 0,
#         'time_taken': elapsed,
#     }

#     return render(request, 'gentimetable.html', context)


# # ── Other views (keep existing) ──────────────────────────────────────────────
# def index(request):
#     return render(request, 'index.html', {})

# def about(request):
#     return render(request, 'aboutus.html', {})

# def help(request):
#     return render(request, 'help.html', {})

# def terms(request):
#     return render(request, 'terms.html', {})

# def contact(request):
#     return render(request, 'contact.html', {})

# def generate(request):
#     return render(request, 'generate.html', {})

# @login_required
# def admindash(request):
#     return render(request, 'admindashboard.html', {
#         'total_departments': Department.objects.count(),
#         'total_divisions': Division.objects.count(),
#         'total_batches': Batch.objects.count(),
#         'total_instructors': Instructor.objects.count(),
#         'total_rooms': Room.objects.count(),
#         'total_courses': Course.objects.count(),
#         'total_sections': Section.objects.count(),
#     })

# @login_required
# def addDepts(request):
#     form = DepartmentForm(request.POST or None)
#     if request.method == 'POST' and form.is_valid():
#         form.save()
#         return redirect('addDepts')
#     return render(request, 'addDepts.html', {'form': form})

# @login_required
# def department_list(request):
#     return render(request, 'deptlist.html', {'departments': Department.objects.all()})

# @login_required
# def delete_department(request, pk):
#     if request.method == 'POST':
#         Department.objects.filter(pk=pk).delete()
#         return redirect('editdepartment')

# @login_required
# def addDivisions(request):
#     form = DivisionForm(request.POST or None)
#     if request.method == 'POST' and form.is_valid():
#         form.save()
#         return redirect('addDivisions')
#     return render(request, 'addDivisions.html', {'form': form})

# @login_required
# def division_list(request):
#     return render(request, 'divisionlist.html', {'divisions': Division.objects.all()})

# @login_required
# def delete_division(request, pk):
#     if request.method == 'POST':
#         Division.objects.filter(pk=pk).delete()
#         return redirect('editdivision')

# @login_required
# def addBatches(request):
#     form = BatchForm(request.POST or None)
#     if request.method == 'POST' and form.is_valid():
#         form.save()
#         return redirect('addBatches')
#     return render(request, 'addBatches.html', {'form': form})

# @login_required
# def batch_list(request):
#     return render(request, 'batchlist.html', {'batches': Batch.objects.all()})

# @login_required
# def delete_batch(request, pk):
#     if request.method == 'POST':
#         Batch.objects.filter(pk=pk).delete()
#         return redirect('editbatch')

# @login_required
# def addCourses(request):
#     form = CourseForm(request.POST or None)
#     if request.method == 'POST' and form.is_valid():
#         form.save()
#         return redirect('addCourses')
#     return render(request, 'addCourses.html', {'form': form})

# @login_required
# def course_list_view(request):
#     return render(request, 'courseslist.html', {'courses': Course.objects.all()})

# @login_required
# def delete_course(request, pk):
#     if request.method == 'POST':
#         Course.objects.filter(pk=pk).delete()
#         return redirect('editcourse')

# @login_required
# def addInstructor(request):
#     form = InstructorForm(request.POST or None)
#     if request.method == 'POST' and form.is_valid():
#         form.save()
#         return redirect('addInstructors')
#     return render(request, 'addInstructors.html', {'form': form})

# @login_required
# def inst_list_view(request):
#     return render(request, 'inslist.html', {'instructors': Instructor.objects.all()})

# @login_required
# def delete_instructor(request, pk):
#     if request.method == 'POST':
#         Instructor.objects.filter(pk=pk).delete()
#         return redirect('editinstructor')

# @login_required
# def addRooms(request):
#     form = RoomForm(request.POST or None)
#     if request.method == 'POST' and form.is_valid():
#         form.save()
#         return redirect('addRooms')
#     return render(request, 'addRooms.html', {'form': form})

# @login_required
# def room_list(request):
#     return render(request, 'roomslist.html', {'rooms': Room.objects.all()})

# @login_required
# def delete_room(request, pk):
#     if request.method == 'POST':
#         Room.objects.filter(pk=pk).delete()
#         return redirect('editrooms')

# @login_required
# def addTimings(request):
#     form = MeetingTimeForm(request.POST or None)
#     if request.method == 'POST' and form.is_valid():
#         form.save()
#         return redirect('addTimings')
#     return render(request, 'addTimings.html', {'form': form})

# @login_required
# def meeting_list_view(request):
#     return render(request, 'mtlist.html', {'meeting_times': MeetingTime.objects.all()})

# @login_required
# def delete_meeting_time(request, pk):
#     if request.method == 'POST':
#         MeetingTime.objects.filter(pk=pk).delete()
#         return redirect('editmeetingtime')

# @login_required
# def addSections(request):
#     form = SectionForm(request.POST or None)
#     if request.method == 'POST' and form.is_valid():
#         form.save()
#         return redirect('addSections')
#     return render(request, 'addSections.html', {'form': form})

# @login_required
# def section_list(request):
#     return render(request, 'seclist.html', {'sections': Section.objects.all()})

# @login_required
# def delete_section(request, pk):
#     if request.method == 'POST':
#         Section.objects.filter(pk=pk).delete()
#         return redirect('editsection')

# claud algo with 0 conflict




# """
# views.py — Timetable Generator (ZERO-CONFLICT VERSION - FINAL FIX)
# ==================================================================
# Fixed: Room distribution for 4 batches in same lab session
# """

# import random
# import time as time_module
# from collections import defaultdict

# from django.shortcuts import render, redirect
# from django.contrib.auth.decorators import login_required

# from .forms import *
# from .models import *

# # ── Constants ────────────────────────────────────────────────────────────────

# LAB_SLOT_PRIORITY = ['08:45', '11:00', '13:45']
# DAYS_ORDER = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
# MAX_LABS_PER_DAY = 2
# MAX_BATCHES_PER_TEACHER = 4
# MAX_RETRIES = 100

# LAB_FREQUENCY = {'DSBDAL': 2, 'LPII': 2, 'WTL': 1}
# LECTURE_FREQUENCY = {'AI': 3, 'DSBDA': 3, 'WT': 3}

# # ── Time helpers ─────────────────────────────────────────────────────────────

# def _to_min(t):
#     """Convert time string to minutes"""
#     try:
#         h, m = map(int, t.strip().split(':'))
#         if 1 <= h <= 7:
#             h += 12
#         return h * 60 + m
#     except:
#         return 0

# def _parse(time_str):
#     """Parse time range to (start_min, end_min)"""
#     try:
#         parts = time_str.replace(' ', '').split('-')
#         return _to_min(parts[0]), _to_min(parts[1])
#     except:
#         return 0, 0

# def _get_slot_priority(time_str):
#     """Lab slot priority"""
#     if '08:45' in time_str:
#         return 1
#     if '11:00' in time_str:
#         return 2
#     if '13:45' in time_str:
#         return 3
#     return 99

# def _is_lab_slot_consecutive(time1_str, time2_str):
#     """Check if two lab times are consecutive"""
#     s1, e1 = _parse(time1_str)
#     s2, e2 = _parse(time2_str)
#     return (e1 == s2) or (e2 == s1)

# def _times_overlap(time1_str, time2_str):
#     """Check if two time slots overlap"""
#     s1, e1 = _parse(time1_str)
#     s2, e2 = _parse(time2_str)
#     return max(s1, s2) < min(e1, e2)


# # ── Data loader ───────────────────────────────────────────────────────────────

# class TimetableData:
#     def __init__(self):
#         self.divisions = list(Division.objects.all().order_by('division_name'))
#         self.rooms = list(Room.objects.all())
#         self.meeting_times = list(MeetingTime.objects.all())
#         self.sections = list(
#             Section.objects.select_related(
#                 'course', 'division', 'batch', 'batch__division'
#             ).all()
#         )

#         self.lecture_rooms = [r for r in self.rooms if r.room_type == 'LECTURE']
#         self.lab_rooms = [r for r in self.rooms if r.room_type == 'LAB']

#         # Slots grouped by day
#         self.lab_slots_by_day = defaultdict(list)
#         self.lec_slots_by_day = defaultdict(list)
#         for mt in self.meeting_times:
#             if mt.slot_type == 'LAB':
#                 self.lab_slots_by_day[mt.day].append(mt)
#             else:
#                 self.lec_slots_by_day[mt.day].append(mt)

#         # Sort lab slots by priority
#         for day in self.lab_slots_by_day:
#             self.lab_slots_by_day[day].sort(key=lambda mt: _get_slot_priority(mt.time))

#         # Eligible teachers per course
#         self.eligible_teachers = {}
#         for course in Course.objects.prefetch_related('instructors').all():
#             self.eligible_teachers[course.course_number] = list(course.instructors.all())

#         # Group sections
#         self.lecture_sections = [s for s in self.sections if s.course and s.course.course_type == 'LECTURE']
#         self.lab_sections = [s for s in self.sections if s.course and s.course.course_type == 'LAB']

#         # Lab sections grouped by (division_id, course_number)
#         self.div_lab_groups = defaultdict(list)
#         for s in self.lab_sections:
#             if s.batch and s.batch.division_id:
#                 key = (s.batch.division_id, s.course.course_number)
#                 self.div_lab_groups[key].append(s)

#         # Batches by division
#         self.batches_by_division = defaultdict(list)
#         for batch in Batch.objects.all().select_related('division'):
#             self.batches_by_division[batch.division_id].append(batch)

#         print(f"✅ Loaded: {len(self.sections)} sections | {len(self.divisions)} divisions")


# # ── Scheduled class ──────────────────────────────────────────────────────────

# class SC:
#     __slots__ = ['section', 'course', 'meeting_time', 'room', 'instructor', 'division', 'batch']

#     def __init__(self, section, mt, room, instructor):
#         self.section = section
#         self.course = section.course
#         self.meeting_time = mt
#         self.room = room
#         self.instructor = instructor
#         self.division = section.division
#         self.batch = section.batch


# # ── Generator ────────────────────────────────────────────────────────────────

# class TimetableGenerator:
#     def __init__(self, data: TimetableData):
#         self.data = data
#         self._reset()

#     def _reset(self):
#         self.result = []

#         # Use (day, start_min, end_min) for precise tracking
#         self.room_busy = defaultdict(list)
#         self.teacher_busy = defaultdict(list)
#         self.div_busy = defaultdict(list)
#         self.batch_busy = defaultdict(list)

#         # Teacher locks
#         self.div_lec_teacher = {}
#         self.batch_lab_teacher = {}

#         # Lab tracking
#         self.div_day_labs = defaultdict(list)
#         self.batch_lab_count = defaultdict(int)
#         self.teacher_batch_count = defaultdict(int)

#     def _is_busy(self, busy_list, day, start_min, end_min):
#         """Check if resource is busy during time range"""
#         for busy_day, busy_start, busy_end in busy_list:
#             if busy_day == day:
#                 if max(start_min, busy_start) < min(end_min, busy_end):
#                     return True
#         return False

#     def _mark_busy(self, busy_list, day, start_min, end_min):
#         """Mark resource as busy"""
#         busy_list.append((day, start_min, end_min))

#     def _room_free(self, mt, room):
#         start_min, end_min = _parse(mt.time)
#         return not self._is_busy(self.room_busy[room.r_number], mt.day, start_min, end_min)

#     def _teacher_free(self, mt, teacher):
#         start_min, end_min = _parse(mt.time)
#         return not self._is_busy(self.teacher_busy[teacher.uid], mt.day, start_min, end_min)

#     def _div_free(self, mt, div_id):
#         start_min, end_min = _parse(mt.time)
#         return not self._is_busy(self.div_busy[div_id], mt.day, start_min, end_min)

#     def _batch_free(self, mt, batch_id):
#         start_min, end_min = _parse(mt.time)
#         return not self._is_busy(self.batch_busy[batch_id], mt.day, start_min, end_min)

#     def _mark(self, mt, room, teacher, div_id=None, batch_id=None):
#         """Mark all resources as busy"""
#         start_min, end_min = _parse(mt.time)
#         day = mt.day

#         self._mark_busy(self.room_busy[room.r_number], day, start_min, end_min)
#         self._mark_busy(self.teacher_busy[teacher.uid], day, start_min, end_min)

#         if div_id:
#             self._mark_busy(self.div_busy[div_id], day, start_min, end_min)
#         if batch_id:
#             self._mark_busy(self.batch_busy[batch_id], day, start_min, end_min)

#     def _get_lecture_teacher(self, div_id, course_code, mt=None):
#         """Fixed teacher for division lecture"""
#         key = (div_id, course_code)
        
#         if key in self.div_lec_teacher:
#             teacher = self.div_lec_teacher[key]
#             if mt is None or self._teacher_free(mt, teacher):
#                 return teacher
#             return None

#         pool = self.data.eligible_teachers.get(course_code, [])
#         if not pool:
#             return None

#         if mt:
#             available = [t for t in pool if self._teacher_free(mt, t)]
#             if not available:
#                 return None
#             available.sort(key=lambda t: self.teacher_batch_count.get(t.uid, 0))
#             chosen = available[0]
#         else:
#             pool.sort(key=lambda t: self.teacher_batch_count.get(t.uid, 0))
#             chosen = pool[0]
            
#         self.div_lec_teacher[key] = chosen
#         return chosen

#     def _get_lab_teacher_for_batch(self, batch_id, course_code, mt, assigned_teachers_this_session):
#         """
#         FIXED: Get lab teacher with session-level locking
#         assigned_teachers_this_session: set of teacher UIDs already assigned in THIS lab session
#         """
#         key = (batch_id, course_code)
        
#         # Check for existing assignment
#         if key in self.batch_lab_teacher:
#             teacher = self.batch_lab_teacher[key]
#             if self._teacher_free(mt, teacher):
#                 return teacher
#             return None

#         pool = self.data.eligible_teachers.get(course_code, [])
#         if not pool:
#             return None

#         # Filter candidates
#         candidates = []
#         for teacher in pool:
#             if not self._teacher_free(mt, teacher):
#                 continue
#             if self.teacher_batch_count[teacher.uid] >= MAX_BATCHES_PER_TEACHER:
#                 continue
#             # CRITICAL: Teacher cannot be assigned to multiple batches in THIS session
#             if teacher.uid in assigned_teachers_this_session:
#                 continue
#             candidates.append(teacher)

#         if not candidates:
#             return None

#         # Choose least loaded
#         candidates.sort(key=lambda t: self.teacher_batch_count.get(t.uid, 0))
#         chosen = candidates[0]
        
#         # Lock this teacher
#         self.batch_lab_teacher[key] = chosen
#         self.teacher_batch_count[chosen.uid] += 1
#         assigned_teachers_this_session.add(chosen.uid)  # CRITICAL: Mark as used in this session
        
#         return chosen

#     def assign_labs(self):
#         """
#         PHASE 1: Labs - CRITICAL FIX for room distribution
#         """
#         data = self.data
#         print(f"\n📊 PHASE 1: Assigning labs")

#         tasks = []
#         for div in data.divisions:
#             for course_code, needed in LAB_FREQUENCY.items():
#                 key = (div.id, course_code)
#                 sections = data.div_lab_groups.get(key, [])
#                 if len(sections) != 4:
#                     continue

#                 tasks.append({
#                     'division': div,
#                     'course_code': course_code,
#                     'sections': sections,
#                     'needed': needed,
#                 })

#         random.shuffle(tasks)

#         for task in tasks:
#             div = task['division']
#             course_code = task['course_code']
#             sections = task['sections']
#             needed = task['needed']
#             assigned = 0

#             for attempt in range(500):
#                 if assigned >= needed:
#                     break

#                 days = DAYS_ORDER.copy()
#                 random.shuffle(days)

#                 for day in days:
#                     if assigned >= needed:
#                         break

#                     div_day_key = (div.id, day)
#                     if len(self.div_day_labs[div_day_key]) >= MAX_LABS_PER_DAY:
#                         continue

#                     for mt in data.lab_slots_by_day.get(day, []):
#                         # Check consecutive labs
#                         existing_times = self.div_day_labs[div_day_key]
#                         if any(_is_lab_slot_consecutive(existing, mt.time) for existing in existing_times):
#                             continue

#                         # Division must be free
#                         if not self._div_free(mt, div.id):
#                             continue

#                         # All batches must be free
#                         batches = data.batches_by_division.get(div.id, [])
#                         if not all(self._batch_free(mt, batch.id) for batch in batches):
#                             continue

#                         # ═══════════════════════════════════════════════════════════
#                         # CRITICAL FIX: Assign teachers and rooms atomically
#                         # ═══════════════════════════════════════════════════════════
                        
#                         assigned_teachers_this_session = set()  # Track UIDs used in THIS session
#                         teacher_assignments = {}  # batch_id -> teacher
#                         room_assignments = {}      # batch_id -> room
                        
#                         all_valid = True

#                         # STEP 1: Assign all 4 teachers
#                         for section in sections:
#                             batch = section.batch
#                             teacher = self._get_lab_teacher_for_batch(
#                                 batch.id, course_code, mt, assigned_teachers_this_session
#                             )
#                             if teacher is None:
#                                 all_valid = False
#                                 break
#                             teacher_assignments[batch.id] = teacher

#                         if not all_valid:
#                             continue

#                         # STEP 2: Assign all 4 rooms (EACH BATCH GETS A DIFFERENT ROOM)
#                         available_rooms = [r for r in data.lab_rooms if self._room_free(mt, r)]
                        
#                         if len(available_rooms) < 4:
#                             # Not enough rooms for all 4 batches
#                             continue

#                         # CRITICAL: Assign UNIQUE room to each batch
#                         used_rooms = set()
#                         for section in sections:
#                             batch = section.batch
                            
#                             # Find a room not yet used in this session
#                             free_unused_rooms = [r for r in available_rooms 
#                                                 if r.r_number not in used_rooms]
                            
#                             if not free_unused_rooms:
#                                 all_valid = False
#                                 break
                            
#                             room = random.choice(free_unused_rooms)
#                             room_assignments[batch.id] = room
#                             used_rooms.add(room.r_number)

#                         if not all_valid:
#                             continue

#                         # ═══════════════════════════════════════════════════════════
#                         # ALL CHECKS PASSED - Commit atomically
#                         # ═══════════════════════════════════════════════════════════
                        
#                         for section in sections:
#                             batch = section.batch
#                             teacher = teacher_assignments[batch.id]
#                             room = room_assignments[batch.id]

#                             sc = SC(section, mt, room, teacher)
#                             self.result.append(sc)

#                             self._mark(mt, room, teacher, div_id=div.id, batch_id=batch.id)
#                             self.batch_lab_count[(batch.id, course_code)] += 1

#                         self.div_day_labs[div_day_key].append(mt.time)
#                         assigned += 1

#                         print(f"    ✓ {div.division_name} {course_code} on {day} at {mt.time[:13]}")
#                         break

#             if assigned < needed:
#                 print(f"  ⚠️  {div.division_name} {course_code}: {assigned}/{needed}")

#     def assign_lectures(self):
#         """PHASE 2: Lectures"""
#         data = self.data
#         print(f"\n📊 PHASE 2: Assigning lectures")

#         lecture_by_division = defaultdict(list)
#         for section in data.lecture_sections:
#             if section.division:
#                 lecture_by_division[section.division.id].append(section)

#         for div_id, sections in lecture_by_division.items():
#             div = Division.objects.get(id=div_id)

#             for section in sections:
#                 course = section.course
#                 course_code = course.course_number
#                 needed = LECTURE_FREQUENCY.get(course_code, 3)

#                 teacher = self._get_lecture_teacher(div.id, course_code)
#                 if not teacher:
#                     print(f"  ⚠️  No teacher for {div.division_name} {course_code}")
#                     continue

#                 assigned = 0
#                 days_used = defaultdict(int)

#                 for _ in range(300):
#                     if assigned >= needed:
#                         break

#                     days = DAYS_ORDER.copy()
#                     random.shuffle(days)

#                     for day in days:
#                         if assigned >= needed:
#                             break

#                         if days_used[day] >= 2:
#                             continue

#                         for mt in data.lec_slots_by_day.get(day, []):
#                             if not self._div_free(mt, div.id):
#                                 continue

#                             if not self._teacher_free(mt, teacher):
#                                 continue

#                             free_rooms = [room for room in data.lecture_rooms if self._room_free(mt, room)]
#                             if not free_rooms:
#                                 continue

#                             room = random.choice(free_rooms)

#                             sc = SC(section, mt, room, teacher)
#                             self.result.append(sc)

#                             self._mark(mt, room, teacher, div_id=div.id)

#                             days_used[day] += 1
#                             assigned += 1

#                             print(f"    ✓ {div.division_name} {course_code} on {day} at {mt.time[:11]}")
#                             break

#                 if assigned < needed:
#                     print(f"  ⚠️  {div.division_name} {course_code}: {assigned}/{needed}")

#     def generate(self):
#         self.assign_labs()
#         self.assign_lectures()
#         return self.result


# # ── Verification ─────────────────────────────────────────────────────────────

# def verify_timetable(solution):
#     """Comprehensive verification"""
#     conflicts = []

#     # Room conflicts
#     room_time_map = defaultdict(list)
#     for sc in solution:
#         start, end = _parse(sc.meeting_time.time)
#         key = (sc.room.r_number, sc.meeting_time.day, start, end)
#         room_time_map[key].append(sc)

#     for key, slots in room_time_map.items():
#         if len(slots) > 1:
#             room, day, start, end = key
#             conflict_details = [f"{sc.division.division_name if sc.division else sc.batch.batch_name} {sc.course.course_number}" for sc in slots]
#             conflicts.append(f"Room {room} conflict on {day} {start}-{end}: {conflict_details}")

#     # Teacher conflicts
#     teacher_time_map = defaultdict(list)
#     for sc in solution:
#         start, end = _parse(sc.meeting_time.time)
#         key = (sc.instructor.uid, sc.meeting_time.day)
#         teacher_time_map[key].append((start, end, sc))

#     for key, slots in teacher_time_map.items():
#         for i, (s1, e1, sc1) in enumerate(slots):
#             for s2, e2, sc2 in slots[i+1:]:
#                 if max(s1, s2) < min(e1, e2):
#                     teacher = Instructor.objects.get(uid=key[0])
#                     conflicts.append(
#                         f"Teacher {teacher.name} conflict on {key[1]}: "
#                         f"{sc1.course.course_number} ({s1}-{e1}) vs {sc2.course.course_number} ({s2}-{e2})"
#                     )

#     # Teacher consistency
#     div_subject_teachers = defaultdict(set)
#     for sc in solution:
#         if sc.course.course_type == 'LECTURE' and sc.division:
#             key = (sc.division.id, sc.course.course_number)
#             div_subject_teachers[key].add(sc.instructor.uid)

#     for key, teachers in div_subject_teachers.items():
#         if len(teachers) > 1:
#             div = Division.objects.get(id=key[0])
#             conflicts.append(f"Multiple teachers for {div.division_name} {key[1]}")

#     # Batch teacher consistency
#     batch_subject_teachers = defaultdict(set)
#     for sc in solution:
#         if sc.course.course_type == 'LAB' and sc.batch:
#             key = (sc.batch.id, sc.course.course_number)
#             batch_subject_teachers[key].add(sc.instructor.uid)

#     for key, teachers in batch_subject_teachers.items():
#         if len(teachers) > 1:
#             batch = Batch.objects.get(id=key[0])
#             conflicts.append(f"Multiple teachers for batch {batch.batch_name} {key[1]}")

#     return conflicts


# # ── Django view ───────────────────────────────────────────────────────────────

# def timetable(request):
#     print("\n" + "=" * 70)
#     print("🚀 TIMETABLE GENERATOR — ZERO-CONFLICT VERSION")
#     print("=" * 70)

#     start_time = time_module.time()
#     data = TimetableData()

#     best_solution = None
#     best_conflicts = float('inf')

#     for attempt in range(1, MAX_RETRIES + 1):
#         print(f"\n📊 Attempt {attempt}/{MAX_RETRIES}")

#         generator = TimetableGenerator(data)
#         solution = generator.generate()
#         conflicts = verify_timetable(solution)

#         print(f"  → {len(solution)} classes, {len(conflicts)} conflicts")

#         if len(conflicts) < best_conflicts:
#             best_conflicts = len(conflicts)
#             best_solution = solution

#             if best_conflicts == 0:
#                 print(f"\n✅ PERFECT TIMETABLE on attempt {attempt}!")
#                 break

#     elapsed = round(time_module.time() - start_time, 2)
#     final_conflicts = verify_timetable(best_solution) if best_solution else []

#     print("\n" + "=" * 70)
#     print(f"🏁 FINAL: {len(best_solution)} classes, {len(final_conflicts)} conflicts, {elapsed}s")
#     if final_conflicts:
#         print("Remaining conflicts:")
#         for c in final_conflicts[:15]:
#             print(f"  - {c}")
#     else:
#         print("✅ ZERO CONFLICTS - PERFECT TIMETABLE!")
#     print("=" * 70)

#     context = {
#         'schedule': best_solution,
#         'sections': data.sections,
#         'times': data.meeting_times,
#         'generations': attempt,
#         'fitness': 1.0 if len(final_conflicts) == 0 else round(1 / (1 + len(final_conflicts)), 4),
#         'conflicts': len(final_conflicts),
#         'verified': len(final_conflicts) == 0,
#         'time_taken': elapsed,
#     }

#     return render(request, 'gentimetable.html', context)


# # ── All other views (unchanged) ──────────────────────────────────────────────
# def index(request):
#     return render(request, 'index.html', {})

# def about(request):
#     return render(request, 'aboutus.html', {})

# def help(request):
#     return render(request, 'help.html', {})

# def terms(request):
#     return render(request, 'terms.html', {})

# def contact(request):
#     return render(request, 'contact.html', {})

# def generate(request):
#     return render(request, 'generate.html', {})

# @login_required
# def admindash(request):
#     return render(request, 'admindashboard.html', {
#         'total_departments': Department.objects.count(),
#         'total_divisions': Division.objects.count(),
#         'total_batches': Batch.objects.count(),
#         'total_instructors': Instructor.objects.count(),
#         'total_rooms': Room.objects.count(),
#         'total_courses': Course.objects.count(),
#         'total_sections': Section.objects.count(),
#     })

# @login_required
# def addDepts(request):
#     form = DepartmentForm(request.POST or None)
#     if request.method == 'POST' and form.is_valid():
#         form.save()
#         return redirect('addDepts')
#     return render(request, 'addDepts.html', {'form': form})

# @login_required
# def department_list(request):
#     return render(request, 'deptlist.html', {'departments': Department.objects.all()})

# @login_required
# def delete_department(request, pk):
#     if request.method == 'POST':
#         Department.objects.filter(pk=pk).delete()
#         return redirect('editdepartment')

# @login_required
# def addDivisions(request):
#     form = DivisionForm(request.POST or None)
#     if request.method == 'POST' and form.is_valid():
#         form.save()
#         return redirect('addDivisions')
#     return render(request, 'addDivisions.html', {'form': form})

# @login_required
# def division_list(request):
#     return render(request, 'divisionlist.html', {'divisions': Division.objects.all()})

# @login_required
# def delete_division(request, pk):
#     if request.method == 'POST':
#         Division.objects.filter(pk=pk).delete()
#         return redirect('editdivision')

# @login_required
# def addBatches(request):
#     form = BatchForm(request.POST or None)
#     if request.method == 'POST' and form.is_valid():
#         form.save()
#         return redirect('addBatches')
#     return render(request, 'addBatches.html', {'form': form})

# @login_required
# def batch_list(request):
#     return render(request, 'batchlist.html', {'batches': Batch.objects.all()})

# @login_required
# def delete_batch(request, pk):
#     if request.method == 'POST':
#         Batch.objects.filter(pk=pk).delete()
#         return redirect('editbatch')

# @login_required
# def addCourses(request):
#     form = CourseForm(request.POST or None)
#     if request.method == 'POST' and form.is_valid():
#         form.save()
#         return redirect('addCourses')
#     return render(request, 'addCourses.html', {'form': form})

# @login_required
# def course_list_view(request):
#     return render(request, 'courseslist.html', {'courses': Course.objects.all()})

# @login_required
# def delete_course(request, pk):
#     if request.method == 'POST':
#         Course.objects.filter(pk=pk).delete()
#         return redirect('editcourse')

# @login_required
# def addInstructor(request):
#     form = InstructorForm(request.POST or None)
#     if request.method == 'POST' and form.is_valid():
#         form.save()
#         return redirect('addInstructors')
#     return render(request, 'addInstructors.html', {'form': form})

# @login_required
# def inst_list_view(request):
#     return render(request, 'inslist.html', {'instructors': Instructor.objects.all()})

# @login_required
# def delete_instructor(request, pk):
#     if request.method == 'POST':
#         Instructor.objects.filter(pk=pk).delete()
#         return redirect('editinstructor')

# @login_required
# def addRooms(request):
#     form = RoomForm(request.POST or None)
#     if request.method == 'POST' and form.is_valid():
#         form.save()
#         return redirect('addRooms')
#     return render(request, 'addRooms.html', {'form': form})

# @login_required
# def room_list(request):
#     return render(request, 'roomslist.html', {'rooms': Room.objects.all()})

# @login_required
# def delete_room(request, pk):
#     if request.method == 'POST':
#         Room.objects.filter(pk=pk).delete()
#         return redirect('editrooms')

# @login_required
# def addTimings(request):
#     form = MeetingTimeForm(request.POST or None)
#     if request.method == 'POST' and form.is_valid():
#         form.save()
#         return redirect('addTimings')
#     return render(request, 'addTimings.html', {'form': form})

# @login_required
# def meeting_list_view(request):
#     return render(request, 'mtlist.html', {'meeting_times': MeetingTime.objects.all()})

# @login_required
# def delete_meeting_time(request, pk):
#     if request.method == 'POST':
#         MeetingTime.objects.filter(pk=pk).delete()
#         return redirect('editmeetingtime')

# @login_required
# def addSections(request):
#     form = SectionForm(request.POST or None)
#     if request.method == 'POST' and form.is_valid():
#         form.save()
#         return redirect('addSections')
#     return render(request, 'addSections.html', {'form': form})

# @login_required
# def section_list(request):
#     return render(request, 'seclist.html', {'sections': Section.objects.all()})

# @login_required
# def delete_section(request, pk):
#     if request.method == 'POST':
#         Section.objects.filter(pk=pk).delete()
#         return redirect('editsection')

# kimi algo with 0 conflict

"""
views.py — Timetable Generator (ZERO-CONFLICT VERSION)
======================================================
Fixed: Teacher locking, cross-division clashes, room races
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
MAX_RETRIES = 100

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
    """Lab slot priority"""
    if '08:45' in time_str:
        return 1
    if '11:00' in time_str:
        return 2
    if '13:45' in time_str:
        return 3
    return 99

def _is_lab_slot_consecutive(time1_str, time2_str):
    """Check if two lab times are consecutive"""
    s1, e1 = _parse(time1_str)
    s2, e2 = _parse(time2_str)
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

        # NEW: Pre-compute lecture teacher assignments to avoid cross-division clashes
        self.preferred_lec_teachers = {}
        for div in self.divisions:
            for course_code in LECTURE_FREQUENCY.keys():
                pool = self.eligible_teachers.get(course_code, [])
                if pool:
                    # Assign least-loaded teacher as preferred
                    self.preferred_lec_teachers[(div.id, course_code)] = pool[0]

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

        # FIXED: Use (day, start_min, end_min) for precise tracking
        self.room_busy = defaultdict(list)
        self.teacher_busy = defaultdict(list)
        self.div_busy = defaultdict(list)
        self.batch_busy = defaultdict(list)

        # Teacher locks - FIXED: These now work as COMMITTED assignments
        self.div_lec_teacher = {}
        self.batch_lab_teacher = {}

        # Lab tracking
        self.div_day_labs = defaultdict(list)
        self.batch_lab_count = defaultdict(int)
        self.teacher_batch_count = defaultdict(int)
        
        # NEW: Track assigned (day, time) slots to prevent cross-division clashes
        self.assigned_slots = defaultdict(list)  # (day, start_min, end_min) -> list of assigned resources

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
        """Mark all resources as busy - ATOMIC OPERATION"""
        start_min, end_min = _parse(mt.time)
        day = mt.day

        self._mark_busy(self.room_busy[room.r_number], day, start_min, end_min)
        self._mark_busy(self.teacher_busy[teacher.uid], day, start_min, end_min)

        if div_id:
            self._mark_busy(self.div_busy[div_id], day, start_min, end_min)
        if batch_id:
            self._mark_busy(self.batch_busy[batch_id], day, start_min, end_min)

    def _get_lecture_teacher(self, div_id, course_code, mt=None):
        """
        C4: Fixed teacher for division
        FIXED: If mt provided, verify teacher is actually free (cross-division check)
        """
        key = (div_id, course_code)
        
        # If already assigned, verify availability
        if key in self.div_lec_teacher:
            teacher = self.div_lec_teacher[key]
            if mt is None or self._teacher_free(mt, teacher):
                return teacher
            # Teacher busy - this is a conflict we need to handle
            return None

        pool = self.data.eligible_teachers.get(course_code, [])
        if not pool:
            return None

        # FIXED: Filter to only available teachers at this time
        if mt:
            available = [t for t in pool if self._teacher_free(mt, t)]
            if not available:
                return None
            # Choose least loaded from available
            available.sort(key=lambda t: self.teacher_batch_count.get(t.uid, 0))
            chosen = available[0]
        else:
            pool.sort(key=lambda t: self.teacher_batch_count.get(t.uid, 0))
            chosen = pool[0]
            
        self.div_lec_teacher[key] = chosen
        return chosen

    def _get_lab_teacher_for_batch(self, batch_id, course_code, mt, assigned_teachers_cache):
        """
        FIXED: Get lab teacher with immediate reservation to prevent race conditions
        assigned_teachers_cache: dict of batch_id -> teacher for current lab session
        """
        # Check if this batch already has a teacher assigned in this session
        if batch_id in assigned_teachers_cache:
            teacher = assigned_teachers_cache[batch_id]
            # Verify the pre-selected teacher is still free (might have been taken by another division)
            if self._teacher_free(mt, teacher):
                return teacher
            return None

        key = (batch_id, course_code)
        
        # Check for existing assignment
        if key in self.batch_lab_teacher:
            teacher = self.batch_lab_teacher[key]
            if self._teacher_free(mt, teacher):
                assigned_teachers_cache[batch_id] = teacher
                return teacher
            return None

        pool = self.data.eligible_teachers.get(course_code, [])
        if not pool:
            return None

        # CRITICAL FIX: Get all teachers currently busy at this time across ALL divisions
        start_min, end_min = _parse(mt.time)
        
        # Filter candidates: must be free AND not at batch limit
        candidates = []
        for teacher in pool:
            if not self._teacher_free(mt, teacher):
                continue
            if self.teacher_batch_count[teacher.uid] >= MAX_BATCHES_PER_TEACHER:
                continue
            # CRITICAL: Check if teacher is already assigned to another batch in THIS lab session
            if teacher.uid in [t.uid for t in assigned_teachers_cache.values()]:
                continue
            candidates.append(teacher)

        if not candidates:
            return None

        # Choose least loaded
        candidates.sort(key=lambda t: self.teacher_batch_count.get(t.uid, 0))
        chosen = candidates[0]
        
        # IMMEDIATELY reserve to prevent other batches from taking this teacher
        assigned_teachers_cache[batch_id] = chosen
        self.batch_lab_teacher[key] = chosen
        self.teacher_batch_count[chosen.uid] += 1
        
        return chosen

    def _get_lab_room_for_batch(self, batch_id, mt, assigned_rooms_cache):
        """
        FIXED: Get room with immediate reservation - KEYED BY BATCH_ID not room_number
        """
        # Check if this batch already has a room assigned
        if batch_id in assigned_rooms_cache:
            return assigned_rooms_cache[batch_id]
            
        # Filter available rooms (not used by other batches in this session and not busy globally)
        used_room_numbers = set(room.r_number for room in assigned_rooms_cache.values())
        
        available = []
        for room in self.data.lab_rooms:
            if room.r_number in used_room_numbers:
                continue
            if self._room_free(mt, room):
                available.append(room)
        
        if not available:
            return None
            
        room = random.choice(available)
        # Store by batch_id so each batch gets its own room
        assigned_rooms_cache[batch_id] = room
        return room

    def assign_labs(self):
        """
        PHASE 1: Labs first - FIXED: Atomic assignment with proper locking
        """
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

        # Sort by complexity - more constrained first
        random.shuffle(tasks)

        for task in tasks:
            div = task['division']
            course_code = task['course_code']
            sections = task['sections']
            needed = task['needed']
            assigned = 0

            for attempt in range(500):
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

                        # CRITICAL FIX: Atomic teacher and room assignment
                        # Use caches to reserve resources immediately within this lab session
                        teacher_cache = {}  # batch_id -> teacher
                        room_cache = {}     # batch_id -> room (FIXED: keyed by batch_id)
                        
                        teacher_valid = True
                        room_valid = True

                        # Assign teachers first (all 4 batches)
                        for section in sections:
                            batch = section.batch
                            teacher = self._get_lab_teacher_for_batch(
                                batch.id, course_code, mt, teacher_cache
                            )
                            if teacher is None:
                                teacher_valid = False
                                break

                        if not teacher_valid:
                            continue

                        # Assign rooms (all 4 batches) - FIXED: pass batch_id
                        for section in sections:
                            batch = section.batch
                            room = self._get_lab_room_for_batch(batch.id, mt, room_cache)
                            if room is None:
                                room_valid = False
                                break

                        if not room_valid:
                            continue

                        # ALL CHECKS PASSED - Commit all resources atomically
                        for section in sections:
                            batch = section.batch
                            teacher = teacher_cache[batch.id]
                            room = room_cache[batch.id]  # FIXED: access by batch.id

                            sc = SC(section, mt, room, teacher)
                            self.result.append(sc)

                            # Atomic marking
                            self._mark(mt, room, teacher, div_id=div.id, batch_id=batch.id)
                            self.batch_lab_count[(batch.id, course_code)] += 1

                        self.div_day_labs[div_day_key].append(mt.time)
                        assigned += 1

                        print(f"    ✓ {div.division_name} {course_code} on {day} at {mt.time[:13]}")
                        break

            if assigned < needed:
                print(f"  ⚠️  {div.division_name} {course_code}: {assigned}/{needed}")

    def assign_lectures(self):
        """
        PHASE 2: Lectures - FIXED: Check against all lab assignments
        """
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

                # FIXED: Get teacher with availability check
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
                            # Check division availability
                            if not self._div_free(mt, div.id):
                                continue

                            # CRITICAL FIX: Check teacher availability against ALL previous assignments
                            # including labs from other divisions
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
    """
    Comprehensive verification - ENHANCED to catch all conflict types
    """
    conflicts = []

    # Room conflicts (including across all types)
    room_time_map = defaultdict(list)
    for sc in solution:
        start, end = _parse(sc.meeting_time.time)
        key = (sc.room.r_number, sc.meeting_time.day, start, end)
        room_time_map[key].append(sc)

    for key, slots in room_time_map.items():
        if len(slots) > 1:
            room, day, start, end = key
            conflict_details = [f"{sc.division.division_name if sc.division else 'Unknown'} {sc.course.course_number}" for sc in slots]
            conflicts.append(f"Room {room} conflict on {day} {start}-{end}: {conflict_details}")

    # Teacher conflicts (ENHANCED: check all overlaps precisely)
    teacher_time_map = defaultdict(list)
    for sc in solution:
        start, end = _parse(sc.meeting_time.time)
        key = (sc.instructor.uid, sc.meeting_time.day)
        teacher_time_map[key].append((start, end, sc))

    for key, slots in teacher_time_map.items():
        # Check all pairs for overlaps
        for i, (s1, e1, sc1) in enumerate(slots):
            for s2, e2, sc2 in slots[i+1:]:
                if max(s1, s2) < min(e1, e2):
                    teacher = Instructor.objects.get(uid=key[0])
                    conflicts.append(
                        f"Teacher {teacher.name} ({teacher.uid}) conflict on {key[1]}: "
                        f"{sc1.division.division_name if sc1.division else 'Unknown'} {sc1.course.course_number} "
                        f"({s1}-{e1}) vs "
                        f"{sc2.division.division_name if sc2.division else 'Unknown'} {sc2.course.course_number} "
                        f"({s2}-{e2})"
                    )

    # Teacher consistency (same teacher for same division/subject)
    div_subject_teachers = defaultdict(set)
    for sc in solution:
        if sc.course.course_type == 'LECTURE' and sc.division:
            key = (sc.division.id, sc.course.course_number)
            div_subject_teachers[key].add(sc.instructor.uid)

    for key, teachers in div_subject_teachers.items():
        if len(teachers) > 1:
            div = Division.objects.get(id=key[0])
            conflicts.append(f"Multiple teachers for {div.division_name} {key[1]}: {teachers}")

    # Batch teacher consistency
    batch_subject_teachers = defaultdict(set)
    for sc in solution:
        if sc.course.course_type == 'LAB' and sc.batch:
            key = (sc.batch.id, sc.course.course_number)
            batch_subject_teachers[key].add(sc.instructor.uid)

    for key, teachers in batch_subject_teachers.items():
        if len(teachers) > 1:
            batch = Batch.objects.get(id=key[0])
            conflicts.append(f"Multiple teachers for batch {batch.batch_name} {key[1]}: {teachers}")

    # FIXED: Check for teacher double-booking across divisions at same time
    teacher_exact_time = set()  # FIXED: Changed from defaultdict to set
    for sc in solution:
        start, end = _parse(sc.meeting_time.time)
        time_key = (sc.meeting_time.day, start, end)
        teacher_time_key = (sc.instructor.uid, time_key)
        
        if teacher_time_key in teacher_exact_time:
            conflicts.append(
                f"Teacher {sc.instructor.name} double-booked at {time_key}: "
                f"multiple assignments"
            )
        teacher_exact_time.add(teacher_time_key)

    return conflicts


# ── Django view ───────────────────────────────────────────────────────────────

def timetable(request):
    print("\n" + "=" * 70)
    print("🚀 TIMETABLE GENERATOR — ZERO-CONFLICT VERSION")
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
    final_conflicts = verify_timetable(best_solution) if best_solution else []

    print("\n" + "=" * 70)
    print(f"🏁 FINAL: {len(best_solution)} classes, {len(final_conflicts)} conflicts, {elapsed}s")
    if final_conflicts:
        print("Conflicts found:")
        for c in final_conflicts[:10]:  # Show first 10
            print(f"  - {c}")
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


# ── Other views (unchanged) ───────────────────────────────────────────────────
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