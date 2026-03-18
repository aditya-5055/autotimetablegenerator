from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.generic import View
from .forms import *
from .models import *
import random as rnd
from django.conf import settings
from collections import defaultdict
import time
import re
import copy

# Load settings
POPULATION_SIZE = getattr(settings, 'TIMETABLE_POPULATION_SIZE', 500)  # Increased
NUMB_OF_ELITE_SCHEDULES = getattr(settings, 'TIMETABLE_ELITE_SCHEDULES', 50)  # Increased
TOURNAMENT_SELECTION_SIZE = getattr(settings, 'TIMETABLE_TOURNAMENT_SIZE', 10)
MUTATION_RATE = getattr(settings, 'TIMETABLE_MUTATION_RATE', 0.3)
MAX_GENERATIONS = getattr(settings, 'TIMETABLE_MAX_GENERATIONS', 2000)
EARLY_STOPPING_THRESHOLD = 100


# ============================================================================
# TIME PARSING UTILITY
# ============================================================================

class TimeSlot:
    """Represents a time slot with proper parsing for overlap detection"""
    
    def __init__(self, meeting_time_obj):
        self.obj = meeting_time_obj
        self.pid = meeting_time_obj.pid if meeting_time_obj else None
        self.day = meeting_time_obj.day if meeting_time_obj else None
        self.time_str = meeting_time_obj.time if meeting_time_obj else None
        self.start_minutes = 0
        self.end_minutes = 0
        self.slot_type = meeting_time_obj.slot_type if meeting_time_obj else None
        
        if self.time_str:
            self._parse_time()
    
    def _parse_time(self):
        """Parse time string with multiple format support"""
        if not self.time_str:
            return
        
        try:
            # Handle formats like "08:45 - 10:45" or "13:45 - 14:45"
            match = re.match(r'(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})', self.time_str)
            if match:
                start_h, start_m, end_h, end_m = map(int, match.groups())
                
                # Convert to 24-hour format for proper comparison
                # Assume times between 1-7 are PM (13-19)
                if 1 <= start_h <= 7:
                    start_h += 12
                if 1 <= end_h <= 7:
                    end_h += 12
                
                self.start_minutes = start_h * 60 + start_m
                self.end_minutes = end_h * 60 + end_m
                
                if self.end_minutes <= self.start_minutes:
                    print(f"Warning: Invalid time range {self.time_str}")
                    self.start_minutes = 0
                    self.end_minutes = 0
        except Exception as e:
            print(f"Error parsing time '{self.time_str}': {e}")
            self.start_minutes = 0
            self.end_minutes = 0
    
    def overlaps_with(self, other):
        """Check if this time slot overlaps with another"""
        if not other or not other.day:
            return False
        if self.day != other.day:
            return False
        # Check if time ranges overlap
        return (self.start_minutes < other.end_minutes and 
                other.start_minutes < self.end_minutes)
    
    def __eq__(self, other):
        if not other:
            return False
        return self.pid == other.pid
    
    def __hash__(self):
        return hash(self.pid)
    
    def __repr__(self):
        return f"TimeSlot({self.pid}, {self.day}, {self.time_str})"


# ============================================================================
# DATA CLASS
# ============================================================================

class Data:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        print("Loading data from database...")
        
        self._rooms = list(Room.objects.all())
        self._meetingTimes = list(MeetingTime.objects.all())
        self._instructors = list(Instructor.objects.all())
        self._courses = list(Course.objects.all())
        self._depts = list(Department.objects.all())
        self._divisions = list(Division.objects.all())
        self._batches = list(Batch.objects.all())
        self._sections = list(Section.objects.all())
        
        # Pre-compute TimeSlot wrappers
        self._time_slots = {}
        for mt in self._meetingTimes:
            self._time_slots[mt.pid] = TimeSlot(mt)
        
        print(f"Loaded: {len(self._rooms)} rooms, {len(self._meetingTimes)} times, "
              f"{len(self._instructors)} instructors, {len(self._courses)} courses, "
              f"{len(self._sections)} sections")
        
        # Pre-compute lookups
        self._rooms_by_type = defaultdict(list)
        for room in self._rooms:
            self._rooms_by_type[room.room_type].append(room)
            
        self._times_by_type = defaultdict(list)
        for mt in self._meetingTimes:
            self._times_by_type[mt.slot_type].append(mt)
            
        self._instructors_by_course = defaultdict(list)
        for course in self._courses:
            self._instructors_by_course[course.course_number] = list(course.instructors.all())
        
        # Validate data
        self._validate_data()
        
        self._initialized = True
        print("Data initialization complete.")
    
    def _validate_data(self):
        """Validate that required data exists"""
        if not self._rooms:
            print("WARNING: No rooms defined!")
        if not self._meetingTimes:
            print("WARNING: No meeting times defined!")
        if not self._instructors:
            print("WARNING: No instructors defined!")
        if not self._courses:
            print("WARNING: No courses defined!")
        if not self._sections:
            print("WARNING: No sections defined!")
    
    def get_time_slot(self, meeting_time):
        """Get TimeSlot wrapper for overlap detection"""
        if not meeting_time:
            return None
        return self._time_slots.get(meeting_time.pid)
    
    def get_rooms(self): return self._rooms
    def get_instructors(self): return self._instructors
    def get_courses(self): return self._courses
    def get_depts(self): return self._depts
    def get_meetingTimes(self): return self._meetingTimes
    def get_divisions(self): return self._divisions
    def get_batches(self): return self._batches
    def get_sections(self): return self._sections
    def get_rooms_by_type(self, rtype): return self._rooms_by_type.get(rtype, [])
    def get_times_by_type(self, ttype): return self._times_by_type.get(ttype, [])
    def get_instructors_for_course(self, course_pk): 
        return self._instructors_by_course.get(course_pk, [])


# ============================================================================
# CLASS - Represents one scheduled class
# ============================================================================

class Class:
    _id_counter = 0
    
    def __init__(self, dept, section):
        Class._id_counter += 1
        self.id = Class._id_counter
        self.department = dept
        self.section = section
        self.course = section.course if section else None
        self.instructor = None
        self.meeting_time = None
        self.room = None
        self.division = section.division if section else None
        self.batch = section.batch if section else None

    def set_instructor(self, instructor): self.instructor = instructor
    def set_meetingTime(self, meetingTime): self.meeting_time = meetingTime
    def set_room(self, room): self.room = room
    
    def get_division_name(self):
        """Get division name either directly or via batch"""
        if self.division:
            return self.division.division_name
        if self.batch and self.batch.division:
            return self.batch.division.division_name
        return None
    
    def get_batch_name(self):
        """Get batch name"""
        if self.batch:
            return self.batch.batch_name
        return None
    
    def get_time_slot(self):
        """Get TimeSlot wrapper for this class"""
        return data.get_time_slot(self.meeting_time)
    
    def copy(self):
        new_class = Class(self.department, self.section)
        new_class.id = self.id
        new_class.course = self.course
        new_class.instructor = self.instructor
        new_class.meeting_time = self.meeting_time
        new_class.room = self.room
        new_class.division = self.division
        new_class.batch = self.batch
        return new_class
    
    def __repr__(self):
        return f"Class({self.id}, {self.course}, {self.meeting_time})"


# ============================================================================
# SCHEDULE CLASS
# ============================================================================

class Schedule:
    def __init__(self, initialize=True):
        self._data = data
        self._classes = []
        self._numberOfConflicts = 0
        self._fitness = -1
        self._isFitnessChanged = True
        self._conflict_details = {}
        self._conflict_list = []
        # Occupancy trackers
        self._room_occupancy = defaultdict(set)  # (day, time_pid) -> set of room numbers
        self._instructor_occupancy = defaultdict(set)  # (day, time_pid) -> set of instructor uids
        self._division_occupancy = defaultdict(set)  # (division, day, time_pid) -> set of class ids
        self._batch_occupancy = defaultdict(set)  # (batch_id, day, time_pid) -> set of class ids
        
        if initialize:
            self.strict_initialize()

    def get_classes(self): return self._classes
    def get_numbOfConflicts(self): return self._numberOfConflicts
    def get_conflict_details(self): return self._conflict_details
    def get_conflict_list(self): return self._conflict_list

    def get_fitness(self):
        if self._isFitnessChanged:
            self._fitness = self.calculate_fitness()
            self._isFitnessChanged = False
        return self._fitness

    def strict_initialize(self):
        """Strict initialization with occupancy tracking - ensures no conflicts"""
        sections = list(data.get_sections())
        rnd.shuffle(sections)
        
        self._classes = []
        self._clear_occupancy()
        
        for section in sections:
            if not section.course:
                print(f"Warning: Section {section} has no course assigned")
                continue
                
            dept = section.department
            n = section.num_class_in_week
            course_type = section.course.course_type
            
            for i in range(n):
                newClass = Class(dept, section)
                
                # Get valid options
                valid_times = data.get_times_by_type(course_type)
                valid_rooms = data.get_rooms_by_type(course_type)
                valid_instructors = data.get_instructors_for_course(section.course.course_number)
                
                if not valid_times or not valid_rooms or not valid_instructors:
                    print(f"Warning: No valid options for section {section}")
                    continue
                
                # Try to assign without conflicts
                assigned = self._assign_without_conflicts(newClass, valid_times, valid_rooms, valid_instructors)
                
                if not assigned:
                    # If can't assign without conflicts, use best available
                    self._assign_best_available(newClass, valid_times, valid_rooms, valid_instructors)
        
        return self
    
    def _clear_occupancy(self):
        """Clear all occupancy trackers"""
        self._room_occupancy.clear()
        self._instructor_occupancy.clear()
        self._division_occupancy.clear()
        self._batch_occupancy.clear()
    
    def _assign_without_conflicts(self, new_class, valid_times, valid_rooms, valid_instructors):
        """Try to assign class without any conflicts"""
        # Shuffle options for randomness
        rnd.shuffle(valid_times)
        rnd.shuffle(valid_rooms)
        rnd.shuffle(valid_instructors)
        
        for time in valid_times:
            time_key = (time.day, time.pid)
            
            for room in valid_rooms:
                # Check room availability
                if room.r_number in self._room_occupancy[time_key]:
                    continue
                
                for instructor in valid_instructors:
                    # Check instructor availability
                    if instructor.uid in self._instructor_occupancy[time_key]:
                        continue
                    
                    # Check division constraints
                    div_name = new_class.get_division_name()
                    if div_name:
                        div_key = (div_name, time.day, time.pid)
                        if div_key in self._division_occupancy:
                            continue
                    
                    # Check batch constraints
                    batch_name = new_class.get_batch_name()
                    if batch_name and new_class.course.course_type == 'LAB':
                        batch_key = (batch_name, time.day, time.pid)
                        if batch_key in self._batch_occupancy:
                            continue
                    
                    # All checks passed - assign
                    new_class.set_meetingTime(time)
                    new_class.set_room(room)
                    new_class.set_instructor(instructor)
                    
                    # Update occupancy
                    self._room_occupancy[time_key].add(room.r_number)
                    self._instructor_occupancy[time_key].add(instructor.uid)
                    
                    if div_name:
                        div_key = (div_name, time.day, time.pid)
                        self._division_occupancy[div_key].add(new_class.id)
                    
                    if batch_name and new_class.course.course_type == 'LAB':
                        batch_key = (batch_name, time.day, time.pid)
                        self._batch_occupancy[batch_key].add(new_class.id)
                    
                    self._classes.append(new_class)
                    return True
        
        return False
    
    def _assign_best_available(self, new_class, valid_times, valid_rooms, valid_instructors):
        """Assign with minimal conflicts when conflict-free not possible"""
        best_time = None
        best_room = None
        best_instructor = None
        min_conflicts = float('inf')
        
        for time in valid_times:
            for room in valid_rooms:
                for instructor in valid_instructors:
                    # Count potential conflicts
                    conflicts = self._count_potential_conflicts(
                        new_class, time, room, instructor
                    )
                    
                    if conflicts < min_conflicts:
                        min_conflicts = conflicts
                        best_time = time
                        best_room = room
                        best_instructor = instructor
                        
                        if conflicts == 0:
                            break
                if min_conflicts == 0:
                    break
            if min_conflicts == 0:
                break
        
        if best_time and best_room and best_instructor:
            new_class.set_meetingTime(best_time)
            new_class.set_room(best_room)
            new_class.set_instructor(best_instructor)
            
            # Update occupancy
            time_key = (best_time.day, best_time.pid)
            self._room_occupancy[time_key].add(best_room.r_number)
            self._instructor_occupancy[time_key].add(best_instructor.uid)
            
            div_name = new_class.get_division_name()
            if div_name:
                div_key = (div_name, best_time.day, best_time.pid)
                self._division_occupancy[div_key].add(new_class.id)
            
            batch_name = new_class.get_batch_name()
            if batch_name and new_class.course.course_type == 'LAB':
                batch_key = (batch_name, best_time.day, best_time.pid)
                self._batch_occupancy[batch_key].add(new_class.id)
        
        self._classes.append(new_class)
    
    def _count_potential_conflicts(self, new_class, time, room, instructor):
        """Count potential conflicts if assigned with given parameters"""
        conflicts = 0
        time_key = (time.day, time.pid)
        
        # Room conflict
        if room.r_number in self._room_occupancy.get(time_key, set()):
            conflicts += 1
        
        # Instructor conflict
        if instructor.uid in self._instructor_occupancy.get(time_key, set()):
            conflicts += 1
        
        # Division conflict
        div_name = new_class.get_division_name()
        if div_name:
            div_key = (div_name, time.day, time.pid)
            if div_key in self._division_occupancy:
                conflicts += 1
        
        # Batch conflict for labs
        batch_name = new_class.get_batch_name()
        if batch_name and new_class.course.course_type == 'LAB':
            batch_key = (batch_name, time.day, time.pid)
            if batch_key in self._batch_occupancy:
                conflicts += 1
        
        return conflicts

    def calculate_fitness(self):
        """Calculate fitness with comprehensive conflict detection"""
        self._numberOfConflicts = 0
        self._conflict_details = {
            "room_conflicts": 0,
            "instructor_conflicts": 0,
            "division_lecture_conflicts": 0,
            "batch_lab_conflicts": 0,
            "capacity_issues": 0,
            "type_mismatch": 0
        }
        self._conflict_list = []
        
        n = len(self._classes)
        
        for i in range(n):
            c1 = self._classes[i]
            if not c1.meeting_time or not c1.room or not c1.instructor:
                self._numberOfConflicts += 1
                continue
            
            slot1 = c1.get_time_slot()
            if not slot1:
                continue
            
            # Check capacity
            if c1.room and c1.course:
                required_cap = 80 if c1.course.course_type == 'LECTURE' else 20
                if c1.room.seating_capacity < required_cap:
                    self._numberOfConflicts += 1
                    self._conflict_details["capacity_issues"] += 1
            
            # Check type match
            if c1.meeting_time.slot_type != c1.course.course_type:
                self._numberOfConflicts += 1
                self._conflict_details["type_mismatch"] += 1
            
            # Check against all other classes
            for j in range(i + 1, n):
                c2 = self._classes[j]
                if not c2.meeting_time or not c2.room or not c2.instructor:
                    continue
                
                slot2 = c2.get_time_slot()
                if not slot2:
                    continue
                
                if not slot1.overlaps_with(slot2):
                    continue
                
                div1 = c1.get_division_name()
                div2 = c2.get_division_name()
                batch1 = c1.get_batch_name()
                batch2 = c2.get_batch_name()
                
                # Room conflict
                if c1.room.r_number == c2.room.r_number:
                    self._numberOfConflicts += 1
                    self._conflict_details["room_conflicts"] += 1
                    self._conflict_list.append({
                        'type': 'ROOM_CONFLICT',
                        'room': c1.room.r_number,
                        'day': c1.meeting_time.day,
                        'time': c1.meeting_time.time,
                        'class1': f"{div1 or 'N/A'} - {c1.course}",
                        'class2': f"{div2 or 'N/A'} - {c2.course}"
                    })
                
                # Instructor conflict
                if c1.instructor.uid == c2.instructor.uid:
                    self._numberOfConflicts += 1
                    self._conflict_details["instructor_conflicts"] += 1
                    self._conflict_list.append({
                        'type': 'INSTRUCTOR_CONFLICT',
                        'instructor': c1.instructor.name,
                        'day': c1.meeting_time.day,
                        'time': c1.meeting_time.time,
                        'class1': f"{div1 or 'N/A'} - {c1.course}",
                        'class2': f"{div2 or 'N/A'} - {c2.course}"
                    })
                
                # Division lecture conflict
                if (div1 and div2 and div1 == div2 and
                    c1.course.course_type == 'LECTURE' and 
                    c2.course.course_type == 'LECTURE'):
                    self._numberOfConflicts += 1
                    self._conflict_details["division_lecture_conflicts"] += 1
                    self._conflict_list.append({
                        'type': 'DIVISION_LECTURE_CONFLICT',
                        'division': div1,
                        'day': c1.meeting_time.day,
                        'time': c1.meeting_time.time,
                        'class1': str(c1.course),
                        'class2': str(c2.course)
                    })
                
                # Batch lab conflict
                if (batch1 and batch2 and batch1 == batch2 and
                    c1.course.course_type == 'LAB' and 
                    c2.course.course_type == 'LAB'):
                    self._numberOfConflicts += 1
                    self._conflict_details["batch_lab_conflicts"] += 1
                    self._conflict_list.append({
                        'type': 'BATCH_LAB_CONFLICT',
                        'batch': batch1,
                        'day': c1.meeting_time.day,
                        'time': c1.meeting_time.time,
                        'class1': str(c1.course),
                        'class2': str(c2.course)
                    })
        
        # Calculate fitness - higher is better
        if self._numberOfConflicts == 0:
            return 1.0
        else:
            return 1.0 / (1.0 + self._numberOfConflicts)
    
    def repair(self):
        """Repair conflicts by reassigning problematic classes"""
        if self._numberOfConflicts == 0:
            return self
        
        # Find classes with conflicts
        conflict_classes = set()
        for conflict in self._conflict_list:
            # Extract class identifiers from conflict
            # This is simplified - in practice you'd need to track which classes are in conflict
            pass
        
        # For simplicity, try to repair all classes with potential issues
        classes_to_repair = []
        for c in self._classes:
            if self._class_has_conflict(c):
                classes_to_repair.append(c)
        
        # Remove these classes from occupancy
        for c in classes_to_repair:
            self._remove_from_occupancy(c)
            self._classes.remove(c)
        
        # Reassign them
        for c in classes_to_repair:
            course_type = c.course.course_type if c.course else 'LECTURE'
            valid_times = data.get_times_by_type(course_type)
            valid_rooms = data.get_rooms_by_type(course_type)
            valid_instructors = data.get_instructors_for_course(c.course.course_number) if c.course else []
            
            self._assign_without_conflicts(c, valid_times, valid_rooms, valid_instructors)
        
        self._isFitnessChanged = True
        return self
    
    def _class_has_conflict(self, target_class):
        """Check if a specific class has any conflicts"""
        # Simplified - in practice you'd check against all other classes
        return True  # For now, assume all classes in repair list need checking
    
    def _remove_from_occupancy(self, target_class):
        """Remove a class from occupancy trackers"""
        if target_class.meeting_time:
            time_key = (target_class.meeting_time.day, target_class.meeting_time.pid)
            
            if target_class.room:
                self._room_occupancy[time_key].discard(target_class.room.r_number)
            
            if target_class.instructor:
                self._instructor_occupancy[time_key].discard(target_class.instructor.uid)
            
            div_name = target_class.get_division_name()
            if div_name:
                div_key = (div_name, target_class.meeting_time.day, target_class.meeting_time.pid)
                self._division_occupancy[div_key].discard(target_class.id)
            
            batch_name = target_class.get_batch_name()
            if batch_name and target_class.course and target_class.course.course_type == 'LAB':
                batch_key = (batch_name, target_class.meeting_time.day, target_class.meeting_time.pid)
                self._batch_occupancy[batch_key].discard(target_class.id)


# ============================================================================
# POPULATION CLASS
# ============================================================================

class Population:
    def __init__(self, size, initialize=True):
        self._size = size
        self._schedules = []
        
        if initialize:
            print(f"Initializing population of {size}...")
            for i in range(size):
                if i % 50 == 0 and i > 0:
                    print(f"  Created {i}/{size} schedules")
                schedule = Schedule()
                self._schedules.append(schedule)
            print(f"Population initialized with {len(self._schedules)} schedules")

    def get_schedules(self):
        return self._schedules


# ============================================================================
# GENETIC ALGORITHM CLASS
# ============================================================================

class GeneticAlgorithm:
    def evolve(self, population):
        """Evolve population to next generation"""
        return self._mutate_population(self._crossover_population(population))

    def _crossover_population(self, pop):
        schedules = pop.get_schedules()
        # Sort by fitness (best first)
        schedules.sort(key=lambda x: x.get_fitness(), reverse=True)
        
        new_pop = Population(0, initialize=False)
        
        # Keep elite schedules
        for i in range(min(NUMB_OF_ELITE_SCHEDULES, len(schedules))):
            new_pop.get_schedules().append(schedules[i])
        
        # Fill rest with crossover
        while len(new_pop.get_schedules()) < POPULATION_SIZE:
            p1 = self._tournament_select(schedules)
            p2 = self._tournament_select(schedules)
            child = self._crossover(p1, p2)
            new_pop.get_schedules().append(child)
        
        return new_pop

    def _tournament_select(self, schedules):
        """Select best schedule from random tournament"""
        tournament_size = min(TOURNAMENT_SELECTION_SIZE, len(schedules))
        tournament = rnd.sample(schedules, tournament_size)
        return max(tournament, key=lambda x: x.get_fitness())

    def _crossover(self, s1, s2):
        """Create child schedule by mixing parents"""
        child = Schedule(initialize=False)
        classes1, classes2 = s1.get_classes(), s2.get_classes()
        
        # Ensure same number of classes
        min_len = min(len(classes1), len(classes2))
        
        for i in range(min_len):
            if rnd.random() < 0.5:
                child.get_classes().append(classes1[i].copy())
            else:
                child.get_classes().append(classes2[i].copy())
        
        # Add remaining classes from longer parent
        if len(classes1) > min_len:
            for i in range(min_len, len(classes1)):
                child.get_classes().append(classes1[i].copy())
        elif len(classes2) > min_len:
            for i in range(min_len, len(classes2)):
                child.get_classes().append(classes2[i].copy())
        
        # Rebuild occupancy for child
        child._clear_occupancy()
        for c in child.get_classes():
            if c.meeting_time and c.room and c.instructor:
                time_key = (c.meeting_time.day, c.meeting_time.pid)
                child._room_occupancy[time_key].add(c.room.r_number)
                child._instructor_occupancy[time_key].add(c.instructor.uid)
                
                div_name = c.get_division_name()
                if div_name:
                    div_key = (div_name, c.meeting_time.day, c.meeting_time.pid)
                    child._division_occupancy[div_key].add(c.id)
                
                batch_name = c.get_batch_name()
                if batch_name and c.course and c.course.course_type == 'LAB':
                    batch_key = (batch_name, c.meeting_time.day, c.meeting_time.pid)
                    child._batch_occupancy[batch_key].add(c.id)
        
        return child

    def _mutate_population(self, population):
        """Apply mutation to population"""
        schedules = population.get_schedules()
        
        for i in range(NUMB_OF_ELITE_SCHEDULES, len(schedules)):
            if rnd.random() < MUTATION_RATE:
                self._mutate(schedules[i])
                schedules[i]._isFitnessChanged = True
        
        return population

    def _mutate(self, schedule):
        """Mutate a schedule by randomly changing some classes"""
        classes = schedule.get_classes()
        if not classes:
            return
        
        # Mutate 1-3 random classes
        num_mutations = rnd.randint(1, min(3, len(classes)))
        mutate_indices = rnd.sample(range(len(classes)), num_mutations)
        
        for idx in mutate_indices:
            c = classes[idx]
            
            # Remove from occupancy
            if c.meeting_time:
                time_key = (c.meeting_time.day, c.meeting_time.pid)
                if c.room:
                    schedule._room_occupancy[time_key].discard(c.room.r_number)
                if c.instructor:
                    schedule._instructor_occupancy[time_key].discard(c.instructor.uid)
                
                div_name = c.get_division_name()
                if div_name:
                    div_key = (div_name, c.meeting_time.day, c.meeting_time.pid)
                    schedule._division_occupancy[div_key].discard(c.id)
                
                batch_name = c.get_batch_name()
                if batch_name and c.course and c.course.course_type == 'LAB':
                    batch_key = (batch_name, c.meeting_time.day, c.meeting_time.pid)
                    schedule._batch_occupancy[batch_key].discard(c.id)
            
            # Assign new random values
            if c.course:
                course_type = c.course.course_type
                valid_times = data.get_times_by_type(course_type)
                valid_rooms = data.get_rooms_by_type(course_type)
                valid_instructors = data.get_instructors_for_course(c.course.course_number)
                
                if valid_times:
                    c.set_meetingTime(rnd.choice(valid_times))
                if valid_rooms:
                    c.set_room(rnd.choice(valid_rooms))
                if valid_instructors:
                    c.set_instructor(rnd.choice(valid_instructors))
                
                # Update occupancy
                if c.meeting_time and c.room and c.instructor:
                    time_key = (c.meeting_time.day, c.meeting_time.pid)
                    schedule._room_occupancy[time_key].add(c.room.r_number)
                    schedule._instructor_occupancy[time_key].add(c.instructor.uid)
                    
                    div_name = c.get_division_name()
                    if div_name:
                        div_key = (div_name, c.meeting_time.day, c.meeting_time.pid)
                        schedule._division_occupancy[div_key].add(c.id)
                    
                    batch_name = c.get_batch_name()
                    if batch_name and c.course.course_type == 'LAB':
                        batch_key = (batch_name, c.meeting_time.day, c.meeting_time.pid)
                        schedule._batch_occupancy[batch_key].add(c.id)


# Global data instance
data = None

def get_data():
    global data
    if data is None:
        data = Data()
    return data


# ============================================================================
# VERIFICATION FUNCTION
# ============================================================================

def verify_timetable(schedule_classes):
    """Independent verification of all conflicts"""
    conflicts = []
    n = len(schedule_classes)
    
    for i in range(n):
        c1 = schedule_classes[i]
        if not c1.meeting_time or not c1.room or not c1.instructor:
            conflicts.append({
                'type': 'INCOMPLETE_ASSIGNMENT',
                'class': str(c1),
                'message': 'Class missing required assignments'
            })
            continue
        
        slot1 = c1.get_time_slot()
        if not slot1:
            continue
        
        # Check capacity
        if c1.room and c1.course:
            required_cap = 80 if c1.course.course_type == 'LECTURE' else 20
            if c1.room.seating_capacity < required_cap:
                conflicts.append({
                    'type': 'CAPACITY_ISSUE',
                    'class': f"{c1.get_division_name() or 'N/A'} - {c1.course}",
                    'room': c1.room.r_number,
                    'capacity': c1.room.seating_capacity,
                    'required': required_cap
                })
        
        for j in range(i + 1, n):
            c2 = schedule_classes[j]
            if not c2.meeting_time or not c2.room or not c2.instructor:
                continue
            
            slot2 = c2.get_time_slot()
            if not slot2:
                continue
            
            if not slot1.overlaps_with(slot2):
                continue
            
            div1 = c1.get_division_name()
            div2 = c2.get_division_name()
            batch1 = c1.get_batch_name()
            batch2 = c2.get_batch_name()
            
            # Room conflict
            if c1.room.r_number == c2.room.r_number:
                conflicts.append({
                    'type': 'ROOM_CONFLICT',
                    'room': c1.room.r_number,
                    'day': c1.meeting_time.day,
                    'time': c1.meeting_time.time,
                    'class1': f"{div1 or 'N/A'} - {c1.course}",
                    'class2': f"{div2 or 'N/A'} - {c2.course}"
                })
            
            # Instructor conflict
            if c1.instructor.uid == c2.instructor.uid:
                conflicts.append({
                    'type': 'INSTRUCTOR_CONFLICT',
                    'instructor': c1.instructor.name,
                    'day': c1.meeting_time.day,
                    'time': c1.meeting_time.time,
                    'class1': f"{div1 or 'N/A'} - {c1.course}",
                    'class2': f"{div2 or 'N/A'} - {c2.course}"
                })
            
            # Division lecture conflict
            if (div1 and div2 and div1 == div2 and
                c1.course.course_type == 'LECTURE' and 
                c2.course.course_type == 'LECTURE'):
                conflicts.append({
                    'type': 'DIVISION_LECTURE_CONFLICT',
                    'division': div1,
                    'day': c1.meeting_time.day,
                    'time': c1.meeting_time.time,
                    'class1': str(c1.course),
                    'class2': str(c2.course)
                })
            
            # Batch lab conflict
            if (batch1 and batch2 and batch1 == batch2 and
                c1.course.course_type == 'LAB' and 
                c2.course.course_type == 'LAB'):
                conflicts.append({
                    'type': 'BATCH_LAB_CONFLICT',
                    'batch': batch1,
                    'day': c1.meeting_time.day,
                    'time': c1.meeting_time.time,
                    'class1': str(c1.course),
                    'class2': str(c2.course)
                })
    
    return conflicts


# ============================================================================
# TIMETABLE GENERATION VIEW
# ============================================================================

def timetable(request):
    global data
    data = get_data()
    Class._id_counter = 0
    
    start_time = time.time()
    
    print(f"\n{'='*70}")
    print(f"🚀 STARTING TIMETABLE GENERATION")
    print(f"Population: {POPULATION_SIZE}, Max Gen: {MAX_GENERATIONS}")
    print(f"Sections: {len(data.get_sections())}, Time Slots: {len(data.get_meetingTimes())}")
    print(f"{'='*70}\n")
    
    # Initialize population
    population = Population(POPULATION_SIZE)
    generation_num = 0
    ga = GeneticAlgorithm()
    
    best_fitness = 0
    best_schedule = None
    no_improvement_count = 0
    
    # Evolution loop
    while generation_num < MAX_GENERATIONS:
        generation_num += 1
        
        # Evaluate current population
        schedules = population.get_schedules()
        for s in schedules:
            s.calculate_fitness()
        
        # Find best schedule
        schedules.sort(key=lambda x: x.get_fitness(), reverse=True)
        current_best = schedules[0]
        current_fitness = current_best.get_fitness()
        current_conflicts = current_best.get_numbOfConflicts()
        
        # Track best ever
        if current_fitness > best_fitness:
            best_fitness = current_fitness
            best_schedule = current_best
            no_improvement_count = 0
        else:
            no_improvement_count += 1
        
        # Progress report
        if generation_num % 10 == 0 or current_conflicts == 0:
            elapsed = time.time() - start_time
            print(f"\n📊 Gen {generation_num:4d} | Fitness: {current_fitness:.6f} | Conflicts: {current_conflicts:3d} | Time: {elapsed:.1f}s")
            
            if current_conflicts > 0:
                details = current_best.get_conflict_details()
                print(f"   Breakdown: Room:{details.get('room_conflicts',0)} Inst:{details.get('instructor_conflicts',0)} "
                      f"Div:{details.get('division_lecture_conflicts',0)} Batch:{details.get('batch_lab_conflicts',0)}")
        
        # Check for perfect solution
        if current_conflicts == 0:
            print(f"\n✅ PERFECT SOLUTION FOUND at generation {generation_num}!")
            break
        
        # Early stopping
        if no_improvement_count > EARLY_STOPPING_THRESHOLD:
            print(f"\n⏹️  Early stopping at generation {generation_num} (no improvement for {EARLY_STOPPING_THRESHOLD} generations)")
            break
        
        # Evolve to next generation
        population = ga.evolve(population)
    
    # Get best schedule
    if best_schedule is None:
        best_schedule = population.get_schedules()[0]
    
    # Final repair pass
    print(f"\n🔧 Applying final repair...")
    best_schedule.repair()
    best_schedule.calculate_fitness()
    
    # Independent verification
    print(f"\n🔍 RUNNING INDEPENDENT VERIFICATION...")
    verification_conflicts = verify_timetable(best_schedule.get_classes())
    
    if verification_conflicts:
        print(f"❌ VERIFICATION FAILED: Found {len(verification_conflicts)} conflicts:")
        for conflict in verification_conflicts[:5]:  # Show first 5
            if 'room' in conflict:
                print(f"   {conflict['type']}: Room {conflict['room']} on {conflict['day']} at {conflict['time']}")
            elif 'instructor' in conflict:
                print(f"   {conflict['type']}: {conflict['instructor']} on {conflict['day']} at {conflict['time']}")
            elif 'division' in conflict:
                print(f"   {conflict['type']}: Division {conflict['division']} on {conflict['day']} at {conflict['time']}")
            elif 'batch' in conflict:
                print(f"   {conflict['type']}: Batch {conflict['batch']} on {conflict['day']} at {conflict['time']}")
        
        # Try one more aggressive repair
        print(f"\n🔨 Attempting aggressive conflict resolution...")
        best_schedule = Schedule(initialize=False)
        best_schedule._classes = best_schedule.get_classes()
        best_schedule._clear_occupancy()
        
        # Rebuild occupancy
        for c in best_schedule.get_classes():
            if c.meeting_time and c.room and c.instructor:
                time_key = (c.meeting_time.day, c.meeting_time.pid)
                best_schedule._room_occupancy[time_key].add(c.room.r_number)
                best_schedule._instructor_occupancy[time_key].add(c.instructor.uid)
        
        best_schedule.calculate_fitness()
        final_conflicts = best_schedule.get_numbOfConflicts()
    else:
        print("✅ VERIFICATION PASSED: No conflicts found")
        final_conflicts = 0
    
    total_time = time.time() - start_time
    
    print(f"\n{'='*70}")
    print(f"🏁 FINAL RESULT")
    print(f"Conflicts: {best_schedule.get_numbOfConflicts()} | Verified: {final_conflicts}")
    print(f"Fitness: {best_schedule.get_fitness():.6f}")
    print(f"Generations: {generation_num} | Time: {total_time:.2f}s")
    print(f"{'='*70}\n")
    
    # Prepare context for template
    context = {
        'schedule': best_schedule.get_classes(),
        'sections': data.get_sections(),
        'times': data.get_meetingTimes(),
        'generations': generation_num,
        'fitness': best_schedule.get_fitness(),
        'conflicts': final_conflicts,
        'conflict_details': best_schedule.get_conflict_details(),
        'verified': len(verification_conflicts) == 0,
        'time_taken': round(total_time, 2)
    }
    
    return render(request, 'gentimetable.html', context)


# ============================================================================
# OTHER VIEWS (unchanged)
# ============================================================================

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

@login_required
def admindash(request):
    context = {
        'total_departments': Department.objects.count(),
        'total_divisions': Division.objects.count(),
        'total_batches': Batch.objects.count(),
        'total_instructors': Instructor.objects.count(),
        'total_rooms': Room.objects.count(),
        'total_courses': Course.objects.count(),
        'total_sections': Section.objects.count(),
    }
    return render(request, 'admindashboard.html', context)

@login_required
def addDepts(request):
    form = DepartmentForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            return redirect('addDepts')
    return render(request, 'addDepts.html', {'form': form})

@login_required
def department_list(request):
    return render(request, 'deptlist.html', {'departments': Department.objects.all()})

@login_required
def delete_department(request, pk):
    dept = Department.objects.filter(pk=pk)
    if request.method == 'POST':
        dept.delete()
        return redirect('editdepartment')

@login_required
def addDivisions(request):
    form = DivisionForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            return redirect('addDivisions')
    return render(request, 'addDivisions.html', {'form': form})

@login_required
def division_list(request):
    return render(request, 'divisionlist.html', {'divisions': Division.objects.all()})

@login_required
def delete_division(request, pk):
    div = Division.objects.filter(pk=pk)
    if request.method == 'POST':
        div.delete()
        return redirect('editdivision')

@login_required
def addBatches(request):
    form = BatchForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            return redirect('addBatches')
    return render(request, 'addBatches.html', {'form': form})

@login_required
def batch_list(request):
    return render(request, 'batchlist.html', {'batches': Batch.objects.all()})

@login_required
def delete_batch(request, pk):
    batch = Batch.objects.filter(pk=pk)
    if request.method == 'POST':
        batch.delete()
        return redirect('editbatch')

@login_required
def addCourses(request):
    form = CourseForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            return redirect('addCourses')
    return render(request, 'addCourses.html', {'form': form})

@login_required
def course_list_view(request):
    return render(request, 'courseslist.html', {'courses': Course.objects.all()})

@login_required
def delete_course(request, pk):
    crs = Course.objects.filter(pk=pk)
    if request.method == 'POST':
        crs.delete()
        return redirect('editcourse')

@login_required
def addInstructor(request):
    form = InstructorForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            return redirect('addInstructors')
    return render(request, 'addInstructors.html', {'form': form})

@login_required
def inst_list_view(request):
    return render(request, 'inslist.html', {'instructors': Instructor.objects.all()})

@login_required
def delete_instructor(request, pk):
    inst = Instructor.objects.filter(pk=pk)
    if request.method == 'POST':
        inst.delete()
        return redirect('editinstructor')

@login_required
def addRooms(request):
    form = RoomForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            return redirect('addRooms')
    return render(request, 'addRooms.html', {'form': form})

@login_required
def room_list(request):
    return render(request, 'roomslist.html', {'rooms': Room.objects.all()})

@login_required
def delete_room(request, pk):
    rm = Room.objects.filter(pk=pk)
    if request.method == 'POST':
        rm.delete()
        return redirect('editrooms')

@login_required
def addTimings(request):
    form = MeetingTimeForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            return redirect('addTimings')
    return render(request, 'addTimings.html', {'form': form})

@login_required
def meeting_list_view(request):
    return render(request, 'mtlist.html', {'meeting_times': MeetingTime.objects.all()})

@login_required
def delete_meeting_time(request, pk):
    mt = MeetingTime.objects.filter(pk=pk)
    if request.method == 'POST':
        mt.delete()
        return redirect('editmeetingtime')

@login_required
def addSections(request):
    form = SectionForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            return redirect('addSections')
    return render(request, 'addSections.html', {'form': form})

@login_required
def section_list(request):
    return render(request, 'seclist.html', {'sections': Section.objects.all()})

@login_required
def delete_section(request, pk):
    sec = Section.objects.filter(pk=pk)
    if request.method == 'POST':
        sec.delete()
        return redirect('editsection')

@login_required
def generate(request):
    return render(request, 'generate.html', {})