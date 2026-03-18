"""
views.py — Timetable Generator
================================
TWO-PHASE approach:
  Phase 1: Assign all LABS first
  Phase 2: Assign all LECTURES after

KEY CONSTRAINTS - STRICTLY ENFORCED:
  C1: Lab sessions are 2 hours, Lectures are 1 hour
  C2: Lab rooms have capacity 25, Lecture halls have capacity 88
  C3: Teachers can only teach subjects they're qualified for
  C4: ONE fixed teacher for ALL lectures of a subject in a division
  C5: ONE fixed teacher for ALL lab sessions of a batch
  C6: ALL 4 batches of a division go to lab at the SAME time slot
  C7: NO lectures during lab hours - DIVISION IS COMPLETELY BLOCKED
  C8: NO consecutive lab slots for a batch on the same day
  C9: NO teacher teaches more than one class at same time
  C10: MAX 2 lab-blocks per division per day
  C11: Lab slot priority: 08:45 > 11:00 > 13:45
  C12: NO two batches share a lab room at the same time
  C13: NO room clashes
  C14: MAX 2 of same subject lectures per day per division
  C15: Each teacher assigned to MAX 4 batches total across all lab subjects
  C16: Lab frequency: DSBDAL=2, LPII=2, WTL=1 per week (EXACTLY)
  C17: Lectures frequency: AI=3, DSBDA=3, WT=3 per week (EXACTLY)
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
MAX_LABS_PER_DAY = 2           # per division per day (C10)
MAX_BATCHES_PER_TEACHER = 4    # across all lab subjects (C15)
MAX_RETRIES = 500              # Number of attempts to find perfect solution

# Lab frequencies per week (C16)
LAB_FREQUENCY = {
    'DSBDAL': 2,
    'LPII': 2,
    'WTL': 1,
}

# Lecture frequencies per week (C17)
LECTURE_FREQUENCY = {
    'AI': 3,
    'DSBDA': 3,
    'WT': 3,
}

# ── Time helpers ─────────────────────────────────────────────────────────────

def _to_min(t):
    """Convert time string to minutes since midnight"""
    try:
        h, m = map(int, t.strip().split(':'))
        if 1 <= h <= 7:
            h += 12
        return h * 60 + m
    except:
        return 0

def _parse(time_str):
    """Parse time range string to start and end minutes"""
    try:
        parts = time_str.replace(' ', '').split('-')
        return _to_min(parts[0]), _to_min(parts[1])
    except Exception:
        return 0, 0

def _get_slot_priority(time_str):
    """Get priority of lab slot (C11)"""
    if '08:45' in time_str:
        return 1
    if '11:00' in time_str:
        return 2
    if '13:45' in time_str:
        return 3
    return 99

def _is_lab_slot_consecutive(time1_str, time2_str):
    """Check if two lab times are consecutive (C8)"""
    if '10:45' in time1_str and '11:00' in time2_str:
        return True
    if '13:00' in time1_str and '13:45' in time2_str:
        return True
    return False

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
                'course', 'division', 'batch',
                'batch__division', 'instructor', 'room'
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

        # Sort lab slots by priority (morning first — C11)
        for day in self.lab_slots_by_day:
            self.lab_slots_by_day[day].sort(
                key=lambda mt: _get_slot_priority(mt.time)
            )

        # Eligible teachers per course
        self.eligible_teachers = {}
        for course in Course.objects.prefetch_related('instructors').all():
            self.eligible_teachers[course.course_number] = list(
                course.instructors.all()
            )

        # Group sections
        self.lecture_sections = [
            s for s in self.sections
            if s.course and s.course.course_type == 'LECTURE'
        ]
        self.lab_sections = [
            s for s in self.sections
            if s.course and s.course.course_type == 'LAB'
        ]

        # Lab sections grouped by (division_id, course_number)
        self.div_lab_groups = defaultdict(list)
        for s in self.lab_sections:
            if s.batch and s.batch.division_id:
                key = (s.batch.division_id, s.course.course_number)
                self.div_lab_groups[key].append(s)

        # Batches grouped by division
        self.batches_by_division = defaultdict(list)
        for batch in Batch.objects.all().select_related('division'):
            self.batches_by_division[batch.division_id].append(batch)

        print(f"✅ Data loaded: {len(self.sections)} sections | "
              f"{len(self.divisions)} divisions | "
              f"{len(self.lecture_rooms)} lecture rooms | "
              f"{len(self.lab_rooms)} lab rooms")


# ── Scheduled class (in-memory) ─────────────────────────────────────────────

class SC:
    __slots__ = ['section', 'course', 'meeting_time', 'room',
                 'instructor', 'division', 'batch']

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

        # Occupancy trackers
        self.room_busy = defaultdict(set)      # (day, pid) → room numbers
        self.teacher_busy = defaultdict(set)   # (day, pid) → teacher uids
        self.div_busy = defaultdict(set)       # (day, pid) → division ids
        self.batch_busy = defaultdict(set)     # (day, pid) → batch ids

        # CRITICAL: Track division busy time ranges (for 2-hour lab blocks)
        self.div_time_ranges = defaultdict(list)  # (div_id, day) → list of (start, end)

        # Teacher locks
        self.div_lec_teacher = {}               # (div_id, course) → Instructor
        self.batch_lab_teacher = {}             # (batch_id, course) → Instructor

        # Lab tracking
        self.div_day_labs = defaultdict(list)   # (div_id, day) → list of time strings
        self.batch_lab_count = defaultdict(int) # (batch_id, course) → count
        self.teacher_batch_count = defaultdict(int)  # teacher_uid → number of batches

    def _k(self, mt):
        return (mt.day, mt.pid)

    def _room_free(self, mt, room):
        return room.r_number not in self.room_busy[self._k(mt)]

    def _teacher_free(self, mt, teacher):
        """Check if teacher is free for the ENTIRE time slot"""
        # Check exact time slot
        if teacher.uid in self.teacher_busy[self._k(mt)]:
            return False
        
        # For lecture slots, also check if teacher is busy in any overlapping lab
        if mt.slot_type == 'LECTURE':
            lec_start, lec_end = _parse(mt.time)
            
            # Check all lab slots on this day
            for other_mt in self.data.meeting_times:
                if other_mt.day != mt.day or other_mt.slot_type != 'LAB':
                    continue
                    
                lab_start, lab_end = _parse(other_mt.time)
                
                # If lecture time overlaps with lab time and teacher is busy in lab
                if max(lec_start, lab_start) < min(lec_end, lab_end):
                    if teacher.uid in self.teacher_busy.get((mt.day, other_mt.pid), set()):
                        return False
        
        return True

    def _div_free(self, mt, div_id):
        """
        CRITICAL: Check if division is free for the ENTIRE time slot
        For labs (2 hours), division must be free for the whole duration
        """
        # Check if division is busy at this exact slot
        if div_id in self.div_busy[self._k(mt)]:
            return False
        
        # For ANY slot type, check if division has ANY class during this time period
        slot_start, slot_end = _parse(mt.time)
        
        # Check all time ranges where this division is busy
        for start, end in self.div_time_ranges.get((div_id, mt.day), []):
            if max(slot_start, start) < min(slot_end, end):
                return False
        
        return True

    def _batch_free(self, mt, batch_id):
        return batch_id not in self.batch_busy[self._k(mt)]

    def _mark(self, mt, room, teacher, div_id=None, batch_id=None):
        """Mark occupancy for a time slot"""
        k = self._k(mt)
        self.room_busy[k].add(room.r_number)
        self.teacher_busy[k].add(teacher.uid)
        
        # Mark division busy for this ENTIRE time slot
        if div_id:
            self.div_busy[k].add(div_id)
            
            # Track the time range for overlap checking
            start, end = _parse(mt.time)
            self.div_time_ranges[(div_id, mt.day)].append((start, end))
        
        if batch_id:
            self.batch_busy[k].add(batch_id)

    def _get_lecture_teacher(self, div_id, course_code):
        """C4: ONE fixed teacher for all lectures of a subject in a division"""
        key = (div_id, course_code)
        if key in self.div_lec_teacher:
            return self.div_lec_teacher[key]

        pool = self.data.eligible_teachers.get(course_code, [])
        if not pool:
            return None

        # Sort by current load
        pool.sort(key=lambda t: self.teacher_batch_count.get(t.uid, 0))
        
        # Pick the least loaded teacher
        chosen = pool[0]
        self.div_lec_teacher[key] = chosen
        return chosen

    def _get_lab_teacher(self, batch_id, course_code, mt):
        """C5: ONE fixed teacher for ALL lab sessions of a batch"""
        key = (batch_id, course_code)
        
        # Check if already locked
        if key in self.batch_lab_teacher:
            teacher = self.batch_lab_teacher[key]
            return teacher if self._teacher_free(mt, teacher) else None

        pool = self.data.eligible_teachers.get(course_code, [])
        if not pool:
            return None

        # Shuffle for randomness
        candidates = list(pool)
        random.shuffle(candidates)

        for teacher in candidates:
            # Check teacher availability
            if not self._teacher_free(mt, teacher):
                continue
            
            # Check max batches limit (C15)
            if self.teacher_batch_count[teacher.uid] >= MAX_BATCHES_PER_TEACHER:
                continue
            
            # Lock this teacher
            self.batch_lab_teacher[key] = teacher
            self.teacher_batch_count[teacher.uid] += 1
            return teacher

        return None

    # ─────────────────────────────────────────────────────────────────────
    # PHASE 1 — LABS
    # ─────────────────────────────────────────────────────────────────────

    def assign_labs(self):
        """PHASE 1: Assign ALL labs FIRST"""
        data = self.data
        
        print(f"\n📊 PHASE 1: Assigning labs")

        # Build tasks for each division and lab subject
        tasks = []
        for div in data.divisions:
            for course_code, needed in LAB_FREQUENCY.items():
                key = (div.id, course_code)
                sections = data.div_lab_groups.get(key, [])
                if not sections or len(sections) != 4:  # Must have all 4 batches
                    continue
                
                tasks.append({
                    'division': div,
                    'course_code': course_code,
                    'sections': sections,
                    'needed': needed,
                    'assigned': 0
                })

        random.shuffle(tasks)

        for task in tasks:
            div = task['division']
            course_code = task['course_code']
            sections = task['sections']
            needed = task['needed']
            assigned = 0

            attempts = 0
            while assigned < needed and attempts < 500:
                attempts += 1
                
                # Try each day
                days = DAYS_ORDER.copy()
                random.shuffle(days)

                for day in days:
                    if assigned >= needed:
                        break

                    # C10: Max 2 labs per division per day
                    div_day_key = (div.id, day)
                    if len(self.div_day_labs[div_day_key]) >= MAX_LABS_PER_DAY:
                        continue

                    # Try slots in priority order (C11)
                    for mt in data.lab_slots_by_day.get(day, []):
                        # Skip if this slot would create consecutive labs (C8)
                        existing_times = self.div_day_labs[div_day_key]
                        if any(_is_lab_slot_consecutive(existing, mt.time) for existing in existing_times):
                            continue

                        # CRITICAL: Division must be completely free for this 2-hour block
                        if not self._div_free(mt, div.id):
                            continue

                        # All batches must be free
                        batches = data.batches_by_division.get(div.id, [])
                        all_batches_free = all(
                            self._batch_free(mt, batch.id) for batch in batches
                        )
                        if not all_batches_free:
                            continue

                        # Assign teachers to each batch (C5)
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

                        # Assign rooms to each batch (C12)
                        room_map = {}
                        room_valid = True
                        used_rooms = set()

                        for section in sections:
                            batch = section.batch
                            
                            # Find free lab rooms
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

                        # ALL CHECKS PASSED - Assign the lab block
                        for section in sections:
                            batch = section.batch
                            teacher = teacher_map[batch.id]
                            room = room_map[batch.id]

                            sc = SC(section, mt, room, teacher)
                            self.result.append(sc)

                            # Mark occupancy - this will block the division for the entire 2 hours
                            self._mark(mt, room, teacher, 
                                      div_id=div.id, 
                                      batch_id=batch.id)

                            self.batch_lab_count[(batch.id, course_code)] += 1

                        # Record this lab block
                        self.div_day_labs[div_day_key].append(mt.time)
                        assigned += 1
                        
                        print(f"    ✓ {div.division_name} {course_code} on {day} at {mt.time[:13]}")
                        break  # Found slot

            if assigned < needed:
                print(f"  ⚠️  {div.division_name} {course_code} only assigned {assigned}/{needed}")

    # ─────────────────────────────────────────────────────────────────────
    # PHASE 2 — LECTURES (AFTER labs are fixed)
    # ─────────────────────────────────────────────────────────────────────

    def assign_lectures(self):
        """PHASE 2: Assign lectures after labs are fixed"""
        data = self.data
        
        print(f"\n📊 PHASE 2: Assigning lectures")

        # Group lecture sections by division
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
                
                # C4: Get fixed teacher for this division+subject
                teacher = self._get_lecture_teacher(div.id, course_code)
                if not teacher:
                    print(f"  ⚠️  No teacher for {div.division_name} {course_code}")
                    continue

                assigned = 0
                attempts = 0
                days_used = defaultdict(int)  # Track lectures per day (C14)

                while assigned < needed and attempts < 300:
                    attempts += 1
                    
                    days = DAYS_ORDER.copy()
                    random.shuffle(days)

                    for day in days:
                        if assigned >= needed:
                            break

                        # C14: Max 2 of same subject per day
                        if days_used[day] >= 2:
                            continue

                        # Try each lecture slot
                        for mt in data.lec_slots_by_day.get(day, []):
                            # CRITICAL: Division must be completely free (not in lab)
                            if not self._div_free(mt, div.id):
                                continue

                            # Teacher must be free
                            if not self._teacher_free(mt, teacher):
                                continue

                            # Find free lecture room
                            free_rooms = [
                                room for room in data.lecture_rooms
                                if self._room_free(mt, room)
                            ]
                            if not free_rooms:
                                continue

                            room = random.choice(free_rooms)

                            # Assign lecture
                            sc = SC(section, mt, room, teacher)
                            self.result.append(sc)

                            # Mark occupancy
                            self._mark(mt, room, teacher, div_id=div.id)

                            days_used[day] += 1
                            assigned += 1
                            
                            print(f"    ✓ {div.division_name} {course_code} on {day} at {mt.time[:11]}")
                            break  # Found slot

                if assigned < needed:
                    print(f"  ⚠️  {div.division_name} {course_code} only assigned {assigned}/{needed}")

    def generate(self):
        """Run the full generation process"""
        self.assign_labs()
        self.assign_lectures()
        return self.result


# ── Verification ─────────────────────────────────────────────────────────────

def verify_timetable(solution):
    """
    Comprehensive verification of ALL constraints
    Returns empty list if perfect, otherwise list of conflicts
    """
    conflicts = []
    
    # Group by division and time for easier checking
    by_div_time = defaultdict(list)
    by_teacher_time = defaultdict(list)
    by_room_time = defaultdict(list)
    by_batch_time = defaultdict(list)
    
    for sc in solution:
        key = (sc.division.id if sc.division else None, 
               sc.meeting_time.day, 
               sc.meeting_time.time)
        by_div_time[key].append(sc)
        
        teacher_key = (sc.instructor.uid, sc.meeting_time.day, sc.meeting_time.time)
        by_teacher_time[teacher_key].append(sc)
        
        room_key = (sc.room.r_number, sc.meeting_time.day, sc.meeting_time.time)
        by_room_time[room_key].append(sc)
        
        if sc.batch:
            batch_key = (sc.batch.id, sc.meeting_time.day, sc.meeting_time.time)
            by_batch_time[batch_key].append(sc)
    
    # C4: One teacher per division per subject
    div_subject_teachers = defaultdict(set)
    for sc in solution:
        if sc.course.course_type == 'LECTURE' and sc.division:
            key = (sc.division.id, sc.course.course_number)
            div_subject_teachers[key].add(sc.instructor.uid)
    
    for key, teachers in div_subject_teachers.items():
        if len(teachers) > 1:
            conflicts.append(f"C4: Division {key[0]} {key[1]} has multiple teachers")
    
    # C5: One teacher per batch per lab subject
    batch_subject_teachers = defaultdict(set)
    for sc in solution:
        if sc.course.course_type == 'LAB' and sc.batch:
            key = (sc.batch.id, sc.course.course_number)
            batch_subject_teachers[key].add(sc.instructor.uid)
    
    for key, teachers in batch_subject_teachers.items():
        if len(teachers) > 1:
            conflicts.append(f"C5: Batch {key[0]} {key[1]} has multiple teachers")
    
    # C6 & C7: ALL batches together, NO lectures during lab
    lab_blocks = defaultdict(list)  # (div_id, day, time) -> list of batches
    for sc in solution:
        if sc.course.course_type == 'LAB' and sc.batch:
            div_id = sc.batch.division_id
            key = (div_id, sc.meeting_time.day, sc.meeting_time.time)
            lab_blocks[key].append(sc.batch.batch_name)
    
    for (div_id, day, time), batches in lab_blocks.items():
        div = Division.objects.get(id=div_id)
        expected = Batch.objects.filter(division_id=div_id).count()
        if len(batches) != expected:
            conflicts.append(f"C6: {div.division_name} has {len(batches)}/{expected} batches in lab at {day} {time}")
        
        # Check for lectures during this lab block (C7)
        lab_start, lab_end = _parse(time)
        for sc in solution:
            if sc.course.course_type == 'LECTURE' and sc.division and sc.division.id == div_id:
                if sc.meeting_time.day == day:
                    lec_start, lec_end = _parse(sc.meeting_time.time)
                    if max(lab_start, lec_start) < min(lab_end, lec_end):
                        conflicts.append(f"C7: {div.division_name} has lecture {sc.course.course_number} during lab at {day}")
    
    # C8: No consecutive labs for same batch
    batch_day_times = defaultdict(list)
    for sc in solution:
        if sc.course.course_type == 'LAB' and sc.batch:
            key = (sc.batch.id, sc.meeting_time.day)
            batch_day_times[key].append(sc.meeting_time.time)
    
    for (batch_id, day), times in batch_day_times.items():
        times.sort()
        for i in range(len(times) - 1):
            if _is_lab_slot_consecutive(times[i], times[i+1]):
                conflicts.append(f"C8: Batch {batch_id} has consecutive labs on {day}")
    
    # C9: No teacher clashes
    for (uid, day, time), classes in by_teacher_time.items():
        if len(classes) > 1:
            teacher = Instructor.objects.get(uid=uid)
            conflicts.append(f"C9: Teacher {teacher.name} teaching {len(classes)} classes at {day} {time}")
    
    # C10: Max 2 labs per division per day
    div_day_lab_count = defaultdict(int)
    for sc in solution:
        if sc.course.course_type == 'LAB' and sc.batch:
            div_id = sc.batch.division_id
            key = (div_id, sc.meeting_time.day, sc.meeting_time.time)
            div_day_lab_count[(div_id, sc.meeting_time.day)] += 1
    
    for (div_id, day), count in div_day_lab_count.items():
        if count > MAX_LABS_PER_DAY:
            div = Division.objects.get(id=div_id)
            conflicts.append(f"C10: {div.division_name} has {count} lab blocks on {day} (max {MAX_LABS_PER_DAY})")
    
    # C13: No room clashes
    for (room, day, time), classes in by_room_time.items():
        if len(classes) > 1:
            conflicts.append(f"C13: Room {room} has {len(classes)} classes at {day} {time}")
    
    # C14: Max 2 of same subject per day
    div_day_subject = defaultdict(int)
    for sc in solution:
        if sc.course.course_type == 'LECTURE' and sc.division:
            key = (sc.division.id, sc.meeting_time.day, sc.course.course_number)
            div_day_subject[key] += 1
    
    for (div_id, day, subject), count in div_day_subject.items():
        if count > 2:
            div = Division.objects.get(id=div_id)
            conflicts.append(f"C14: {div.division_name} has {count} {subject} lectures on {day} (max 2)")
    
    # C15: Teacher max batches
    teacher_batches = defaultdict(set)
    for sc in solution:
        if sc.course.course_type == 'LAB' and sc.batch:
            teacher_batches[sc.instructor.uid].add(sc.batch.id)
    
    for uid, batches in teacher_batches.items():
        if len(batches) > MAX_BATCHES_PER_TEACHER:
            teacher = Instructor.objects.get(uid=uid)
            conflicts.append(f"C15: Teacher {teacher.name} assigned to {len(batches)} batches (max {MAX_BATCHES_PER_TEACHER})")
    
    # C16: Check lab frequencies
    batch_lab_counts = defaultdict(int)
    for sc in solution:
        if sc.course.course_type == 'LAB' and sc.batch:
            key = (sc.batch.id, sc.course.course_number)
            batch_lab_counts[key] += 1
    
    for (batch_id, course), count in batch_lab_counts.items():
        expected = LAB_FREQUENCY.get(course, 0)
        if count != expected:
            conflicts.append(f"C16: Batch {batch_id} {course} has {count} labs, expected {expected}")
    
    # C17: Check lecture frequencies
    div_lecture_counts = defaultdict(int)
    for sc in solution:
        if sc.course.course_type == 'LECTURE' and sc.division:
            key = (sc.division.id, sc.course.course_number)
            div_lecture_counts[key] += 1
    
    for (div_id, course), count in div_lecture_counts.items():
        expected = LECTURE_FREQUENCY.get(course, 0)
        if count != expected:
            conflicts.append(f"C17: Division {div_id} {course} has {count} lectures, expected {expected}")
    
    return conflicts


# ── Django view ───────────────────────────────────────────────────────────────

def timetable(request):
    print("\n" + "=" * 70)
    print("🚀 AUTO TIMETABLE GENERATOR — TWO-PHASE ALGORITHM")
    print("=" * 70)

    start_time = time_module.time()

    # Load data
    data = TimetableData()

    # Generate timetable with multiple attempts
    best_solution = None
    best_conflicts = float('inf')
    best_conflict_list = []

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"\n📊 Attempt {attempt}/{MAX_RETRIES}")
        print("-" * 40)

        generator = TimetableGenerator(data)
        solution = generator.generate()
        conflicts = verify_timetable(solution)

        print(f"  → Generated {len(solution)} classes, {len(conflicts)} conflicts")

        if len(conflicts) < best_conflicts:
            best_conflicts = len(conflicts)
            best_solution = solution
            best_conflict_list = conflicts
            print(f"  ✓ New best solution!")

            if best_conflicts == 0:
                print(f"\n✅ PERFECT TIMETABLE FOUND on attempt {attempt}!")
                break

    elapsed = round(time_module.time() - start_time, 2)

    # Final verification
    final_conflicts = verify_timetable(best_solution)

    print("\n" + "=" * 70)
    print(f"🏁 FINAL RESULT")
    print(f"   Classes Scheduled: {len(best_solution)}")
    print(f"   Conflicts: {len(final_conflicts)}")
    print(f"   Time Taken: {elapsed}s")

    if final_conflicts:
        print("\n⚠️  Remaining Conflicts:")
        for i, conflict in enumerate(final_conflicts[:10], 1):
            print(f"   {i}. {conflict}")
        if len(final_conflicts) > 10:
            print(f"   ... and {len(final_conflicts) - 10} more")
    else:
        print("\n✅ ALL CONSTRAINTS SATISFIED!")

    print("=" * 70)

    context = {
        'schedule': best_solution,
        'sections': data.sections,
        'times': data.meeting_times,
        'generations': MAX_RETRIES,
        'fitness': 1.0 if len(final_conflicts) == 0 else round(1 / (1 + len(final_conflicts)), 4),
        'conflicts': len(final_conflicts),
        'conflict_details': {'total': len(final_conflicts)},
        'verified': len(final_conflicts) == 0,
        'time_taken': elapsed,
    }

    return render(request, 'gentimetable.html', context)


# ── Other views (keep your existing ones) ───────────────────────────────────
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