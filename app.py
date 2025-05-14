
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
