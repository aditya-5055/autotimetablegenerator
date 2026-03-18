

"""
load_timetable_data.py — Management command
============================================
This loads ONLY the input data that a user would enter via the Django forms:

  1. Department
  2. Divisions
  3. Batches
  4. Instructors  +  which SUBJECTS they can teach (that's all)
  5. Rooms        +  room type (LECTURE or LAB)
  6. Courses      +  course type + eligible teachers list
  7. Sections     +  which division/batch + which course + sessions/week

The algorithm in views.py figures out:
  - WHICH teacher is assigned to which division/batch (auto, locked per C4/C5)
  - WHICH room is used (auto, picked from free rooms of correct type)
  - WHAT time slot each class gets (auto, respecting all constraints)

Sections store NO instructor and NO room — the algorithm assigns those.
"""

from django.core.management.base import BaseCommand
from ttgen.models import (Department, Division, Batch, Instructor,
                           Room, Course, MeetingTime, Section)


class Command(BaseCommand):
    help = 'Load input data only — algorithm assigns teachers/rooms/times'

    def handle(self, *args, **kwargs):
        self.stdout.write('🚀 Starting data load...')

        # ── Clear all old data ─────────────────────────────────────────────
        for m in [Section, MeetingTime, Course, Batch,
                  Division, Room, Instructor, Department]:
            m.objects.all().delete()
        self.stdout.write('🗑️  Old data cleared')

        # ── 1. Department ──────────────────────────────────────────────────
        dept = Department.objects.create(dept_name='Computer Engineering')

        # ── 2. Divisions ───────────────────────────────────────────────────
        divisions = [
            Division.objects.create(division_name=n,
                                     department=dept,
                                     total_students=88)
            for n in ['TE-I', 'TE-II', 'TE-III', 'TE-IV']
        ]
        self.stdout.write(f'✅ {len(divisions)} divisions')

        # ── 3. Batches ─────────────────────────────────────────────────────
        # 4 batches per division: K,L,M,N + division index
        batches = {}
        for i, div in enumerate(divisions, 1):
            for letter in ['K', 'L', 'M', 'N']:
                name = f'{letter}{i}'
                batches[name] = Batch.objects.create(
                    batch_name=name, division=div, student_count=22)
        self.stdout.write(f'✅ {len(batches)} batches')

        # ── 4. Instructors ─────────────────────────────────────────────────
        # User enters: teacher name + which subjects they can teach
        inst_data = [
            ('T001', 'Dr. S.N. Girme'),
            ('T002', 'Prof. Rutuja Kulkarni'),
            ('T003', 'Prof. A.D. Bundele'),
            ('T004', 'Prof. M.V. Mane'),
            ('T005', 'Prof. P.P. Joshi'),
            ('T006', 'Prof. P.A. Jain'),
            ('T007', 'Prof. P.J. Jambhulkar'),
            ('T008', 'Prof. S.W. Jadhav'),
            ('T009', 'Prof. B.P. Masram'),
            ('T010', 'Prof. A.A. Chandorkar'),
            ('T011', 'Prof. D.D. Raigar'),
            ('T012', 'Prof. M.S. Wakode'),
            ('T013', 'Prof. K.R. Urane'),
            ('T014', 'Prof. N.Y. Kapadnis'),
            ('T015', 'Prof. Kopal Gangrade'),
            ('T016', 'Prof. P.R. Navghare'),
            ('T017', 'Dr. P.R. Patil'),
            ('T018', 'Prof. Deepika Kumari'),
            ('T019', 'Prof. Madhuri Patil'),
            ('T020', 'Prof. R.R. Jadhav'),
        ]
        
        T = {}
        for uid, name in inst_data:
            T[uid] = Instructor.objects.create(
                uid=uid, 
                name=name,
                max_batches_per_week=4,  # Default: can handle 4 lab batches
                max_lecture_divisions=2    # Default: can handle 2 divisions for lectures
            )
        self.stdout.write(f'✅ {len(T)} instructors')

        # ── 5. Rooms ───────────────────────────────────────────────────────
        # User enters: room number + capacity + type (LECTURE or LAB)
        R = {}
        
        # Lecture rooms (capacity 100)
        lecture_rooms = ['A1-309', 'A1-310', 'A1-311', 'A1-111', 'A1-213']
        for r in lecture_rooms:
            R[r] = Room.objects.create(
                r_number=r, 
                seating_capacity=100,
                room_type='LECTURE'
            )
        
        # Lab rooms (capacity 25)
        lab_rooms = ['A1-204', 'A1-102', 'A1-306', 'A1-307', 'A1-314',
                     'A1-303', 'A1-216', 'A2-302', 'A2-303', 'A1-105']
        for r in lab_rooms:
            R[r] = Room.objects.create(
                r_number=r, 
                seating_capacity=25,
                room_type='LAB'
            )
        
        self.stdout.write(f'✅ {len(R)} rooms (5 lecture + 10 lab)')

        # ── 6. Courses ─────────────────────────────────────────────────────
        # User enters: course name + type + list of eligible teachers
        # Algorithm picks ONE teacher per division/batch from this pool

        # Lecture courses — eligible teachers listed
        ai = Course.objects.create(
            course_number='AI',
            course_name='Artificial Intelligence',
            max_numb_students=88,
            course_type='LECTURE')
        ai.instructors.set([T['T001'], T['T004']])  # Girme, Mane

        dsbda = Course.objects.create(
            course_number='DSBDA',
            course_name='Data Science & Big Data Analytics',
            max_numb_students=88,
            course_type='LECTURE')
        dsbda.instructors.set([T['T002'], T['T005']])  # Kulkarni, Joshi

        wt = Course.objects.create(
            course_number='WT',
            course_name='Web Technology',
            max_numb_students=88,
            course_type='LECTURE')
        wt.instructors.set([T['T003'], T['T006']])  # Bundele, Jain

        # Lab courses — eligible teachers listed
        dsbdal = Course.objects.create(
            course_number='DSBDAL',
            course_name='DSBDA Lab',
            max_numb_students=22,
            course_type='LAB')
        dsbdal.instructors.set([
            T['T002'], T['T005'], T['T008'],
            T['T011'], T['T012'], T['T016'], T['T020']
        ])

        lpii = Course.objects.create(
            course_number='LPII',
            course_name='LP-II',
            max_numb_students=22,
            course_type='LAB')
        lpii.instructors.set([
            T['T001'], T['T004'], T['T009'], T['T010'],
            T['T013'], T['T014'], T['T017'], T['T018'], T['T019']
        ])

        wtl = Course.objects.create(
            course_number='WTL',
            course_name='WT Lab',
            max_numb_students=22,
            course_type='LAB')
        wtl.instructors.set([
            T['T003'], T['T006'], T['T007'], T['T015']
        ])

        self.stdout.write('✅ 6 courses created (3 lecture + 3 lab)')

        # ── 7. Meeting Times ───────────────────────────────────────────────
        # Zero-padded hours — MUST be '08:45' not '8:45'
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']

        lec_slots = [
            ('08:45','09:45'), ('09:45','10:45'),
            ('11:00','12:00'), ('12:00','13:00'),
            ('13:45','14:45'), ('14:45','15:45'),
        ]
        lab_slots = [
            ('08:45','10:45'),   # priority 1 — morning
            ('11:00','13:00'),   # priority 2
            ('13:45','15:45'),   # priority 3
        ]

        lc = 1
        for day in days:
            for s, e in lec_slots:
                MeetingTime.objects.create(
                    pid=f'L{lc:03d}', 
                    time=f'{s} - {e}',
                    day=day, 
                    slot_type='LECTURE')
                lc += 1

        bc = 1
        for day in days:
            for s, e in lab_slots:
                MeetingTime.objects.create(
                    pid=f'B{bc:03d}', 
                    time=f'{s} - {e}',
                    day=day, 
                    slot_type='LAB')
                bc += 1

        self.stdout.write(f'✅ {MeetingTime.objects.count()} meeting times '
                          f'(30 lecture + 15 lab)')

        # ── 8. Sections ────────────────────────────────────────────────────
        # User enters: section_id + division/batch + course + sessions/week
        # NO instructor, NO room — algorithm assigns those automatically

        # Lecture sections (one per division per subject)
        for i, div in enumerate(divisions, 1):
            for course, cnum in [(ai, 'AI'), (dsbda, 'DSBDA'), (wt, 'WT')]:
                Section.objects.create(
                    section_id=f'{cnum}-TE{i}',
                    department=dept,
                    num_class_in_week=3,    # 3 lectures per week
                    division=div,
                    course=course,
                )

        # Lab sections (one per batch per lab subject)
        for course, cnum, sessions in [
            (dsbdal, 'DSBDAL', 2),   # 2 lab sessions per week per batch
            (lpii,   'LPII',   2),   # 2 lab sessions per week per batch
            (wtl,    'WTL',    1),   # 1 lab session  per week per batch
        ]:
            for bname, batch in batches.items():
                Section.objects.create(
                    section_id=f'{cnum}-{bname}',
                    department=dept,
                    num_class_in_week=sessions,
                    batch=batch,
                    course=course,
                )

        # ── Summary ────────────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS('\n✅ DATA LOADED SUCCESSFULLY\n'))
        self.stdout.write('📊 Summary:')
        self.stdout.write(f'   Departments  : {Department.objects.count()}')
        self.stdout.write(f'   Divisions    : {Division.objects.count()}')
        self.stdout.write(f'   Batches      : {Batch.objects.count()}')
        self.stdout.write(f'   Instructors  : {Instructor.objects.count()}')
        self.stdout.write(f'   Rooms        : {Room.objects.count()}')
        self.stdout.write(f'   Courses      : {Course.objects.count()}')
        self.stdout.write(f'   Meeting Times: {MeetingTime.objects.count()}')
        self.stdout.write(f'   Sections     : {Section.objects.count()}')

        self.stdout.write('\n📋 What algorithm will auto-assign:')
        self.stdout.write('   → Teacher per division per lecture subject (C4)')
        self.stdout.write('   → Teacher per batch per lab subject (C5)')
        self.stdout.write('   → Lab room per batch (from free lab rooms)')
        self.stdout.write('   → Lecture room per slot (from free lecture rooms)')
        self.stdout.write('   → Time slot for every class (all constraints)')
        self.stdout.write('\n🚀 Ready! Run the server and visit /timetable_generation/')