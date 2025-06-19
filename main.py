# app.py using mysql.connector
from flask import Flask, render_template, request, redirect, url_for, session, flash
import mysql.connector
import csv
from db import get_connection
from datetime import timedelta
from io import StringIO

app = Flask(__name__)
app.secret_key = 'supersecretkey'
app.permanent_session_lifetime = timedelta(minutes=5)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login/<role>", methods=["GET", "POST"])
def login(role):
    if request.method == "POST":
        username = request.form['username']
        password = request.form['password']

        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username=%s AND password=%s AND role=%s", (username, password, role))
        user = cursor.fetchone()
        conn.close()

        if user:
            session.permanent = True
            session['user'] = user['username']
            session['role'] = user['role']
            return redirect(url_for(f"{role}_dashboard"))
        else:
            flash("Invalid credentials. Try again.")
            return redirect(request.url)

    return render_template("login.html", role=role)

@app.route("/admin/dashboard")
def admin_dashboard():
    if session.get("role") != "admin": return redirect("/")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM exams")
    exams = [row[0] for row in cursor.fetchall()]

    cursor.execute("SELECT username FROM users WHERE role='teacher'")
    teachers = [row[0] for row in cursor.fetchall()]
    conn.close()

    return render_template("admin_dashboard.html", exams=exams, teachers=teachers)

@app.route("/admin/edit_exams", methods=["POST"])
def edit_exams():
    conn = get_connection()
    cursor = conn.cursor()
    if "add_exam" in request.form:
        try:
            cursor.execute("INSERT INTO exams (name) VALUES (%s)", (request.form['exam_name'],))
        except mysql.connector.errors.IntegrityError:
            pass
    elif "remove_exam" in request.form:
        cursor.execute("DELETE FROM exams WHERE name=%s", (request.form['exam_to_remove'],))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_dashboard"))

@app.route("/admin/edit_teachers", methods=["POST"])
def edit_teachers():
    conn = get_connection()
    cursor = conn.cursor()
    if "add_teacher" in request.form:
        try:
            cursor.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, 'teacher')",
                           (request.form['new_teacher'], request.form['teacher_password']))
        except mysql.connector.errors.IntegrityError:
            pass
    elif "remove_teacher" in request.form:
        cursor.execute("DELETE FROM users WHERE username=%s AND role='teacher'",
                       (request.form['teacher_to_remove'],))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/add_student", methods=["POST"])
def add_student():
    adm = request.form["new_student"]
    password = request.form["student_password"]
    db = get_connection()
    cursor = db.cursor()
    cursor.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, 'student')", (adm, password))
    db.commit()
    return redirect("/admin/dashboard")


@app.route("/admin/remove_student", methods=["POST"])
def remove_student():
    adm = request.form["student_to_remove"]
    db = get_connection()
    cursor = db.cursor()
    cursor.execute("DELETE FROM users WHERE username = %s AND role = 'student'", (adm,))
    db.commit()
    return redirect("/admin/dashboard")


@app.route("/admin/upload_students", methods=["POST"])
def upload_students():
    if "students_file" not in request.files:
        return "Missing file", 400
    file = request.files["students_file"]
    if file.filename == "":
        return "No selected file", 400

    stream = StringIO(file.stream.read().decode("UTF8"))
    reader = csv.DictReader(stream)

    required_fields = {"admission_number", "password", "name"}
    if not required_fields.issubset(reader.fieldnames):
        return "CSV must contain 'admission_number', 'password', and 'name' columns", 400

    db = get_connection()
    cursor = db.cursor()

    for row in reader:
        adm = row["admission_number"]
        pw = row["password"]
        name = row["name"]

        # Insert into users table
        cursor.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, 'student')", (adm, pw))

        # Insert into student table
        cursor.execute("INSERT INTO student (admission_number, name) VALUES (%s, %s)", (adm, name))

    db.commit()
    return redirect("/admin/dashboard")


@app.route("/teacher/dashboard")
def teacher_dashboard():
    if session.get("role") != "teacher": return redirect("/")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM exams")
    exams = [row[0] for row in cursor.fetchall()]
    conn.close()
    return render_template("teacher_dashboard.html", classes=["A"], exams=exams)

@app.route("/teacher/upload_grades", methods=["POST"])
def upload_grades():
    exam_name = request.form['exam']
    file = request.files['grades_file']

    conn = get_connection()
    cursor = conn.cursor()

    # Get exam ID
    cursor.execute("SELECT id FROM exams WHERE name=%s", (exam_name,))
    result = cursor.fetchone()
    if not result:
        flash("Exam not found.")
        return redirect(url_for("teacher_dashboard"))
    exam_id = result[0]

    decoded = file.read().decode('utf-8').splitlines()
    reader = csv.DictReader(decoded)

    for row in reader:
        student = row['admission_number']
        for subject, score in row.items():
            if subject == "admission_number":
                continue
            try:
                score_val = int(score.strip()) if score.strip().isdigit() or score.strip() == "-1" else -1
                cursor.execute("""
                    INSERT INTO marks (student_username, exam_id, subject, score)
                    VALUES (%s, %s, %s, %s)
                """, (student, exam_id, subject, score_val))
            except Exception as e:
                print("Error inserting row:", e)

    conn.commit()
    conn.close()
    return redirect(url_for("teacher_dashboard"))


@app.route("/teacher/update_marks", methods=["POST"])
def update_marks():
    try:
        adm = request.form["admission_number"]
        exam_name = request.form["exam_name"]
        subject = request.form["subject"]
        score = int(request.form["score"])
    except KeyError as e:
        return f"Missing field: {e}", 400
    except ValueError:
        return "Score must be a number", 400

    db = get_connection()
    cursor = db.cursor(dictionary=True)

    # Check or create exam
    cursor.execute("SELECT id FROM exams WHERE name = %s", (exam_name,))
    exam = cursor.fetchone()
    if not exam:
        cursor.execute("INSERT INTO exams (name) VALUES (%s)", (exam_name,))
        db.commit()
        exam_id = cursor.lastrowid
    else:
        exam_id = exam["id"]

    # Insert or update mark
    cursor.execute("""
        INSERT INTO marks (student_username, exam_id, subject, score)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE score = VALUES(score)
    """, (adm, exam_id, subject, score))

    db.commit()
    return redirect("/teacher/dashboard")


@app.route("/student/dashboard")
def student_dashboard():
    adm = session.get("user")

    db = get_connection()
    cursor = db.cursor(dictionary=True)

    # Get student's name
    cursor.execute("SELECT name FROM student WHERE admission_number = %s", (adm,))
    result = cursor.fetchone()
    if not result:
        student_name = adm  # fallback to admission number
    else:
        student_name = result["name"]

    # Get list of exams
    cursor.execute("""
        SELECT exams.name
        FROM exams
        JOIN marks ON exams.id = marks.exam_id
        WHERE marks.student_username = %s
        GROUP BY exams.name
    """, (adm,))
    exam_list = [row["name"] for row in cursor.fetchall()]

    return render_template("student_dashboard.html", student_name=student_name, exam_list=exam_list)



@app.route("/student/marks", methods=["POST"])
def student_marks():
    adm = session['user']
    exam_name = request.form['exam_name']
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id FROM exams WHERE name=%s", (exam_name,))
    result = cursor.fetchone()
    if not result:
        flash("Exam not found.")
        return redirect(url_for("student_dashboard"))
    exam_id = result['id']

    cursor.execute("""
        SELECT subject, score FROM marks
        WHERE student_username = %s AND exam_id = %s
    """, (adm, exam_id))

    marks = []
    for row in cursor.fetchall():
        marks.append({
            "subject": row['subject'],
            "score": row['score']
        })

    conn.close()
    return render_template("student_marks.html", exam_name=exam_name, marks=marks)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))  # or your login page


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5005, debug=False)
