from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .forms import *
from .models import *
import time
from ortools.sat.python import cp_model


# ============================================================================
# DATA LOADER
# ============================================================================

class TimetableData:
    """Load and organize all timetable data"""
    
    def __init__(self):
        print("Loading timetable data from database...")
        
        self.departments = list(Department.objects.all())
        self.divisions = list(Division.objects.all())
        self.batches = list(Batch.objects.all())
        self.instructors = list(Instructor.objects.all())
        self.rooms = list(Room.objects.all())
        self.courses = list(Course.objects.all())
        self.meeting_times = list(MeetingTime.objects.all())
        self.sections = list(Section.objects.all())
        
        # Create indexes for fast lookup
        self.rooms_by_type = {'LECTURE': [], 'LAB': []}
        self.times_by_type = {'LECTURE': [], 'LAB': []}
        self.instructors_by_course = {}
        
        for section in self.sections:
            if section.course:
                course_type = section.course.course_type
        
        for room in self.rooms:
            self.rooms_by_type[room.room_type].append(room)
        
        for mt in self.meeting_times:
            self.times_by_type[mt.slot_type].append(mt)
        
        for course in self.courses:
            self.instructors_by_course[course.course_number] = list(course.instructors.all())
        
        print(f"✅ Loaded: {len(self.sections)} sections, {len(self.rooms)} rooms, "
              f"{len(self.meeting_times)} time slots, {len(self.instructors)} instructors")


# ============================================================================
# OR-TOOLS CONSTRAINT PROGRAMMING SOLVER
# ============================================================================

class TimetableSolver:
    """OR-Tools CP-SAT solver for timetable generation"""
    
    def __init__(self, data):
        self.data = data
        self.model = cp_model.CpModel()
        self.variables = {}
        self.class_assignments = []
        
    def build_model(self):
        """Build the constraint programming model"""
        print("\n🔧 Building constraint model...")
        
        # For each section, create variables for each class instance
        for section in self.data.sections:
            if not section.course:
                continue
            
            course_type = section.course.course_type
            valid_times = self.data.times_by_type[course_type]
            valid_rooms = self.data.rooms_by_type[course_type]
            valid_instructors = self.data.instructors_by_course.get(section.course.course_number, [])
            
            if not valid_times or not valid_rooms or not valid_instructors:
                continue
            
            # Create multiple class instances per week
            for class_num in range(section.num_class_in_week):
                class_id = f"{section.section_id}_c{class_num}"
                
                # Create decision variables for time, room, instructor
                for time in valid_times:
                    for room in valid_rooms:
                        for instructor in valid_instructors:
                            var_name = f"{class_id}|{time.pid}|{room.r_number}|{instructor.uid}"
                            self.variables[var_name] = self.model.NewBoolVar(var_name)
                            
                            # Store metadata
                            self.class_assignments.append({
                                'var': var_name,
                                'section': section,
                                'class_num': class_num,
                                'time': time,
                                'room': room,
                                'instructor': instructor
                            })
        
        print(f"   Created {len(self.variables)} decision variables")
        
    def add_constraints(self):
        """Add all scheduling constraints"""
        print("🔒 Adding constraints...")
        
        # Group variables by class
        class_vars = {}
        for assignment in self.class_assignments:
            class_id = assignment['var'].split('|')[0]
            if class_id not in class_vars:
                class_vars[class_id] = []
            class_vars[class_id].append(self.variables[assignment['var']])
        
        # CONSTRAINT 1: Each class assigned exactly once
        for class_id, vars_list in class_vars.items():
            self.model.Add(sum(vars_list) == 1)
        
        # CONSTRAINT 2: Room conflicts
        room_time_vars = {}
        for assignment in self.class_assignments:
            time_room_key = f"{assignment['time'].pid}_{assignment['room'].r_number}"
            if time_room_key not in room_time_vars:
                room_time_vars[time_room_key] = []
            room_time_vars[time_room_key].append(self.variables[assignment['var']])
        
        for key, vars_list in room_time_vars.items():
            self.model.Add(sum(vars_list) <= 1)
        
        # CONSTRAINT 3: Instructor conflicts
        inst_time_vars = {}
        for assignment in self.class_assignments:
            time_inst_key = f"{assignment['time'].pid}_{assignment['instructor'].uid}"
            if time_inst_key not in inst_time_vars:
                inst_time_vars[time_inst_key] = []
            inst_time_vars[time_inst_key].append(self.variables[assignment['var']])
        
        for key, vars_list in inst_time_vars.items():
            self.model.Add(sum(vars_list) <= 1)
        
        # CONSTRAINT 4: Division lecture conflicts
        div_time_lecture_vars = {}
        for assignment in self.class_assignments:
            section = assignment['section']
            if section.division and section.course.course_type == 'LECTURE':
                div_time_key = f"{section.division.division_name}_{assignment['time'].pid}_LECTURE"
                if div_time_key not in div_time_lecture_vars:
                    div_time_lecture_vars[div_time_key] = []
                div_time_lecture_vars[div_time_key].append(self.variables[assignment['var']])
        
        for key, vars_list in div_time_lecture_vars.items():
            self.model.Add(sum(vars_list) <= 1)
        
        # CONSTRAINT 5: Batch lab conflicts
        batch_time_lab_vars = {}
        for assignment in self.class_assignments:
            section = assignment['section']
            if section.batch and section.course.course_type == 'LAB':
                batch_time_key = f"{section.batch.batch_name}_{assignment['time'].pid}_LAB"
                if batch_time_key not in batch_time_lab_vars:
                    batch_time_lab_vars[batch_time_key] = []
                batch_time_lab_vars[batch_time_key].append(self.variables[assignment['var']])
        
        for key, vars_list in batch_time_lab_vars.items():
            self.model.Add(sum(vars_list) <= 1)
        
        # CONSTRAINT 6: No batch lab during division lecture
        for time in self.data.meeting_times:
            # Find all division lectures at this time
            div_lectures = {}
            for assignment in self.class_assignments:
                if assignment['time'].pid == time.pid:
                    section = assignment['section']
                    if section.division and section.course.course_type == 'LECTURE':
                        div_name = section.division.division_name
                        if div_name not in div_lectures:
                            div_lectures[div_name] = []
                        div_lectures[div_name].append(self.variables[assignment['var']])
            
            # Find all batch labs at this time
            batch_labs = {}
            for assignment in self.class_assignments:
                if assignment['time'].pid == time.pid:
                    section = assignment['section']
                    if section.batch and section.course.course_type == 'LAB':
                        # Get division from batch
                        if section.batch.division:
                            div_name = section.batch.division.division_name
                            if div_name not in batch_labs:
                                batch_labs[div_name] = []
                            batch_labs[div_name].append(self.variables[assignment['var']])
            
            # Add constraints: if division has lecture, batches can't have labs
            for div_name in div_lectures:
                if div_name in batch_labs:
                    for lecture_var in div_lectures[div_name]:
                        for lab_var in batch_labs[div_name]:
                            self.model.Add(lecture_var + lab_var <= 1)
        
        print("   ✅ All constraints added")
    
    def solve(self, time_limit_seconds=120):
        """Solve the constraint model"""
        print(f"\n🚀 Solving (time limit: {time_limit_seconds}s)...")
        
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_seconds
        solver.parameters.num_search_workers = 8  # Use multiple cores
        
        start_time = time.time()
        status = solver.Solve(self.model)
        solve_time = time.time() - start_time
        
        print(f"⏱️  Solve time: {solve_time:.2f}s")
        
        if status == cp_model.OPTIMAL:
            print("✅ OPTIMAL solution found!")
            return self._extract_solution(solver)
        elif status == cp_model.FEASIBLE:
            print("✅ FEASIBLE solution found!")
            return self._extract_solution(solver)
        elif status == cp_model.INFEASIBLE:
            print("❌ INFEASIBLE - No solution exists with current constraints!")
            print("   Try: Add more rooms, instructors, or time slots")
            return None
        else:
            print(f"❌ Solver status: {solver.StatusName(status)}")
            return None
    
    def _extract_solution(self, solver):
        """Extract solution from solver"""
        solution_classes = []
        
        for assignment in self.class_assignments:
            var = self.variables[assignment['var']]
            if solver.Value(var) == 1:
                # Create a Class-like object
                class_obj = type('ScheduledClass', (), {})()
                class_obj.section = assignment['section']
                class_obj.course = assignment['section'].course
                class_obj.meeting_time = assignment['time']
                class_obj.room = assignment['room']
                class_obj.instructor = assignment['instructor']
                class_obj.division = assignment['section'].division
                class_obj.batch = assignment['section'].batch
                
                solution_classes.append(class_obj)
        
        return solution_classes


# ============================================================================
# VERIFICATION
# ============================================================================

def verify_solution(solution):
    """Verify the solution has no conflicts"""
    conflicts = []
    
    for i, c1 in enumerate(solution):
        for c2 in solution[i+1:]:
            # Same time slot?
            if c1.meeting_time.pid != c2.meeting_time.pid:
                continue
            
            # Room conflict
            if c1.room.r_number == c2.room.r_number:
                conflicts.append(f"ROOM: {c1.room.r_number} at {c1.meeting_time.time}")
            
            # Instructor conflict
            if c1.instructor.uid == c2.instructor.uid:
                conflicts.append(f"INSTRUCTOR: {c1.instructor.name} at {c1.meeting_time.time}")
            
            # Division conflict
            if (c1.division and c2.division and 
                c1.division.id == c2.division.id and
                c1.course.course_type == 'LECTURE' and c2.course.course_type == 'LECTURE'):
                conflicts.append(f"DIVISION: {c1.division.division_name} at {c1.meeting_time.time}")
            
            # Batch conflict
            if (c1.batch and c2.batch and 
                c1.batch.id == c2.batch.id and
                c1.course.course_type == 'LAB' and c2.course.course_type == 'LAB'):
                conflicts.append(f"BATCH: {c1.batch.batch_name} at {c1.meeting_time.time}")
            
            # Division-batch mix
            if c1.division and c2.batch:
                if c2.batch.division and c1.division.id == c2.batch.division.id:
                    conflicts.append(f"DIV-BATCH MIX: {c1.division.division_name} at {c1.meeting_time.time}")
            if c2.division and c1.batch:
                if c1.batch.division and c2.division.id == c1.batch.division.id:
                    conflicts.append(f"DIV-BATCH MIX: {c2.division.division_name} at {c2.meeting_time.time}")
    
    return conflicts


# ============================================================================
# DJANGO VIEW
# ============================================================================

def timetable(request):
    """Generate timetable using OR-Tools CP-SAT"""
    
    print("\n" + "="*70)
    print("🔬 OR-TOOLS TIMETABLE GENERATOR")
    print("="*70 + "\n")
    
    start_time = time.time()
    
    # Load data
    data = TimetableData()
    
    # Build and solve model
    solver = TimetableSolver(data)
    solver.build_model()
    solver.add_constraints()
    
    solution = solver.solve(time_limit_seconds=180)
    
    if not solution:
        context = {
            'schedule': [],
            'sections': data.sections,
            'times': data.meeting_times,
            'generations': 0,
            'fitness': 0,
            'conflicts': 999,
            'time_taken': 0,
            'error_message': 'No valid timetable could be generated. Please check your data constraints.'
        }
        return render(request, 'gentimetable.html', context)
    
    # Verify solution
    print("\n🔍 Verifying solution...")
    conflicts = verify_solution(solution)
    
    if conflicts:
        print(f"❌ Found {len(conflicts)} conflicts:")
        for c in conflicts[:10]:
            print(f"   {c}")
    else:
        print("✅ ZERO conflicts - perfect timetable!")
    
    total_time = time.time() - start_time
    
    print(f"\n" + "="*70)
    print(f"🏁 COMPLETE")
    print(f"Classes scheduled: {len(solution)}")
    print(f"Conflicts: {len(conflicts)}")
    print(f"Total time: {total_time:.2f}s")
    print("="*70 + "\n")
    
    context = {
        'schedule': solution,
        'sections': data.sections,
        'times': data.meeting_times,
        'generations': 1,
        'fitness': 1.0 if not conflicts else 1.0 / (1 + len(conflicts)),
        'conflicts': len(conflicts),
        'time_taken': round(total_time, 2)
    }
    
    return render(request, 'gentimetable.html', context)


# ============================================================================
# OTHER VIEWS (keep all existing views)
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
