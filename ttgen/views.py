
# """
# views.py — Timetable Generator (ZERO-CONFLICT + ROOM LOCKING + LOAD BALANCING)
# ==============================================================================
# Fixed: Load balancing - distribute lectures across all qualified teachers
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
        
#         # Room locks
#         self.batch_lab_room = {}

#         # Lab tracking
#         self.div_day_labs = defaultdict(list)
#         self.batch_lab_count = defaultdict(int)
#         self.teacher_batch_count = defaultdict(int)
        
#         # ✅ NEW: Track lecture load per teacher (for load balancing)
#         self.teacher_lecture_load = defaultdict(int)  # teacher_uid -> number of divisions assigned

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
#         """
#         ✅ FIXED: Load balancing for lecture teachers
#         Assign teachers to divisions evenly across all qualified teachers
#         """
#         key = (div_id, course_code)
        
#         # If already assigned, return existing assignment
#         if key in self.div_lec_teacher:
#             teacher = self.div_lec_teacher[key]
#             if mt is None or self._teacher_free(mt, teacher):
#                 return teacher
#             return None

#         pool = self.data.eligible_teachers.get(course_code, [])
#         if not pool:
#             return None

#         # ✅ CRITICAL FIX: Sort by LECTURE LOAD instead of batch count
#         # This ensures even distribution across divisions
#         if mt:
#             # Filter to available teachers at this time
#             available = [t for t in pool if self._teacher_free(mt, t)]
#             if not available:
#                 return None
            
#             # ✅ Sort by lecture load (divisions assigned) - LOAD BALANCING
#             available.sort(key=lambda t: (
#                 self.teacher_lecture_load.get(t.uid, 0),  # Primary: lecture divisions
#                 self.teacher_batch_count.get(t.uid, 0)     # Secondary: lab batches
#             ))
#             chosen = available[0]
#         else:
#             # Initial assignment - sort by current load
#             pool_sorted = sorted(pool, key=lambda t: (
#                 self.teacher_lecture_load.get(t.uid, 0),
#                 self.teacher_batch_count.get(t.uid, 0)
#             ))
#             chosen = pool_sorted[0]
        
#         # Lock this teacher for this division-course
#         self.div_lec_teacher[key] = chosen
        
#         # ✅ Increment lecture load counter
#         self.teacher_lecture_load[chosen.uid] += 1
        
#         print(f"      🎓 Assigned {chosen.name} to {Division.objects.get(id=div_id).division_name} {course_code} (load: {self.teacher_lecture_load[chosen.uid]} divisions)")
        
#         return chosen

#     def _get_lab_teacher_for_batch(self, batch_id, course_code, mt, assigned_teachers_this_session):
#         """Get lab teacher with session-level locking"""
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
#             if teacher.uid in assigned_teachers_this_session:
#                 continue
#             candidates.append(teacher)

#         if not candidates:
#             return None

#         # ✅ Sort by total load (both lectures and labs)
#         candidates.sort(key=lambda t: (
#             self.teacher_batch_count.get(t.uid, 0),
#             self.teacher_lecture_load.get(t.uid, 0)
#         ))
#         chosen = candidates[0]
        
#         self.batch_lab_teacher[key] = chosen
#         self.teacher_batch_count[chosen.uid] += 1
#         assigned_teachers_this_session.add(chosen.uid)
        
#         return chosen

#     def _get_lab_room_for_batch(self, batch_id, course_code, mt, assigned_rooms_this_session):
#         """Room locking per batch-course pair"""
#         key = (batch_id, course_code)
        
#         # Check if already locked
#         if key in self.batch_lab_room:
#             locked_room = self.batch_lab_room[key]
            
#             if self._room_free(mt, locked_room):
#                 if locked_room.r_number not in assigned_rooms_this_session:
#                     assigned_rooms_this_session.add(locked_room.r_number)
#                     return locked_room
            
#             return None
        
#         # First time - pick and lock
#         available = []
#         for room in self.data.lab_rooms:
#             if room.r_number in assigned_rooms_this_session:
#                 continue
#             if not self._room_free(mt, room):
#                 continue
#             available.append(room)
        
#         if not available:
#             return None
        
#         room = random.choice(available)
#         self.batch_lab_room[key] = room
#         assigned_rooms_this_session.add(room.r_number)
        
#         return room

#     def assign_labs(self):
#         """PHASE 1: Labs with room consistency"""
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
#                         existing_times = self.div_day_labs[div_day_key]
#                         if any(_is_lab_slot_consecutive(existing, mt.time) for existing in existing_times):
#                             continue

#                         if not self._div_free(mt, div.id):
#                             continue

#                         batches = data.batches_by_division.get(div.id, [])
#                         if not all(self._batch_free(mt, batch.id) for batch in batches):
#                             continue

#                         assigned_teachers_this_session = set()
#                         assigned_rooms_this_session = set()
                        
#                         teacher_assignments = {}
#                         room_assignments = {}
                        
#                         all_valid = True

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

#                         for section in sections:
#                             batch = section.batch
#                             room = self._get_lab_room_for_batch(
#                                 batch.id, course_code, mt, assigned_rooms_this_session
#                             )
#                             if room is None:
#                                 all_valid = False
#                                 break
#                             room_assignments[batch.id] = room

#                         if not all_valid:
#                             continue

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
#         """PHASE 2: Lectures with load balancing"""
#         data = self.data
#         print(f"\n📊 PHASE 2: Assigning lectures (with load balancing)")

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
        
#         # ✅ Print load distribution summary
#         print("\n" + "=" * 70)
#         print("📊 TEACHER LOAD DISTRIBUTION")
#         print("=" * 70)
        
#         # Group by course
#         lecture_assignments = defaultdict(list)
#         for (div_id, course_code), teacher in self.div_lec_teacher.items():
#             div = Division.objects.get(id=div_id)
#             lecture_assignments[course_code].append((div.division_name, teacher.name))
        
#         for course_code in sorted(lecture_assignments.keys()):
#             print(f"\n{course_code} Lectures:")
#             for div_name, teacher_name in sorted(lecture_assignments[course_code]):
#                 print(f"  {div_name}: {teacher_name}")
        
#         print("\n" + "=" * 70)
        
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
#             conflict_details = [f"{sc.batch.batch_name if sc.batch else sc.division.division_name} {sc.course.course_number}" for sc in slots]
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

#     # Batch room consistency
#     batch_subject_rooms = defaultdict(set)
#     for sc in solution:
#         if sc.course.course_type == 'LAB' and sc.batch:
#             key = (sc.batch.id, sc.course.course_number)
#             batch_subject_rooms[key].add(sc.room.r_number)

#     for key, rooms in batch_subject_rooms.items():
#         if len(rooms) > 1:
#             batch = Batch.objects.get(id=key[0])
#             conflicts.append(f"Batch {batch.batch_name} {key[1]} uses multiple rooms: {rooms}")

#     return conflicts


# # ── Django view ───────────────────────────────────────────────────────────────

# def timetable(request):
#     print("\n" + "=" * 70)
#     print("🚀 TIMETABLE GENERATOR — LOAD BALANCED + ZERO CONFLICT")
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




"""
views.py — Timetable Generator (ZERO-CONFLICT + ROOM LOCKING + LOAD BALANCING + ELECTIVES)
============================================================================================
Phase 0: Electives  →  Phase 1: Labs  →  Phase 2: Lectures

Elective rules enforced:
  • CC and IS run in PARALLEL for the same group (G1 or G2) at the SAME slot
  • Group 1 = TE-I + TE-II,  Group 2 = TE-III + TE-IV
  • All 4 divisions are blocked during every elective slot
  • Each elective needs exactly 2 sessions per week:
      - 1 × 2-hour session  (pid starts with 'E', 2-hour lab-style slot)
      - 1 × 1-hour session  (pid starts with 'L', regular lecture slot)
  • The two sessions must be on DIFFERENT days
  • Both CC and IS for the same group are scheduled to the SAME slot
    (they run simultaneously in different rooms — students choose one)
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

LAB_FREQUENCY  = {'DSBDAL': 2, 'LPII': 2, 'WTL': 1}
LECTURE_FREQUENCY = {'AI': 3, 'DSBDA': 3, 'WT': 3}

# Elective group → which division names belong to that group
ELECTIVE_GROUP_DIVISIONS = {
    'G1': ['TE-I',  'TE-II'],
    'G2': ['TE-III', 'TE-IV'],
}


# ── Time helpers ─────────────────────────────────────────────────────────────

def _to_min(t):
    try:
        h, m = map(int, t.strip().split(':'))
        if 1 <= h <= 7:
            h += 12
        return h * 60 + m
    except Exception:
        return 0

def _parse(time_str):
    try:
        parts = time_str.replace(' ', '').split('-')
        return _to_min(parts[0]), _to_min(parts[1])
    except Exception:
        return 0, 0

def _get_slot_priority(time_str):
    if '08:45' in time_str: return 1
    if '11:00' in time_str: return 2
    if '13:45' in time_str: return 3
    return 99

def _is_lab_slot_consecutive(time1_str, time2_str):
    s1, e1 = _parse(time1_str)
    s2, e2 = _parse(time2_str)
    return (e1 == s2) or (e2 == s1)

def _times_overlap(time1_str, time2_str):
    s1, e1 = _parse(time1_str)
    s2, e2 = _parse(time2_str)
    return max(s1, s2) < min(e1, e2)


# ── Data loader ───────────────────────────────────────────────────────────────

class TimetableData:
    def __init__(self):
        self.divisions     = list(Division.objects.all().order_by('division_name'))
        self.rooms         = list(Room.objects.all())
        self.meeting_times = list(MeetingTime.objects.all())
        self.sections      = list(
            Section.objects.select_related(
                'course', 'division', 'batch', 'batch__division'
            ).all()
        )

        self.lecture_rooms = [r for r in self.rooms if r.room_type == 'LECTURE']
        self.lab_rooms     = [r for r in self.rooms if r.room_type == 'LAB']

        # Slots grouped by day
        self.lab_slots_by_day = defaultdict(list)
        self.lec_slots_by_day = defaultdict(list)

        # Elective slots:
        #   2-hour elective slots → pid starts with 'E'
        #   1-hour elective slots → regular 'L' slots (same pool as lectures)
        self.elec_2h_by_day = defaultdict(list)   # MeetingTime objects with pid 'E...'
        self.elec_1h_by_day = defaultdict(list)   # MeetingTime objects with pid 'L...'

        for mt in self.meeting_times:
            if mt.slot_type == 'LAB':
                self.lab_slots_by_day[mt.day].append(mt)
            else:
                # LECTURE slot_type — check pid to separate elective 2h vs regular
                if mt.pid.startswith('E'):
                    self.elec_2h_by_day[mt.day].append(mt)
                else:
                    self.lec_slots_by_day[mt.day].append(mt)
                    self.elec_1h_by_day[mt.day].append(mt)  # 1-hour elective uses same slots

        # Sort lab slots by priority
        for day in self.lab_slots_by_day:
            self.lab_slots_by_day[day].sort(key=lambda mt: _get_slot_priority(mt.time))

        # Eligible teachers per course
        self.eligible_teachers = {}
        for course in Course.objects.prefetch_related('instructors').all():
            self.eligible_teachers[course.course_number] = list(course.instructors.all())

        # Separate elective sections from regular ones
        self.elective_sections = [s for s in self.sections if s.is_elective]
        self.regular_sections  = [s for s in self.sections if not s.is_elective]

        self.lecture_sections  = [s for s in self.regular_sections
                                   if s.course and s.course.course_type == 'LECTURE']
        self.lab_sections      = [s for s in self.regular_sections
                                   if s.course and s.course.course_type == 'LAB']

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

        # Division name → Division object
        self.div_by_name = {d.division_name: d for d in self.divisions}

        print(f"✅ Loaded: {len(self.sections)} sections "
              f"| {len(self.elective_sections)} elective "
              f"| {len(self.divisions)} divisions")


# ── Scheduled class ──────────────────────────────────────────────────────────

class SC:
    __slots__ = ['section', 'course', 'meeting_time', 'room',
                 'instructor', 'division', 'batch']

    def __init__(self, section, mt, room, instructor, override_division=None):
        self.section      = section
        self.course       = section.course
        self.meeting_time = mt
        self.room         = room
        self.instructor   = instructor
        # override_division allows one elective SC to appear for each division in the group
        self.division     = override_division if override_division else section.division
        self.batch        = section.batch


# ── Generator ────────────────────────────────────────────────────────────────

class TimetableGenerator:
    def __init__(self, data: TimetableData):
        self.data = data
        self._reset()

    def _reset(self):
        self.result = []

        self.room_busy    = defaultdict(list)   # room_number  → [(day, s, e)]
        self.teacher_busy = defaultdict(list)   # teacher_uid  → [(day, s, e)]
        self.div_busy     = defaultdict(list)   # division_id  → [(day, s, e)]
        self.batch_busy   = defaultdict(list)   # batch_id     → [(day, s, e)]

        self.div_lec_teacher  = {}   # (div_id, course_code) → Instructor
        self.batch_lab_teacher = {}  # (batch_id, course_code) → Instructor
        self.batch_lab_room    = {}  # (batch_id, course_code) → Room

        self.div_day_labs        = defaultdict(list)   # (div_id, day) → [time_str]
        self.batch_lab_count     = defaultdict(int)
        self.teacher_batch_count = defaultdict(int)
        self.teacher_lecture_load = defaultdict(int)

        # Track which days each elective group has already been scheduled
        # key: group_name ('G1'/'G2') → list of days used
        self.elec_group_days_used = defaultdict(list)   # group → [day, ...]

    # ── busy helpers ─────────────────────────────────────────────────────────

    def _is_busy(self, busy_list, day, start_min, end_min):
        for bd, bs, be in busy_list:
            if bd == day and max(start_min, bs) < min(end_min, be):
                return True
        return False

    def _mark_busy(self, busy_list, day, start_min, end_min):
        busy_list.append((day, start_min, end_min))

    def _room_free(self, mt, room):
        s, e = _parse(mt.time)
        return not self._is_busy(self.room_busy[room.r_number], mt.day, s, e)

    def _teacher_free(self, mt, teacher):
        s, e = _parse(mt.time)
        return not self._is_busy(self.teacher_busy[teacher.uid], mt.day, s, e)

    def _div_free(self, mt, div_id):
        s, e = _parse(mt.time)
        return not self._is_busy(self.div_busy[div_id], mt.day, s, e)

    def _batch_free(self, mt, batch_id):
        s, e = _parse(mt.time)
        return not self._is_busy(self.batch_busy[batch_id], mt.day, s, e)

    def _mark(self, mt, room, teacher, div_id=None, batch_id=None):
        s, e = _parse(mt.time)
        day  = mt.day
        self._mark_busy(self.room_busy[room.r_number], day, s, e)
        self._mark_busy(self.teacher_busy[teacher.uid], day, s, e)
        if div_id:
            self._mark_busy(self.div_busy[div_id], day, s, e)
        if batch_id:
            self._mark_busy(self.batch_busy[batch_id], day, s, e)

    def _mark_div_only(self, mt, div_id):
        """Block a division without assigning a room/teacher (used for elective blocking)."""
        s, e = _parse(mt.time)
        self._mark_busy(self.div_busy[div_id], mt.day, s, e)

    # ── teacher helpers ───────────────────────────────────────────────────────

    def _get_lecture_teacher(self, div_id, course_code, mt=None):
        key = (div_id, course_code)
        if key in self.div_lec_teacher:
            teacher = self.div_lec_teacher[key]
            if mt is None or self._teacher_free(mt, teacher):
                return teacher
            return None

        pool = self.data.eligible_teachers.get(course_code, [])
        if not pool:
            return None

        if mt:
            available = [t for t in pool if self._teacher_free(mt, t)]
            if not available:
                return None
            available.sort(key=lambda t: (
                self.teacher_lecture_load.get(t.uid, 0),
                self.teacher_batch_count.get(t.uid, 0)
            ))
            chosen = available[0]
        else:
            chosen = sorted(pool, key=lambda t: (
                self.teacher_lecture_load.get(t.uid, 0),
                self.teacher_batch_count.get(t.uid, 0)
            ))[0]

        self.div_lec_teacher[key] = chosen
        self.teacher_lecture_load[chosen.uid] += 1
        return chosen

    def _get_lab_teacher_for_batch(self, batch_id, course_code, mt, used_teachers):
        key = (batch_id, course_code)
        if key in self.batch_lab_teacher:
            teacher = self.batch_lab_teacher[key]
            if self._teacher_free(mt, teacher):
                return teacher
            return None

        pool = self.data.eligible_teachers.get(course_code, [])
        candidates = [
            t for t in pool
            if self._teacher_free(mt, t)
            and self.teacher_batch_count[t.uid] < MAX_BATCHES_PER_TEACHER
            and t.uid not in used_teachers
        ]
        if not candidates:
            return None

        candidates.sort(key=lambda t: (
            self.teacher_batch_count.get(t.uid, 0),
            self.teacher_lecture_load.get(t.uid, 0)
        ))
        chosen = candidates[0]
        self.batch_lab_teacher[key] = chosen
        self.teacher_batch_count[chosen.uid] += 1
        used_teachers.add(chosen.uid)
        return chosen

    def _get_lab_room_for_batch(self, batch_id, course_code, mt, used_rooms):
        key = (batch_id, course_code)
        if key in self.batch_lab_room:
            locked = self.batch_lab_room[key]
            if self._room_free(mt, locked) and locked.r_number not in used_rooms:
                used_rooms.add(locked.r_number)
                return locked
            return None

        available = [
            r for r in self.data.lab_rooms
            if r.r_number not in used_rooms and self._room_free(mt, r)
        ]
        if not available:
            return None

        room = random.choice(available)
        self.batch_lab_room[key] = room
        used_rooms.add(room.r_number)
        return room

    # =========================================================================
    # PHASE 0 — ELECTIVES
    # =========================================================================
    #
    # Strategy
    # ────────
    # For each elective group (G1, G2):
    #   Pick 2 different days — one for the 2-hour session, one for 1-hour.
    #   At the chosen slot:
    #     • Both CC and IS are scheduled IN PARALLEL (same slot, different rooms)
    #     • ALL divisions belonging to that group are blocked at that slot
    #     • Each course gets its group-specific teacher
    #
    # CC-G1  teacher: Chandorkar (T010)   CC-G2  teacher: Masram (T009)
    # IS-G1  teacher: Girme     (T001)    IS-G2  teacher: Kapadnis (T014)
    #
    # The elective_group field on the Section tells us which group each section
    # belongs to ('G1' or 'G2').
    # =========================================================================

    def _get_elective_teacher_for_section(self, section, mt):
        """
        For elective sections the teacher pool on the Course may contain teachers
        for BOTH groups.  We pick the ONE teacher who is free at this slot.
        In practice the data loader assigns:
          CC.instructors = [Chandorkar(G1), Masram(G2)]
          IS.instructors = [Girme(G1),      Kapadnis(G2)]
        We prefer the teacher already locked for this (section, group) pair,
        otherwise pick any free teacher from the pool.
        """
        key = (section.section_id, 'ELECTIVE')
        if key in self.div_lec_teacher:
            teacher = self.div_lec_teacher[key]
            if self._teacher_free(mt, teacher):
                return teacher
            return None

        pool = self.data.eligible_teachers.get(section.course.course_number, [])
        free = [t for t in pool if self._teacher_free(mt, t)]
        if not free:
            return None

        # Prefer teacher with lower overall load
        free.sort(key=lambda t: (
            self.teacher_lecture_load.get(t.uid, 0),
            self.teacher_batch_count.get(t.uid, 0)
        ))
        chosen = free[0]
        self.div_lec_teacher[key] = chosen
        self.teacher_lecture_load[chosen.uid] += 1
        return chosen

    def assign_electives(self):
        """
        PHASE 0: Schedule elective sessions BEFORE labs and lectures.

        KEY RULE: ALL 4 divisions (TE-I, TE-II, TE-III, TE-IV) must share
        the SAME day + SAME time slot for every elective session.

        Layout on an elective day (same slot):
          G1 → CC-G1 (room A) + IS-G1 (room B)
          G2 → CC-G2 (room C) + IS-G2 (room D)
          All 4 divisions blocked simultaneously.

        Two sessions per week on DIFFERENT days:
          Session 1 → 2-hour slot  (pid starts with 'E')
          Session 2 → 1-hour slot  (pid starts with 'L')
        """
        data = self.data
        print("\n📊 PHASE 0: Assigning electives")

        # All elective sections: [CC-G1, IS-G1, CC-G2, IS-G2]
        all_elective_sections = data.elective_sections
        if not all_elective_sections:
            print("  ℹ️  No elective sections found — skipping phase 0")
            return

        # ALL 4 division ids combined
        all_div_ids = []
        for div_names in ELECTIVE_GROUP_DIVISIONS.values():
            for name in div_names:
                div = data.div_by_name.get(name)
                if div:
                    all_div_ids.append(div.id)

        # Need 1 room per section (CC-G1, IS-G1, CC-G2, IS-G2 = 4 rooms)
        needed_rooms = len(all_elective_sections)

        # Track days already used for elective sessions
        # (2-hour and 1-hour must land on DIFFERENT days)
        elective_days_used = []

        for session_label, slot_pool_attr in [
            ('2-hour', 'elec_2h_by_day'),
            ('1-hour', 'elec_1h_by_day'),
        ]:
            slot_pool = getattr(data, slot_pool_attr)
            scheduled = False
            days = DAYS_ORDER.copy()
            random.shuffle(days)

            for day in days:
                # Must be a different day from the other session type
                if day in elective_days_used:
                    continue

                slots = slot_pool.get(day, [])
                random.shuffle(slots)

                for mt in slots:
                    # CHECK 1: ALL 4 divisions free at this slot
                    if not all(self._div_free(mt, did) for did in all_div_ids):
                        continue

                    # CHECK 2: Enough free lecture rooms for all 4 sections
                    free_rooms = [
                        r for r in data.lecture_rooms
                        if self._room_free(mt, r)
                    ]
                    if len(free_rooms) < needed_rooms:
                        continue

                    # CHECK 3: Every section has a free teacher
                    teacher_map = {}
                    valid = True
                    for sec in all_elective_sections:
                        teacher = self._get_elective_teacher_for_section(sec, mt)
                        if teacher is None:
                            valid = False
                            break
                        teacher_map[sec.section_id] = teacher
                    if not valid:
                        continue

                    # CHECK 4: Assign one unique room per section
                    room_map = {}
                    random.shuffle(free_rooms)
                    for idx, sec in enumerate(all_elective_sections):
                        if idx >= len(free_rooms):
                            valid = False
                            break
                        room_map[sec.section_id] = free_rooms[idx]
                    if not valid:
                        continue

                    # ── COMMIT ────────────────────────────────────────────
                    s_min, e_min = _parse(mt.time)

                    print(f"\n  📅 Elective {session_label} → "
                          f"{day} {mt.time[:13]}  "
                          f"[ALL 4 DIVISIONS BLOCKED]")

                    # Build group → [Division objects] map for this commit
                    group_divs = {}
                    for grp, div_names in ELECTIVE_GROUP_DIVISIONS.items():
                        group_divs[grp] = [
                            data.div_by_name[n]
                            for n in div_names
                            if n in data.div_by_name
                        ]

                    for sec in all_elective_sections:
                        teacher = teacher_map[sec.section_id]
                        room    = room_map[sec.section_id]

                        self._mark_busy(self.room_busy[room.r_number],
                                        mt.day, s_min, e_min)
                        self._mark_busy(self.teacher_busy[teacher.uid],
                                        mt.day, s_min, e_min)

                        # ✅ Create one SC per division in this section's group
                        # so that ALL divisions show the elective in their timetable
                        divs_for_group = group_divs.get(sec.elective_group, [sec.division])
                        for div_obj in divs_for_group:
                            sc = SC(sec, mt, room, teacher,
                                    override_division=div_obj)
                            self.result.append(sc)

                        print(f"    ✓ {sec.section_id} ({sec.course.course_number}) "
                              f"[{sec.elective_group}] | "
                              f"Room: {room.r_number} | "
                              f"Teacher: {teacher.name} | "
                              f"Visible to: {[d.division_name for d in divs_for_group]}")

                    # Block ALL 4 divisions at this slot
                    for did in all_div_ids:
                        self._mark_div_only(mt, did)

                    # Block all batches inside all 4 divisions
                    for did in all_div_ids:
                        for batch in data.batches_by_division.get(did, []):
                            self._mark_busy(self.batch_busy[batch.id],
                                            mt.day, s_min, e_min)

                    elective_days_used.append(day)
                    scheduled = True
                    break

                if scheduled:
                    break

            if not scheduled:
                print(f"  ⚠️  Could not schedule {session_label} elective "
                      f"session for ALL 4 divisions!")

    # =========================================================================
    # PHASE 1 — LABS
    # =========================================================================

    def assign_labs(self):
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
            div         = task['division']
            course_code = task['course_code']
            sections    = task['sections']
            needed      = task['needed']
            assigned    = 0

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
                        existing_times = self.div_day_labs[div_day_key]
                        if any(_is_lab_slot_consecutive(e, mt.time) for e in existing_times):
                            continue
                        if not self._div_free(mt, div.id):
                            continue

                        batches = data.batches_by_division.get(div.id, [])
                        if not all(self._batch_free(mt, b.id) for b in batches):
                            continue

                        used_teachers = set()
                        used_rooms    = set()
                        teacher_map   = {}
                        room_map      = {}
                        all_valid     = True

                        for section in sections:
                            t = self._get_lab_teacher_for_batch(
                                section.batch.id, course_code, mt, used_teachers)
                            if t is None:
                                all_valid = False
                                break
                            teacher_map[section.batch.id] = t

                        if not all_valid:
                            continue

                        for section in sections:
                            r = self._get_lab_room_for_batch(
                                section.batch.id, course_code, mt, used_rooms)
                            if r is None:
                                all_valid = False
                                break
                            room_map[section.batch.id] = r

                        if not all_valid:
                            continue

                        for section in sections:
                            batch   = section.batch
                            teacher = teacher_map[batch.id]
                            room    = room_map[batch.id]

                            sc = SC(section, mt, room, teacher)
                            self.result.append(sc)
                            self._mark(mt, room, teacher,
                                       div_id=div.id, batch_id=batch.id)
                            self.batch_lab_count[(batch.id, course_code)] += 1

                        self.div_day_labs[div_day_key].append(mt.time)
                        assigned += 1
                        print(f"    ✓ {div.division_name} {course_code} "
                              f"on {day} at {mt.time[:13]}")
                        break

            if assigned < needed:
                print(f"  ⚠️  {div.division_name} {course_code}: {assigned}/{needed}")

    # =========================================================================
    # PHASE 2 — LECTURES
    # =========================================================================

    def assign_lectures(self):
        data = self.data
        print(f"\n📊 PHASE 2: Assigning lectures (with load balancing)")

        lecture_by_division = defaultdict(list)
        for section in data.lecture_sections:
            if section.division:
                lecture_by_division[section.division.id].append(section)

        for div_id, sections in lecture_by_division.items():
            div = Division.objects.get(id=div_id)

            for section in sections:
                course      = section.course
                course_code = course.course_number
                needed      = LECTURE_FREQUENCY.get(course_code, 3)

                teacher = self._get_lecture_teacher(div.id, course_code)
                if not teacher:
                    print(f"  ⚠️  No teacher for {div.division_name} {course_code}")
                    continue

                assigned  = 0
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

                            free_rooms = [
                                r for r in data.lecture_rooms
                                if self._room_free(mt, r)
                            ]
                            if not free_rooms:
                                continue

                            room = random.choice(free_rooms)
                            sc   = SC(section, mt, room, teacher)
                            self.result.append(sc)
                            self._mark(mt, room, teacher, div_id=div.id)
                            days_used[day] += 1
                            assigned += 1
                            print(f"    ✓ {div.division_name} {course_code} "
                                  f"on {day} at {mt.time[:11]}")
                            break

                if assigned < needed:
                    print(f"  ⚠️  {div.division_name} {course_code}: {assigned}/{needed}")

    # =========================================================================
    # GENERATE
    # =========================================================================

    def generate(self):
        # Order matters: electives first so labs and lectures
        # automatically respect blocked slots
        self.assign_electives()
        self.assign_labs()
        self.assign_lectures()

        # Summary
        print("\n" + "=" * 70)
        print("📊 TEACHER LOAD DISTRIBUTION")
        print("=" * 70)

        lecture_assignments = defaultdict(list)
        for (div_id, course_code), teacher in self.div_lec_teacher.items():
            try:
                div = Division.objects.get(id=div_id)
                lecture_assignments[course_code].append(
                    (div.division_name, teacher.name))
            except Exception:
                pass

        for course_code in sorted(lecture_assignments.keys()):
            print(f"\n{course_code} Lectures:")
            for div_name, teacher_name in sorted(lecture_assignments[course_code]):
                print(f"  {div_name}: {teacher_name}")

        print("\n" + "=" * 70)
        return self.result


# ── Verification ─────────────────────────────────────────────────────────────

def verify_timetable(solution):
    conflicts = []

    # Room conflicts
    room_time_map = defaultdict(list)
    for sc in solution:
        s, e = _parse(sc.meeting_time.time)
        room_time_map[(sc.room.r_number, sc.meeting_time.day, s, e)].append(sc)

    for key, slots in room_time_map.items():
        if len(slots) > 1:
            room, day, s, e = key
            details = [
                f"{sc.batch.batch_name if sc.batch else sc.division.division_name} "
                f"{sc.course.course_number}"
                for sc in slots
            ]
            conflicts.append(
                f"Room {room} conflict on {day} {s}-{e}: {details}")

    # Teacher conflicts (overlap check)
    teacher_day_map = defaultdict(list)
    for sc in solution:
        s, e = _parse(sc.meeting_time.time)
        teacher_day_map[(sc.instructor.uid, sc.meeting_time.day)].append((s, e, sc))

    for key, slots in teacher_day_map.items():
        for i, (s1, e1, sc1) in enumerate(slots):
            for s2, e2, sc2 in slots[i + 1:]:
                if max(s1, s2) < min(e1, e2):
                    try:
                        teacher = Instructor.objects.get(uid=key[0])
                    except Exception:
                        teacher_name = key[0]
                    else:
                        teacher_name = teacher.name
                    conflicts.append(
                        f"Teacher {teacher_name} conflict on {key[1]}: "
                        f"{sc1.course.course_number} ({s1}-{e1}) vs "
                        f"{sc2.course.course_number} ({s2}-{e2})"
                    )

    # Lecture teacher consistency per division
    div_subj_teachers = defaultdict(set)
    for sc in solution:
        if sc.course.course_type == 'LECTURE' and sc.division:
            div_subj_teachers[(sc.division.id, sc.course.course_number)].add(
                sc.instructor.uid)

    for key, teachers in div_subj_teachers.items():
        if len(teachers) > 1:
            try:
                div = Division.objects.get(id=key[0])
                div_name = div.division_name
            except Exception:
                div_name = str(key[0])
            conflicts.append(
                f"Multiple teachers for {div_name} {key[1]}")

    # Lab teacher consistency per batch
    batch_subj_teachers = defaultdict(set)
    for sc in solution:
        if sc.course.course_type == 'LAB' and sc.batch:
            batch_subj_teachers[(sc.batch.id, sc.course.course_number)].add(
                sc.instructor.uid)

    for key, teachers in batch_subj_teachers.items():
        if len(teachers) > 1:
            try:
                batch = Batch.objects.get(id=key[0])
                batch_name = batch.batch_name
            except Exception:
                batch_name = str(key[0])
            conflicts.append(
                f"Multiple teachers for batch {batch_name} {key[1]}")

    # Lab room consistency per batch
    batch_subj_rooms = defaultdict(set)
    for sc in solution:
        if sc.course.course_type == 'LAB' and sc.batch:
            batch_subj_rooms[(sc.batch.id, sc.course.course_number)].add(
                sc.room.r_number)

    for key, rooms in batch_subj_rooms.items():
        if len(rooms) > 1:
            try:
                batch = Batch.objects.get(id=key[0])
                batch_name = batch.batch_name
            except Exception:
                batch_name = str(key[0])
            conflicts.append(
                f"Batch {batch_name} {key[1]} uses multiple rooms: {rooms}")

    # Elective same-group same-slot check
    # CC and IS for the same group must occupy the SAME slot on each session day
    elec_group_slots = defaultdict(list)   # group → [(day, s, e, course_number)]
    for sc in solution:
        if sc.section.is_elective and sc.section.elective_group:
            s, e = _parse(sc.meeting_time.time)
            elec_group_slots[sc.section.elective_group].append(
                (sc.meeting_time.day, s, e, sc.course.course_number))

    for group, slot_list in elec_group_slots.items():
        # Group by day
        by_day = defaultdict(list)
        for day, s, e, cnum in slot_list:
            by_day[day].append((s, e, cnum))
        for day, entries in by_day.items():
            times = set((s, e) for s, e, _ in entries)
            if len(times) > 1:
                conflicts.append(
                    f"Elective group {group} on {day} has mismatched slots: {times}")

    return conflicts


# ── Django views ──────────────────────────────────────────────────────────────

def timetable(request):
    print("\n" + "=" * 70)
    print("🚀 TIMETABLE GENERATOR — ELECTIVES + LOAD BALANCED + ZERO CONFLICT")
    print("=" * 70)

    start_time = time_module.time()
    data = TimetableData()

    best_solution  = None
    best_conflicts = float('inf')
    attempt        = 0

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n📊 Attempt {attempt}/{MAX_RETRIES}")

        generator = TimetableGenerator(data)
        solution  = generator.generate()
        conflicts = verify_timetable(solution)

        print(f"  → {len(solution)} classes, {len(conflicts)} conflicts")

        if len(conflicts) < best_conflicts:
            best_conflicts = len(conflicts)
            best_solution  = solution

            if best_conflicts == 0:
                print(f"\n✅ PERFECT TIMETABLE on attempt {attempt}!")
                break

    elapsed         = round(time_module.time() - start_time, 2)
    final_conflicts = verify_timetable(best_solution) if best_solution else []

    print("\n" + "=" * 70)
    print(f"🏁 FINAL: {len(best_solution)} classes, "
          f"{len(final_conflicts)} conflicts, {elapsed}s")
    if final_conflicts:
        print("Remaining conflicts:")
        for c in final_conflicts[:15]:
            print(f"  - {c}")
    else:
        print("✅ ZERO CONFLICTS — PERFECT TIMETABLE!")
    print("=" * 70)

    context = {
        'schedule':    best_solution,
        'sections':    data.sections,
        'times':       data.meeting_times,
        'generations': attempt,
        'fitness':     (1.0 if len(final_conflicts) == 0
                        else round(1 / (1 + len(final_conflicts)), 4)),
        'conflicts':   len(final_conflicts),
        'verified':    len(final_conflicts) == 0,
        'time_taken':  elapsed,
    }

    return render(request, 'gentimetable.html', context)


# ── All other views (unchanged) ──────────────────────────────────────────────

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
        'total_divisions':   Division.objects.count(),
        'total_batches':     Batch.objects.count(),
        'total_instructors': Instructor.objects.count(),
        'total_rooms':       Room.objects.count(),
        'total_courses':     Course.objects.count(),
        'total_sections':    Section.objects.count(),
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
    return render(request, 'deptlist.html',
                  {'departments': Department.objects.all()})

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
    return render(request, 'divisionlist.html',
                  {'divisions': Division.objects.all()})

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
    return render(request, 'batchlist.html',
                  {'batches': Batch.objects.all()})

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
    return render(request, 'courseslist.html',
                  {'courses': Course.objects.all()})

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
    return render(request, 'inslist.html',
                  {'instructors': Instructor.objects.all()})

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
    return render(request, 'roomslist.html',
                  {'rooms': Room.objects.all()})

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
    return render(request, 'mtlist.html',
                  {'meeting_times': MeetingTime.objects.all()})

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
    return render(request, 'seclist.html',
                  {'sections': Section.objects.all()})

@login_required
def delete_section(request, pk):
    if request.method == 'POST':
        Section.objects.filter(pk=pk).delete()
        return redirect('editsection')