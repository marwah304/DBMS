
from flask import Flask, render_template, request, session, url_for, redirect, jsonify, flash, send_from_directory, current_app
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import joinedload
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql import text
from werkzeug.utils import secure_filename
from flask_migrate import Migrate
from datetime import datetime
import os
app = Flask(__name__)
CORS(app)

app.config['SQLALCHEMY_DATABASE_URI'] ='postgresql://postgres:pgadmin4@localhost/studysync_db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'your_secret_key'


UPLOAD_FOLDER_ASSIGNMENTS = os.path.join(app.root_path, 'static', 'uploads')
UPLOAD_FOLDER_SUBMISSIONS = os.path.join(app.root_path, 'static', 'submissions')

os.makedirs(UPLOAD_FOLDER_ASSIGNMENTS, exist_ok=True)
os.makedirs(UPLOAD_FOLDER_SUBMISSIONS, exist_ok=True)

app.config['UPLOAD_FOLDER_ASSIGNMENTS'] = UPLOAD_FOLDER_ASSIGNMENTS
app.config['UPLOAD_FOLDER_SUBMISSIONS'] = UPLOAD_FOLDER_SUBMISSIONS

db = SQLAlchemy(app)
migrate = Migrate(app, db)

class User(db.Model):
    user_id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    courses = db.relationship('Course', backref='instructor', lazy=True)
    enrollments = db.relationship('Enrollment', backref='student', lazy=True, cascade="all, delete-orphan")


class Course(db.Model):
    course_id = db.Column(db.String(50), primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    duration = db.Column(db.String(50), nullable=True)
    instructor_id = db.Column(db.String(50), db.ForeignKey('user.user_id'), nullable=False)
    enrollments = db.relationship('Enrollment', backref='course', lazy=True)
    assignments = db.relationship('Assignment', backref='course', lazy=True)

class Enrollment(db.Model):
    enroll_id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), db.ForeignKey('user.user_id'), nullable=False)
    course_id = db.Column(db.String(50), db.ForeignKey('course.course_id'), nullable=False)
    status = db.Column(db.String(50), nullable=False)

class Assignment(db.Model):
    assignment_id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    file_path = db.Column(db.String(200), nullable=False)
    course_id = db.Column(db.String(50), db.ForeignKey('course.course_id'), nullable=False)

class Submission(db.Model):
    submission_id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String, db.ForeignKey('user.user_id'))
    assignment_id = db.Column(db.Integer, db.ForeignKey('assignment.assignment_id'))
    file_path = db.Column(db.String)
    grade = db.Column(db.String, nullable=True)  
    feedback = db.Column(db.Text, nullable=True)  

    #
    student = db.relationship('User', backref='submissions')
    assignment = db.relationship('Assignment', backref='submissions')

class Progress(db.Model):
    __tablename__ = 'progress'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), db.ForeignKey('user.user_id'), nullable=False)
    course_id = db.Column(db.String(50), db.ForeignKey('course.course_id'), nullable=False)
    completion_percentage = db.Column(db.Float, nullable=False, default=0) 
    status = db.Column(db.String(50), nullable=False, default="in-progress") 
    student = db.relationship('User', backref='progress')
    course = db.relationship('Course', backref='progress')


class DeletedEnrollment(db.Model):
    __tablename__ = 'deleted_enrollments'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.String(50), nullable=False)
    course_id = db.Column(db.String(50), nullable=False)
    deleted_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<DeletedEnrollment {self.student_id} removed from {self.course_id}>"

@app.route('/instructor/dashboard/<instructor_id>')
def instructor_dashboard(instructor_id):
    instructor = User.query.filter_by(user_id=instructor_id, role='instructor').first()
    if not instructor:
        return "Instructor not found", 404

    courses = Course.query.filter_by(instructor_id=instructor_id).all()
    course_items = []

    all_students_set = {}

    for course in courses:
        students = User.query.join(Enrollment).filter(
            Enrollment.course_id == course.course_id,
            User.user_id == Enrollment.student_id
        ).all()

        for student in students:
            all_students_set[student.user_id] = student

        assignments = Assignment.query.filter_by(course_id=course.course_id).all()
        course_items.append({
            'course': course,
            'students': students,
            'assignments': assignments
        })

    all_students = list(all_students_set.values())

    deleted_enrollments = DeletedEnrollment.query.order_by(DeletedEnrollment.deleted_at.desc()).limit(10).all()

    return render_template(
        'instructor_dashboard.html',
        instructor=instructor,
        course_items=course_items,
        all_students=all_students,
        deleted_enrollments=deleted_enrollments
    )

@app.route('/restore_student', methods=['POST'])
def restore_student():
    data = request.get_json()
    student_id = data.get('student_id')
    course_id = data.get('course_id')

    student = User.query.filter_by(user_id=student_id, role='student').first()
    if not student:
        return jsonify({"error": "Student not found"}), 404

    existing = Enrollment.query.filter_by(student_id=student_id, course_id=course_id).first()
    if existing:
        return jsonify({"error": "Already enrolled"}), 409

    new_enrollment = Enrollment(student_id=student_id, course_id=course_id, status='enrolled')
    db.session.add(new_enrollment)
    db.session.commit()

    # The trigger will handle the removal of the deleted record from the DeletedEnrollment table
    return jsonify({"message": "Student restored successfully"}), 200


@app.route('/add_student', methods=['POST'])
def add_student():
    data = request.get_json()
    user_id = data.get('user_id')
    course_id = data.get('course_id')

    student = User.query.filter_by(user_id=user_id, role='student').first()
    if not student:
        return jsonify({"error": "Student not found"}), 404

    existing_enrollment = Enrollment.query.filter_by(student_id=user_id, course_id=course_id).first()
    if existing_enrollment:
        return jsonify({"error": "Student is already enrolled in this course"}), 409

    enrollment = Enrollment(student_id=user_id, course_id=course_id, status='enrolled')
    db.session.add(enrollment)
    db.session.commit()

    return jsonify({"message": "Student enrolled successfully"}), 200

@app.route('/delete_student/<user_id>/<course_id>', methods=['DELETE'])
def delete_student_from_course(user_id, course_id):
    enrollment = Enrollment.query.filter_by(student_id=user_id, course_id=course_id).first()
    if not enrollment:
        return jsonify({"error": "Enrollment not found"}), 404

    # Deleting the enrollment record, which will trigger the backup via the trigger
    db.session.delete(enrollment)
    db.session.commit()

    return jsonify({"message": "Student unenrolled successfully (backup handled by trigger)"}), 200

@app.route('/grade_assignment_edited/<int:submission_id>', methods=['POST'])
def update_assignment_grade(submission_id):
    data = request.get_json()
    grade = data.get('grade')

    submission = Submission.query.get(submission_id)
    if submission:
        submission.grade = grade
        db.session.commit()
        return jsonify({'message': 'Grade updated'}), 200
    return jsonify({'error': 'Submission not found'}), 404



@app.route('/update_grade', methods=['POST'])
def update_grade():
    data = request.get_json()
    user_id = data.get('user_id')
    grade = data.get('grade')

    student = User.query.filter_by(user_id=user_id, role='student').first()
    if student:
        student.grade = grade
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Grade updated'})
    return jsonify({'status': 'error', 'message': 'Student not found'}), 404



@app.route('/upload_assignment/<course_id>', methods=['POST'])
def upload_assignment(course_id):
    course = Course.query.filter_by(course_id=course_id).first()
    if not course:
        return "Course not found", 404

    title = request.form['title']
    description = request.form['description']
    file = request.files['assignment_file']

    if file:
        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER_ASSIGNMENTS'], filename)
        file.save(save_path)

        assignment = Assignment(
            title=title,
            description=description,
            file_path=filename,  
            course_id=course_id
        )

        db.session.add(assignment)
        db.session.commit()

    return redirect(url_for('instructor_dashboard', instructor_id=course.instructor_id))

@app.route('/create_db')
def create_db():
    try:
        db.drop_all()
        db.create_all()

        instructors = [
            User(user_id='121000', name='Dr. Ayesha Khan', email='ayesha.khan@ocms.com', password=generate_password_hash('teach123'), role='instructor'),
            User(user_id='122000', name='Prof. Salman Ahmed', email='salman.ahmed@ocms.com', password=generate_password_hash('teach124'), role='instructor'),
            User(user_id='123000', name='Dr. Sana Raza', email='sana.raza@ocms.com', password=generate_password_hash('teach125'), role='instructor'),
            User(user_id='124000', name='Dr. Asim Shah', email='asim.shah@ocms.com', password=generate_password_hash('teach126'), role='instructor'),
            User(user_id='125000', name='Prof. Ali Farooq', email='ali.farooq@ocms.com', password=generate_password_hash('teach127'), role='instructor'),
            User(user_id='126000', name='Dr. Nida Tariq', email='nida.tariq@ocms.com', password=generate_password_hash('teach128'), role='instructor'),
            User(user_id='127000', name='Dr. Zain Abbas', email='zain.abbas@ocms.com', password=generate_password_hash('teach129'), role='instructor'),
            User(user_id='128000', name='Dr. Saima Sadiq', email='saima.sadiq@ocms.com', password=generate_password_hash('teach130'), role='instructor'),
            User(user_id='129000', name='Prof. Bilal Iqbal', email='bilal.iqbal@ocms.com', password=generate_password_hash('teach131'), role='instructor'),
            User(user_id='130000', name='Dr. Fariha Zahid', email='fariha.zahid@ocms.com', password=generate_password_hash('teach132'), role='instructor'),
        ]

        students = [
            User(user_id='202331', name='Ali Raza', email='ali.raza@student.ocms.com', password=generate_password_hash('study123'), role='student'),
            User(user_id='202332', name='Hira Malik', email='hira.malik@student.ocms.com', password=generate_password_hash('study124'), role='student'),
            User(user_id='202333', name='Ahmed Iqbal', email='ahmed.iqbal@student.ocms.com', password=generate_password_hash('study125'), role='student'),
            User(user_id='202334', name='Sara Khan', email='sara.khan@student.ocms.com', password=generate_password_hash('study126'), role='student'),
            User(user_id='202335', name='Usman Shah', email='usman.shah@student.ocms.com', password=generate_password_hash('study127'), role='student'),
            User(user_id='202336', name='Nida Tariq', email='nida.tariq@student.ocms.com', password=generate_password_hash('study128'), role='student'),
            User(user_id='202337', name='Muneeb Khan', email='muneeb.khan@student.ocms.com', password=generate_password_hash('study129'), role='student'),
            User(user_id='202338', name='Ayesha Fatima', email='ayesha.fatima@student.ocms.com', password=generate_password_hash('study130'), role='student'),
            User(user_id='202339', name='Zainab Ali', email='zainab.ali@student.ocms.com', password=generate_password_hash('study131'), role='student'),
            User(user_id='202340', name='Omer Farooq', email='omer.farooq@student.ocms.com', password=generate_password_hash('study132'), role='student'),
        ]

        db.session.add_all(instructors + students)
        db.session.commit()

        courses = [
            Course(course_id='CSE101', title='Introduction to Computer Science', description='Fundamentals of computer science', duration='4 months', instructor_id='121000'),
            Course(course_id='CS232', title='Data Structures', description='Advanced data structures and algorithms', duration='4 months', instructor_id='122000'),
            Course(course_id='CSE103', title='Operating Systems', description='Understanding of operating systems', duration='4 months', instructor_id='123000'),
            Course(course_id='AI201', title='Introduction to Python', description='Learn Python basics including syntax, loops, and functions.', duration='4 months', instructor_id='124000'),
            Course(course_id='CS231', title='Discrete Mathematics', description='Mathematical foundations for computer science', duration='4 months', instructor_id='125000'),
            Course(course_id='CS112', title='Object-Oriented Programming', description='Introduction to object-oriented programming concepts', duration='4 months', instructor_id='126000'),
            Course(course_id='MT101', title='Linear Algebra', description='Fundamentals of linear algebra', duration='4 months', instructor_id='127000'),
            Course(course_id='HM101', title='English Communication', description='English communication skills for students', duration='4 months', instructor_id='128000'),
            Course(course_id='ES205', title='Advanced Linear Algebra', description='Advanced topics in linear algebra', duration='4 months', instructor_id='129000'),
            Course(course_id='CS233', title='Database Management System', description='Introduction to databases and SQL', duration='4 months', instructor_id='130000'),
        ]

        db.session.add_all(courses)
        db.session.commit()
          student_courses = {
            '202331': ['CSE101', 'CS232'],
            '202332': ['CSE101'],
            '202333': ['CS231', 'CS112'],
            '202334': ['MT101', 'HM101'],
            '202335': ['ES205', 'CS232'],
            '202336': ['CSE101', 'CS231'],
            '202337': ['CSE103', 'AI201'],
            '202338': ['CS112', 'CS232'],
            '202339': ['MT101', 'CS112'],
            '202340': ['ES205', 'AI201'],
        }

        existing_students = {s.user_id for s in User.query.filter_by(role='student').all()}

        enrollments = []
        for student_id, course_ids in student_courses.items():
            if student_id not in existing_students:
                print(f"❌ Invalid student ID: {student_id}")
                continue
            for course_id in course_ids:
                if course_id is None:
                    print(f"⚠ Skipped None course_id for student {student_id}")
                    continue
                enrollments.append(Enrollment(student_id=student_id, course_id=course_id, status='enrolled'))


        db.session.add_all(enrollments)
        db.session.commit()

        assignments = [
            Assignment(title='Assignment 1', description='Basic concepts', file_path='uploads/a1.txt', course_id='CSE101'),
            Assignment(title='Assignment 2', description='Intro to data structures', file_path='uploads/a2.txt', course_id='CS232'),
            Assignment(title='Assignment 3', description='OS Processes', file_path='uploads/a3.txt', course_id='CSE103'),
            Assignment(title='Assignment 4', description='Python Loops', file_path='uploads/a4.txt', course_id='AI201'),
            Assignment(title='Assignment 5', description='Logic & Sets', file_path='uploads/a5.txt', course_id='CS231'),
            Assignment(title='Assignment 6', description='Classes and Objects', file_path='uploads/a6.txt', course_id='CS112'),
            Assignment(title='Assignment 7', description='Matrix operations', file_path='uploads/a7.txt', course_id='MT101'),
            Assignment(title='Assignment 8', description='Essay writing', file_path='uploads/a8.txt', course_id='HM101'),
            Assignment(title='Assignment 9', description='Vector spaces', file_path='uploads/a9.txt', course_id='ES205'),
            Assignment(title='Assignment 10', description='SQL Queries', file_path='uploads/a10.txt', course_id='CS233'),
        ]

        db.session.add_all(assignments)
        db.session.commit()

        return "Database and demo data created."
    except Exception as e:
        return f"Error: {e}"
    
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        user_id = request.form['user_id']
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        role = request.form['role']


        if User.query.filter_by(user_id=user_id).first():
            return "User ID already taken. Please try again."

        new_user = User(
            user_id=user_id.strip(),
            name=name.strip(),
            email=email.strip(),
            password=generate_password_hash(password.strip(), method='pbkdf2:sha256'),
            role=role.strip()
        )
        db.session.add(new_user)
        db.session.commit()

       
        session['user_id'] = new_user.user_id
        session['role'] = new_user.role

        if new_user.role == 'instructor':
            return redirect(url_for('instructor_dashboard', instructor_id=new_user.user_id))
        else:
            return redirect(url_for('student_dashboard'))

    return render_template('newregister.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))  


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_id = request.form['user_id']
        password = request.form['password']
        user = User.query.filter_by(user_id=user_id).first()

        if user and check_password_hash(user.password, password):
            session['user_id'] = user.user_id
            session['name'] = user.name
            session['role'] = user.role

            if user.role == 'instructor':
                return redirect(url_for('instructor_dashboard', instructor_id=user.user_id))
            else:
                return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid credentials. Please try again.', 'error')

    return render_template('newlogin.html')

@app.route('/instructor/<instructor_id>/add_course', methods=['GET', 'POST'])
def add_course(instructor_id):
    instructor = User.query.filter_by(user_id=instructor_id, role='instructor').first()
    if not instructor:
        return "Instructor not found", 404

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        duration = request.form['duration']

        new_course = Course(
            course_id=f"COURSE{Course.query.count() + 1}",
            title=title,
            description=description,
            duration=duration,
            instructor_id=instructor_id
        )
        db.session.add(new_course)
        db.session.commit()
        return redirect(url_for('instructor_dashboard', instructor_id=instructor_id))

    return render_template('add_course.html', instructor=instructor)

@app.route('/student_dashboard')
def student_dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    user = User.query.options(joinedload(User.enrollments).joinedload(Enrollment.course)).filter_by(user_id=user_id).first()
    if not user:
        return "User not found", 404

    enrolled_courses = [enrollment.course for enrollment in user.enrollments]
    all_courses = Course.query.all()

    return render_template('nstudentdashboard.html', user=user, enrolled_courses=enrolled_courses, all_courses=all_courses)

@app.route('/courses')
def browse_courses():
    courses = Course.query.all()
    if not courses:
        return "No courses available", 404
    return render_template('browsecourses.html', courses=courses)

@app.route('/student_profile')
def student_profile():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    user = User.query.filter_by(user_id=user_id).first()
    
    if not user:
        return "User not found", 404

    return render_template('student_dashboard.html', user=user)


@app.route('/test_db_connection')
def test_db_connection():
    try:
        db.session.execute(text('SELECT 1'))
        return 'Database connection successful.'
    except Exception as e:
        return f'Database connection failed: {e}'

@app.route('/')
def index():
    return render_template('home.html')

@app.route('/download_assignment/<filename>')
def download_assignment(filename):
    try:
        return send_from_directory(app.config['UPLOAD_FOLDER_ASSIGNMENTS'], filename, as_attachment=True)
    except FileNotFoundError:
        return "File not found", 404


@app.route('/download/<path:filename>')
def download_file(filename):
    directory = os.path.join(current_app.root_path, 'static', 'submissions')

    try:
        return send_from_directory(directory, filename, as_attachment=True)
    except FileNotFoundError:
        return "File not found", 404

@app.route('/my-courses', methods=['GET', 'POST'])
def my_courses():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']

    user = User.query.filter_by(user_id=user_id).first()
    if not user or user.role != 'student':
        return "Student not found", 404

    all_courses = Course.query.all()

    enrolled_course_ids = {e.course_id for e in Enrollment.query.filter_by(student_id=user_id).all()}
    enrolled_courses = [c for c in all_courses if c.course_id in enrolled_course_ids]
    available_courses = [c for c in all_courses if c.course_id not in enrolled_course_ids]

    if request.method == 'POST':
        course_id = request.form.get('course_id')
        if course_id and course_id not in enrolled_course_ids:
            enrollment = Enrollment(student_id=user_id, course_id=course_id, status='enrolled')
            db.session.add(enrollment)
            db.session.commit()
            return redirect(url_for('my_courses'))

    return render_template(
        'my_courses.html',
        enrolled_courses=enrolled_courses,
        available_courses=available_courses
    )

@app.route('/assignments')
def list_assignments():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    user = User.query.filter_by(user_id=user_id).first()
    
    if not user:
        return "User not found", 404

    enrolled_courses = [enrollment.course for enrollment in user.enrollments]
    
    if enrolled_courses:
        assignments = Assignment.query.filter(Assignment.course_id.in_([course.course_id for course in enrolled_courses])).all()
    else:
        assignments = []

    assignments_data = []
    for assignment in assignments:
        assignments_data.append({
            'assignment_id': assignment.assignment_id,
            'title': assignment.title,
            'description': assignment.description,
            'file_path': assignment.file_path
        })

    return render_template('student_assignments.html', assignments=assignments_data)

@app.route('/submit_assignment', methods=['POST'])
def submit_assignment():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if 'submission_file' not in request.files:
        flash('No file part', 'error')
        return redirect(request.url)

    file = request.files['submission_file']

    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(request.url)

    if file:
        filename = secure_filename(file.filename)
        save_path = os.path.join(app.config['UPLOAD_FOLDER_SUBMISSIONS'], filename) 
        file.save(save_path)

        db_file_path = os.path.join('submissions', filename).replace("\\", "/") 

        new_submission = Submission(
            student_id=session['user_id'],
            assignment_id=request.form['assignment_id'],
            file_path=db_file_path
        )
        db.session.add(new_submission)
        db.session.commit()

        flash('Assignment submitted successfully', 'success')
        return redirect(url_for('student_dashboard'))

@app.route('/view_submissions/<int:assignment_id>')
def view_submissions(assignment_id):
    if 'user_id' not in session or session.get('role') != 'instructor':
        return redirect(url_for('login'))
    
    assignment = Assignment.query.get_or_404(assignment_id)
    
    submissions = Submission.query.options(joinedload(Submission.student)).filter_by(assignment_id=assignment_id).all()
    
    return render_template('view_assignments.html', assignment=assignment, submissions=submissions)

@app.route('/grade_assignment/<int:submission_id>', methods=['GET', 'POST'])
def grade_assignment(submission_id):
    if 'user_id' not in session or session.get('role') != 'instructor':
        return redirect(url_for('login'))
    submission = Submission.query.get_or_404(submission_id)
    
    if request.method == 'POST':
        grade = request.form['grade']
        feedback = request.form['feedback']
        

        submission.grade = grade
        submission.feedback = feedback
        db.session.commit()

        print(f"Updated Submission ID {submission.submission_id} with grade {submission.grade}")
        
        update_course_progress(submission.student_id, submission.assignment.course_id)
        
        flash('Grade and feedback have been saved successfully!', 'success')
        return redirect(url_for('view_submissions', assignment_id=submission.assignment_id))
    
    return render_template('grade_assignments.html', submission=submission)


@app.route('/download_submission/<path:filename>')
def download_submission(filename):
    try:
        return send_from_directory(os.path.join(app.root_path, 'static'), filename, as_attachment=True)
    except FileNotFoundError:
        return "File not found", 404


@app.route('/student/grades')
def student_grades():
    if 'user_id' not in session or session.get('role') != 'student':
        return redirect(url_for('login'))
    
    student_id = session['user_id']
    
    graded_submissions = Submission.query.filter_by(student_id=student_id).filter(Submission.grade != None).all()
    
    return render_template('student_grades.html', submissions=graded_submissions)

def calculate_course_progress(student_id, course_id):
    total_assignments = Assignment.query.filter_by(course_id=course_id).count()
    print(f"Total assignments in course {course_id}: {total_assignments}") 
    
  
    completed_assignments = db.session.query(Submission).join(Assignment).filter(
        Submission.student_id == student_id,
        Assignment.course_id == course_id,
        Submission.grade != None
    ).count()
    print(f"Completed assignments for student {student_id} in course {course_id}: {completed_assignments}") 
   
    if total_assignments == 0:
        return 0
    completion_percentage = (completed_assignments / total_assignments) * 100
    print(f"Calculated completion percentage: {completion_percentage}%")  
    return completion_percentage


def update_course_progress(student_id, course_id):
    completion_percentage = calculate_course_progress(student_id, course_id)
    print(f"Calculated completion: {completion_percentage}%")  
    
    progress = Progress.query.filter_by(student_id=student_id, course_id=course_id).first()
    if progress:
        progress.completion_percentage = completion_percentage
        if completion_percentage == 100:
            progress.status = "completed"
        else:
            progress.status = "in-progress"
        print(f"Updated progress: {progress.completion_percentage}% - {progress.status}")  
    else:
        new_progress = Progress(student_id=student_id, course_id=course_id, completion_percentage=completion_percentage)
        if completion_percentage == 100:
            new_progress.status = "completed"
        print(f"New progress created: {new_progress.completion_percentage}% - {new_progress.status}")  
        db.session.add(new_progress)

    db.session.commit()


   
@app.route('/progress_tracking')
def progress_tracking():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    user = User.query.options(joinedload(User.enrollments).joinedload(Enrollment.course)).filter_by(user_id=user_id).first()

    if not user:
        return "User not found", 404

    enrolled_courses = [enrollment.course for enrollment in user.enrollments]
    progress_data = []  

    for course in enrolled_courses:
          progress = Progress.query.filter_by(student_id=user_id, course_id=course.course_id).first()

          if not progress:
             progress_percentage = 0
             status = 'in-progress'
          else:
             progress_percentage = progress.completion_percentage
             status = progress.status

          progress_data.append({
            'course': course,
            'course_id': course.course_id,  
            'progress_percentage': progress_percentage,
            'status': status
    })

    return render_template('progress_tracking.html', user=user, enrolled_courses=enrolled_courses, progress_data=progress_data)


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, use_reloader=True)
