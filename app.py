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
