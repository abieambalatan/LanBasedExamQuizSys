"""Django views for the existing student, teacher, and administrator APIs."""

import json
import mimetypes
import os
from pathlib import Path
import re
import secrets
import time
import uuid

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login as django_login, logout as django_logout
from django.core.exceptions import SuspiciousFileOperation
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect
from django.middleware.csrf import get_token, rotate_token
from django.utils._os import safe_join

from .db import get_db
from .assessment_activity import normalize_activity_log, activity_summary, merge_activity_logs
from .accounts import RETIRED_PREFIX, permanently_delete_account
from .constants import YEAR_LEVELS, points_per_question, question_point_values
from .http import json_response, read_json
from .models import SchoolOption, timestamp
from .security import generate_password_hash, check_password_hash
from .school_options import option_values, school_options_payload, sections_for_department
from .targets import class_can_access, normalize_target_classes, save_target_classes, student_scope_sql, target_classes, target_summary


BASE_DIR = str(settings.BASE_DIR)
ADMIN_USERNAME = os.environ.get("EXAM_PORTAL_ADMIN_USERNAME", "administrator")
ADMIN_PASSWORD_FILE = os.path.join(BASE_DIR, ".admin_password")


def _load_admin_password():
    env_password = os.environ.get("EXAM_PORTAL_ADMIN_PASSWORD")
    if env_password:
        return env_password
    if os.path.exists(ADMIN_PASSWORD_FILE):
        try:
            with open(ADMIN_PASSWORD_FILE, "r", encoding="utf-8") as handle:
                saved = handle.read().strip()
            if saved:
                os.environ["EXAM_PORTAL_ADMIN_PASSWORD"] = saved
                return saved
        except OSError:
            pass
    return None


ADMIN_PASSWORD = _load_admin_password()


def serve_frontend(request, path):
    if any(part.startswith(".") for part in Path(path).parts):
        raise Http404
    try:
        filename = Path(safe_join(settings.BASE_DIR, "files", path))
    except SuspiciousFileOperation as error:
        raise Http404 from error
    if not filename.is_file():
        raise Http404
    account = None
    if filename.name == "administrator.html":
        account = current_admin_account(request)
        if not account:
            return HttpResponseRedirect("/login")
        if account["role"] != "teacher":
            return HttpResponseRedirect("/admin/")
    elif filename.name == "index.html":
        account = current_student_account(request)
    if filename.suffix == ".html":
        get_token(request)
    if filename.name in ("index.html", "administrator.html", "login.html"):
        content = filename.read_text(encoding="utf-8")
        options_json = json.dumps(school_options_payload()).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
        content = content.replace(
            "window.ARALHUB_SCHOOL_OPTIONS = {};",
            f"window.ARALHUB_SCHOOL_OPTIONS = {options_json};",
        )
        account_json = json.dumps(account).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
        content = content.replace("window.ARALHUB_CURRENT_USER = null;", f"window.ARALHUB_CURRENT_USER = {account_json};")
        response = HttpResponse(content, content_type="text/html; charset=utf-8")
        response["Cache-Control"] = "no-store"
        return response
    content_type = mimetypes.guess_type(str(filename))[0] or "application/octet-stream"
    return FileResponse(filename.open("rb"), content_type=content_type)


def csrf_token(request):
    return json_response({"csrfToken": get_token(request)})


def current_admin_account(request):
    user = request.user
    if user.is_authenticated and user.is_active and user.is_staff and user.is_superuser:
        return {"role": "admin", "name": user.get_full_name() or user.username, "username": user.username, "department": "ALL"}
    account = request.session.get("account")
    if not isinstance(account, dict):
        return False
    if account.get("role") != "teacher" or not account.get("username"):
        return False
    conn = get_db()
    teacher = conn.execute(
        "SELECT id, username, name, department, password_hash FROM teachers WHERE username=? AND deleted_at IS NULL",
        (account["username"],),
    ).fetchone()
    departments = [row["department"] for row in conn.execute(
        "SELECT department FROM teacher_departments WHERE teacher_username=? ORDER BY department",
        (teacher["username"] if teacher else account["username"],),
    ).fetchall()]
    conn.close()
    if teacher and account.get("teacherId") == teacher["id"]:
        return {"role": "teacher", "name": teacher["name"], "username": teacher["username"], "department": teacher["department"], "departments": departments}
    request.session.flush()
    rotate_token(request)
    return False


def current_student_account(request):
    account = request.session.get("account")
    if not isinstance(account, dict) or account.get("role") != "student":
        return None
    conn = get_db()
    student = conn.execute(
        "SELECT id, name, roll_no, department, section, year_level FROM students WHERE id=? AND deleted_at IS NULL",
        (account.get("studentId"),),
    ).fetchone()
    conn.close()
    if student:
        return {"role": "student", "studentId": student["id"], "name": student["name"], "rollNo": student["roll_no"], "department": student["department"], "section": student["section"] or "", "yearLevel": student["year_level"] or ""}
    request.session.flush()
    rotate_token(request)
    return None


def require_admin(request):
    return bool(current_admin_account(request))


def normalize_answer(text):
    return (text or "").strip().lower()


# ---------------------------------------------------------------- frontend
def index(request):
    return serve_frontend(request, "index.html")


def administrator_page(request):
    return HttpResponseRedirect("/login")


def login_page(request):
    return serve_frontend(request, "login.html")


def student_page(request):
    return serve_frontend(request, "index.html")


def teacher_page(request):
    return serve_frontend(request, "administrator.html")


def legacy_admin_page(request):
    return HttpResponseRedirect("/login")


# ---------------------------------------------------------------- auth
def admin_login(request):
    data = read_json(request)
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    user = authenticate(request, username=username, password=password)
    if user and user.is_active and user.is_staff and user.is_superuser:
        request.session.flush()
        django_login(request, user)
        request.portal_session_cookie = settings.SESSION_COOKIE_NAME
        return json_response({"ok": True, "role": "admin", "name": user.get_full_name() or user.username, "redirect": "/admin/"})
    conn = get_db()
    teacher = conn.execute(
        "SELECT id, username, name, department, password_hash FROM teachers WHERE username=? AND deleted_at IS NULL",
        (username,),
    ).fetchone()
    departments = [row["department"] for row in conn.execute(
        "SELECT department FROM teacher_departments WHERE teacher_username=? ORDER BY department",
        (teacher["username"] if teacher else username,),
    ).fetchall()]
    conn.close()
    if teacher and check_password_hash(teacher["password_hash"], password):
        request.session.flush()
        rotate_token(request)
        request.session["account"] = {"role": "teacher", "teacherId": teacher["id"], "name": teacher["name"], "username": teacher["username"], "department": teacher["department"]}
        return json_response({"ok": True, "role": "teacher", "name": teacher["name"], "username": teacher["username"], "department": teacher["department"], "departments": departments})
    return json_response({"error": "Incorrect username or password."}, status=401)


def logout(request):
    django_logout(request)
    rotate_token(request)
    return json_response({"ok": True})


def list_teachers(request):
    account = current_admin_account(request)
    if not account or account["role"] != "admin":
        return json_response({"error": "Admin access required."}, status=403)
    conn = get_db()
    rows = conn.execute(
          """SELECT t.id, t.name, t.username, t.department, t.created_at,
                  COUNT(DISTINCT e.id) AS exam_count,
                    COUNT(DISTINCT r.id) AS attempt_count
           FROM teachers t
           LEFT JOIN exams e ON e.created_by = t.username
                LEFT JOIN results r ON r.teacher_username = t.username
              WHERE t.deleted_at IS NULL
           GROUP BY t.id
           ORDER BY t.department, t.name"""
    ).fetchall()
    conn.close()
    return json_response([dict(row) for row in rows])


def delete_teacher(request, teacher_id):
    account = current_admin_account(request)
    if not account or account["role"] != "admin":
        return json_response({"error": "Admin access required."}, status=403)
    conn = get_db()
    teacher = conn.execute("SELECT username FROM teachers WHERE id=?", (teacher_id,)).fetchone()
    if not teacher:
        conn.close()
        return json_response({"error": "Teacher not found."}, status=404)
    if read_json(request).get("confirmation") != "DELETE":
        conn.close()
        return json_response({"error": "Type DELETE to confirm account deletion."}, status=400)
    conn.close()
    deleted = permanently_delete_account("teacher", teacher_id)
    if not deleted:
        return json_response({"error": "Teacher not found."}, status=404)
    return json_response({"ok": True, "permanentlyDeleted": True})


def restore_teacher(request, teacher_id):
    account = current_admin_account(request)
    if not account or account["role"] != "admin":
        return json_response({"error": "Admin access required."}, status=403)
    conn = get_db()
    restored = conn.execute(
        "UPDATE teachers SET deleted_at=NULL WHERE id=? AND deleted_at IS NOT NULL",
        (teacher_id,),
    ).rowcount
    conn.commit()
    conn.close()
    if not restored:
        return json_response({"error": "Archived teacher not found."}, status=404)
    return json_response({"ok": True, "restored": True})


def list_archived_teachers(request):
    account = current_admin_account(request)
    if not account or account["role"] != "admin":
        return json_response({"error": "Admin access required."}, status=403)
    conn = get_db()
    rows = conn.execute(
        """SELECT t.id, t.name, t.username, t.department, t.created_at, t.deleted_at,
                  COUNT(DISTINCT e.id) AS exam_count,
                  COUNT(r.id) AS attempt_count
           FROM teachers t
           LEFT JOIN exams e ON e.created_by=t.username
           LEFT JOIN results r ON r.teacher_username=t.username
           WHERE t.deleted_at IS NOT NULL
           GROUP BY t.id
           ORDER BY t.deleted_at DESC"""
    ).fetchall()
    conn.close()
    return json_response([dict(row) for row in rows])


def reset_teacher_password(request, teacher_id):
    account = current_admin_account(request)
    if not account or account["role"] != "admin":
        return json_response({"error": "Admin access required."}, status=403)
    data = read_json(request)
    password = data.get("password") or ""
    if len(password) < 4:
        return json_response({"error": "Password must be at least 4 characters."}, status=400)
    conn = get_db()
    updated = conn.execute(
        "UPDATE teachers SET password_hash=? WHERE id=?",
        (generate_password_hash(password), teacher_id),
    ).rowcount
    conn.commit()
    conn.close()
    if not updated:
        return json_response({"error": "Teacher not found."}, status=404)
    return json_response({"ok": True})


# ---------------------------------------------------------------- students
def student_signup(request):
    data = read_json(request)
    first_name = (data.get("firstName") or "").strip()
    last_name = (data.get("lastName") or "").strip()
    middle_initial = (data.get("middleInitial") or "").strip()
    roll_no = (data.get("rollNo") or "").strip()
    department = (data.get("department") or "").strip().upper()
    section = (data.get("section") or "").strip().upper()
    year_level = (data.get("yearLevel") or "").strip()
    username = roll_no
    password = data.get("password") or ""

    if not first_name or not last_name:
        return json_response({"error": "Please enter your first name and last name."}, status=400)
    if len(first_name) > 255 or len(last_name) > 255:
        return json_response({"error": "First and last names must each be at most 255 characters."}, status=400)
    if middle_initial and not re.fullmatch(r"[^\W\d_]\.?", middle_initial):
        return json_response({"error": "Middle initial must be one letter, optionally followed by a period."}, status=400)
    middle_initial = middle_initial.rstrip(".").upper()
    name = f"{last_name}, {first_name}" + (f" {middle_initial}." if middle_initial else "")
    if not roll_no:
        return json_response({"error": "Please enter your ID number."}, status=400)
    if roll_no.startswith(RETIRED_PREFIX):
        return json_response({"error": "This ID number prefix is reserved. Use your school student ID."}, status=400)
    if department not in option_values(SchoolOption.DEPARTMENT):
        return json_response({"error": "Please select a valid department."}, status=400)
    if section not in sections_for_department(department, year_level):
        return json_response({"error": "Please select a valid section."}, status=400)
    if year_level not in YEAR_LEVELS:
        return json_response({"error": "Please select a valid year level."}, status=400)
    if len(password) < 4:
        return json_response({"error": "Password must be at least 4 characters."}, status=400)

    conn = get_db()
    if conn.execute("SELECT id FROM students WHERE roll_no=?", (roll_no,)).fetchone():
        conn.close()
        return json_response({"error": "This ID number is already registered. Please sign in instead."}, status=409)
    student_id = "stu_" + uuid.uuid4().hex[:10]
    conn.execute(
          """INSERT INTO students
              (id, name, first_name, last_name, middle_initial, roll_no, department, username,
               password_hash, teacher_username, section, year_level, created_at)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            student_id, name, first_name, last_name, middle_initial, roll_no, department, username,
            generate_password_hash(password), "", section, year_level, time.strftime("%Y-%m-%dT%H:%M:%S"),
        ),
    )
    conn.commit()
    conn.close()
    return json_response({"ok": True})


def list_managed_students(request):
    account = current_admin_account(request)
    if not account:
        return json_response({"error": "Teacher or admin access required."}, status=403)

    conn = get_db()
    if account["role"] == "admin":
        rows = conn.execute(
            """SELECT id, name, roll_no, department, section, year_level
               FROM students WHERE deleted_at IS NULL
               ORDER BY department, section, name"""
        ).fetchall()
    else:
        username = account["username"]
        rows = conn.execute(
            """SELECT s.id, s.name, s.roll_no, s.department, s.section, s.year_level
               FROM students s
               WHERE s.deleted_at IS NULL AND EXISTS (
                   SELECT 1 FROM teacher_departments td
                   WHERE td.department=s.department AND td.teacher_username=?
               )
               ORDER BY s.department, s.section, s.name""",
            (username,),
        ).fetchall()
    conn.close()
    return json_response([dict(row) for row in rows])


def list_archived_students(request):
    account = current_admin_account(request)
    if not account:
        return json_response({"error": "Teacher or admin access required."}, status=403)
    conn = get_db()
    if account["role"] == "admin":
        rows = conn.execute(
            """SELECT id, name, roll_no, department, section, year_level, deleted_at
               FROM students WHERE deleted_at IS NOT NULL
               ORDER BY department, section, name"""
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT s.id, s.name, s.roll_no, s.department, s.section, s.year_level, s.deleted_at
               FROM students s
               WHERE s.deleted_at IS NOT NULL AND EXISTS (
                   SELECT 1 FROM teacher_departments td
                   WHERE td.department=s.department AND td.teacher_username=?
               )
               ORDER BY s.department, s.section, s.name""",
            (account["username"],),
        ).fetchall()
    conn.close()
    return json_response([dict(row) for row in rows])


def archive_student(request, student_id):
    account = current_admin_account(request)
    if not account:
        return json_response({"error": "Teacher or admin access required."}, status=403)
    conn = get_db()
    student = conn.execute(
        "SELECT id, department, deleted_at FROM students WHERE id=?",
        (student_id,),
    ).fetchone()
    if not student:
        conn.close()
        return json_response({"error": "Student not found."}, status=404)
    if student["deleted_at"] and account["role"] == "teacher":
        conn.close()
        return json_response({"error": "This student account is already archived."}, status=409)
    if account["role"] == "teacher":
        assigned = conn.execute(
            "SELECT 1 FROM teacher_departments WHERE department=? AND teacher_username=?",
            (student["department"], account["username"]),
        ).fetchone()
        if not assigned:
            conn.close()
            return json_response({"error": "You can only archive students in your assigned programs."}, status=403)
    if read_json(request).get("confirmation") != "DELETE":
        conn.close()
        return json_response({"error": "Type DELETE to confirm account deletion."}, status=400)
    if account["role"] == "admin":
        conn.close()
        if not permanently_delete_account("student", student_id):
            return json_response({"error": "Student not found."}, status=404)
        return json_response({"ok": True, "permanentlyDeleted": True})
    conn.execute(
        "UPDATE students SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
        (timestamp(), student_id),
    )
    conn.commit()
    conn.close()
    return json_response({"ok": True})


def restore_student(request, student_id):
    account = current_admin_account(request)
    if not account or account["role"] != "admin":
        return json_response({"error": "Only the super admin can retrieve deleted accounts."}, status=403)
    conn = get_db()
    student = conn.execute(
        "SELECT id, department, deleted_at FROM students WHERE id=?",
        (student_id,),
    ).fetchone()
    if not student:
        conn.close()
        return json_response({"error": "Student not found."}, status=404)
    if not student["deleted_at"]:
        conn.close()
        return json_response({"error": "This student account is not archived."}, status=409)
    conn.execute("UPDATE students SET deleted_at=NULL WHERE id=?", (student_id,))
    conn.commit()
    conn.close()
    return json_response({"ok": True})


def reset_student_password(request, student_id):
    account = current_admin_account(request)
    if not account:
        return json_response({"error": "Teacher or admin access required."}, status=403)

    data = read_json(request)
    password = data.get("password") or ""
    if len(password) < 4:
        return json_response({"error": "Password must be at least 4 characters."}, status=400)

    conn = get_db()
    student = conn.execute(
        "SELECT id, department FROM students WHERE id=? AND deleted_at IS NULL",
        (student_id,),
    ).fetchone()
    if not student:
        conn.close()
        return json_response({"error": "Student not found."}, status=404)

    if account["role"] == "teacher":
        username = account["username"]
        assigned = conn.execute(
            "SELECT 1 FROM teacher_departments WHERE department=? AND teacher_username=?",
            (student["department"], username),
        ).fetchone()
        if not assigned:
            conn.close()
            return json_response({"error": "You can only reset passwords for students in your assigned programs."}, status=403)

    conn.execute(
        "UPDATE students SET password_hash=? WHERE id=?",
        (generate_password_hash(password), student_id),
    )
    conn.commit()
    conn.close()
    return json_response({"ok": True})


def student_login(request):
    data = read_json(request)
    student_id_number = (data.get("idNumber") or data.get("rollNo") or data.get("username") or "").strip()
    password = data.get("password") or ""

    if not student_id_number or not password:
        return json_response({"error": "Please enter your ID number and password."}, status=400)

    conn = get_db()
    s = conn.execute(
        "SELECT * FROM students WHERE deleted_at IS NULL AND (roll_no=? OR username=?) ORDER BY CASE WHEN roll_no=? THEN 0 ELSE 1 END LIMIT 1",
        (student_id_number, student_id_number, student_id_number),
    ).fetchone()
    if not s or not s["password_hash"] or not check_password_hash(s["password_hash"], password):
        conn.close()
        return json_response({"error": "Incorrect ID number or password."}, status=401)

    conn.close()
    request.session.flush()
    rotate_token(request)
    request.session["account"] = {
        "role": "student",
        "studentId": s["id"],
        "name": s["name"],
        "rollNo": s["roll_no"],
        "department": s["department"],
        "section": s["section"] or "",
        "yearLevel": s["year_level"] or "",
    }
    return json_response({
        "name": s["name"], "rollNo": s["roll_no"], "department": s["department"],
        "section": s["section"] or "",
        "yearLevel": s["year_level"] or "",
    })


def available_teachers(request):
    department = (request.GET.get("department") or "").strip().upper()
    if department not in option_values(SchoolOption.DEPARTMENT):
        return json_response([])
    conn = get_db()
    rows = conn.execute(
        """SELECT t.name, t.username FROM teachers t
           JOIN teacher_departments td ON td.teacher_username = t.username
           WHERE td.department=? AND t.deleted_at IS NULL ORDER BY t.name""",
        (department,),
    ).fetchall()
    conn.close()
    return json_response([{"name": row["name"], "username": row["username"]} for row in rows])


# ---------------------------------------------------------------- exam helpers
def _validate_and_normalize_questions(questions):
    """Returns (normalized_questions, error_message_or_None)."""
    if not isinstance(questions, list) or not questions:
        return None, "Add at least one question."
    parts = {"multiple_choice": 1, "identification": 2, "true_false": 3, "matching": 4}
    normalized = []
    for i, q in enumerate(questions):
        if not isinstance(q, dict):
            return None, f"Question {i+1} has an invalid format."
        text = (q.get("text") or "").strip()
        if not text:
            return None, f"Question {i+1} needs question text."
        qtype = (q.get("type") or "multiple_choice").strip().lower()
        if qtype not in parts:
            return None, f"Question {i+1} has an unsupported question type."
        part = parts[qtype]

        if qtype == "identification":
            answer_text = (q.get("answerText") or "").strip().upper()
            if not answer_text:
                return None, f"Question {i+1} needs a correct answer."
            alternatives = q.get("alternatives") or []
            if not isinstance(alternatives, list):
                alternatives = []
            alternatives = [str(a).strip().upper() for a in alternatives if str(a).strip()]
            normalized.append(
                {
                    "part": part or 2,
                    "type": "identification",
                    "text": text,
                    "option_a": "", "option_b": "", "option_c": "", "option_d": "",
                    "correct": 0,
                    "answer_text": answer_text,
                    "alternatives": alternatives,
                    "options": [],
                }
            )
        else:
            opts = ["True", "False"] if qtype == "true_false" else q.get("options") or []
            if not isinstance(opts, list) or any(not isinstance(o, str) or not o.strip() for o in opts):
                return None, f"Question {i+1} needs non-empty answer choices."
            if qtype == "multiple_choice" and len(opts) != 4:
                return None, f"Question {i+1} needs all four options filled in."
            if qtype == "matching" and not 2 <= len(opts) <= 26:
                return None, f"Question {i+1} needs 2 to 26 matching choices."
            correct = q.get("correct")
            if not isinstance(correct, int) or isinstance(correct, bool) or not 0 <= correct < len(opts):
                return None, f"Question {i+1} needs a correct option selected."
            opts = [option.strip() for option in opts]
            padded = opts + [""] * max(0, 4 - len(opts))
            normalized.append(
                {
                    "part": part or 1,
                    "type": qtype,
                    "text": text,
                    "option_a": padded[0], "option_b": padded[1],
                    "option_c": padded[2], "option_d": padded[3],
                    "correct": correct,
                    "answer_text": "",
                    "alternatives": [],
                    "options": opts,
                }
            )
    return normalized, None


def _insert_questions(conn, exam_id, normalized_questions):
    for i, q in enumerate(normalized_questions):
        qid = "q_" + uuid.uuid4().hex[:10]
        conn.execute(
            """INSERT INTO questions
               (id, exam_id, position, part, type, text, option_a, option_b, option_c, option_d,
                correct, answer_text, alternatives_json, options_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                qid, exam_id, i, q["part"], q["type"], q["text"],
                q["option_a"], q["option_b"], q["option_c"], q["option_d"],
                q["correct"], q["answer_text"], json.dumps(q["alternatives"]), json.dumps(q["options"]),
            ),
        )


def _question_options(q):
    if q["type"] == "identification":
        return []
    if q["type"] == "true_false":
        return ["True", "False"]
    if q["type"] == "matching":
        return json.loads(q["options_json"] or "[]")
    return [q["option_a"], q["option_b"], q["option_c"], q["option_d"]]


def _question_to_admin_dict(q):
    return {
        "id": q["id"],
        "part": q["part"],
        "type": q["type"],
        "text": q["text"],
        "options": _question_options(q),
        "correct": q["correct"],
        "answerText": q["answer_text"],
        "alternatives": json.loads(q["alternatives_json"] or "[]"),
    }


def _exam_departments(conn, exam_id):
    return [row["department"] for row in conn.execute(
        "SELECT department FROM exam_departments WHERE exam_id=? ORDER BY department", (exam_id,)
    ).fetchall()]


# ---------------------------------------------------------------- exams
def list_exams(request):
    department = (request.GET.get("department") or "").strip().upper()
    teacher_username = (request.GET.get("teacherUsername") or "").strip()
    teacher_usernames = [item.strip() for item in (request.GET.get("teacherUsernames") or "").split(",") if item.strip()]
    year_level = (request.GET.get("yearLevel") or "").strip()
    section = (request.GET.get("section") or "").strip().upper()
    student_view = request.GET.get("studentView") == "1"
    account = current_admin_account(request)
    student = current_student_account(request)
    if student_view:
        if not student:
            return json_response({"error": "Student sign in required."}, status=401)
        department = student["department"]
        year_level = student["yearLevel"]
        section = student["section"]
    elif not account:
        return json_response({"error": "Sign in required."}, status=401)
    conn = get_db()
    if student_view:
        exams = conn.execute(
            "SELECT * FROM exams WHERE " + student_scope_sql() + " AND (created_by='' OR EXISTS (SELECT 1 FROM teachers t WHERE t.username=exams.created_by AND t.deleted_at IS NULL)) ORDER BY created_at DESC",
            (department, year_level, section, department, year_level, section),
        ).fetchall()
    elif account and account["role"] == "teacher":
        exams = conn.execute(
            "SELECT * FROM exams WHERE created_by=? AND EXISTS (SELECT 1 FROM teachers t WHERE t.username=exams.created_by AND t.deleted_at IS NULL) ORDER BY created_at DESC",
            (account["username"],),
        ).fetchall()
    elif teacher_usernames:
        placeholders = ",".join("?" for _ in teacher_usernames)
        exams = conn.execute(
            f"SELECT * FROM exams WHERE created_by IN ({placeholders}) AND EXISTS (SELECT 1 FROM teachers t WHERE t.username=exams.created_by AND t.deleted_at IS NULL) ORDER BY created_at DESC",
            teacher_usernames,
        ).fetchall()
    elif teacher_username:
        exams = conn.execute(
            "SELECT * FROM exams WHERE created_by=? AND EXISTS (SELECT 1 FROM teachers t WHERE t.username=exams.created_by AND t.deleted_at IS NULL) ORDER BY created_at DESC",
            (teacher_username,),
        ).fetchall()
    elif department in option_values(SchoolOption.DEPARTMENT):
        exams = conn.execute(
            "SELECT * FROM exams WHERE EXISTS (SELECT 1 FROM exam_departments ed WHERE ed.exam_id=exams.id AND ed.department=?) AND (created_by='' OR EXISTS (SELECT 1 FROM teachers t WHERE t.username=exams.created_by AND t.deleted_at IS NULL)) ORDER BY created_at DESC",
            (department,),
        ).fetchall()
    else:
        exams = conn.execute("SELECT * FROM exams WHERE (created_by='' OR EXISTS (SELECT 1 FROM teachers t WHERE t.username=exams.created_by AND t.deleted_at IS NULL)) ORDER BY created_at DESC").fetchall()
    out = []
    for e in exams:
        qcount = conn.execute(
            "SELECT COUNT(*) c FROM questions WHERE exam_id=?", (e["id"],)
        ).fetchone()["c"]
        attempts = conn.execute(
            "SELECT COUNT(*) c FROM results WHERE exam_id=?", (e["id"],)
        ).fetchone()["c"]
        departments = _exam_departments(conn, e["id"])
        out.append(
            {
                "id": e["id"],
                "title": e["title"],
                "activityType": e["activity_type"] or "exam",
                "duration": e["duration"],
                "department": e["department"] or (departments[0] if departments else "ALL"),
                "departments": departments,
                "targetClasses": target_classes(conn, e) if not student_view else [{"department": department, "yearLevel": year_level, "section": section}],
                "yearLevel": year_level if student_view else e["year_level"] or "",
                "subject": e["subject"] or "",
                "sectionScope": section if student_view else e["section_scope"] or "ALL",
                "createdBy": e["created_by"] or "",
                "questionCount": qcount,
                "totalPoints": sum(points_per_question(e["activity_type"], q["type"]) for q in conn.execute("SELECT type FROM questions WHERE exam_id=?", (e["id"],)).fetchall()),
                "attempts": attempts,
                "returned": bool(student_view and conn.execute(
                    "SELECT 1 FROM portal_submissionreturn WHERE exam_id=? AND roll_no=? AND resubmitted_id='' LIMIT 1",
                    (e["id"], student["rollNo"]),
                ).fetchone()),
            }
        )
    conn.close()
    return json_response(out)


def create_exam(request):
    account = current_admin_account(request)
    if not account:
        return json_response({"error": "Your teacher session has expired. Sign in again to publish your assessment.", "code": "staff_session_expired"}, status=401)
    if account["role"] != "teacher":
        return json_response({"error": "The browser is signed in with a different account. Sign in with your teacher account to publish this assessment.", "code": "teacher_required"}, status=403)
    conn = get_db()
    data = read_json(request)
    if data.get("expectedTeacherUsername") and data["expectedTeacherUsername"] != account["username"]:
        conn.close()
        return json_response({"error": "Your signed-in teacher account changed. Sign in again with the account that started this assessment.", "code": "teacher_account_changed"}, status=403)
    title = (data.get("title") or "").strip()
    activity_type = (data.get("activityType") or "exam").strip().lower()
    duration = data.get("duration")
    targets, target_error = normalize_target_classes(data)
    if target_error:
        conn.close()
        return json_response({"error": target_error}, status=400)
    departments, year_level, section_scope = target_summary(targets)
    subject = (data.get("subject") or "").strip()
    questions = data.get("questions") or []

    if not title:
        conn.close()
        return json_response({"error": "Please enter an exam title."}, status=400)
    if activity_type not in ("exam", "quiz"):
        conn.close()
        return json_response({"error": "Choose either an exam or a quiz."}, status=400)
    if not isinstance(duration, int) or duration < 1:
        conn.close()
        return json_response({"error": "Duration must be at least 1 minute."}, status=400)
    if not departments or any(department not in option_values(SchoolOption.DEPARTMENT) for department in departments):
        conn.close()
        return json_response({"error": "Select at least one valid exam department."}, status=400)
    if not subject:
        conn.close()
        return json_response({"error": "Please enter the subject."}, status=400)
    normalized, err = _validate_and_normalize_questions(questions)
    if err:
        conn.close()
        return json_response({"error": err}, status=400)

    exam_id = "exam_" + uuid.uuid4().hex[:10]
    conn.execute(
        "INSERT INTO exams (id, title, duration, department, created_by, year_level, subject, section_scope, activity_type, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (exam_id, title, duration, departments[0], account["username"], year_level, subject, section_scope, activity_type, time.strftime("%Y-%m-%dT%H:%M:%S")),
    )
    conn.executemany("INSERT INTO exam_departments (exam_id, department) VALUES (?,?)", [(exam_id, department) for department in set(departments)])
    save_target_classes(conn, exam_id, targets)
    _insert_questions(conn, exam_id, normalized)
    conn.commit()
    conn.close()
    return json_response({"ok": True, "id": exam_id})


def get_exam_admin(request, exam_id):
    """Full exam detail INCLUDING correct answers — used by the admin edit screen."""
    if not require_admin(request):
        return json_response({"error": "Unauthorized."}, status=401)
    conn = get_db()
    exam = conn.execute("SELECT * FROM exams WHERE id=? AND (created_by='' OR EXISTS (SELECT 1 FROM teachers t WHERE t.username=exams.created_by AND t.deleted_at IS NULL))", (exam_id,)).fetchone()
    if not exam:
        conn.close()
        return json_response({"error": "Exam not found."}, status=404)
    account = current_admin_account(request)
    if account and account["role"] == "teacher" and exam["created_by"] != account["username"]:
        conn.close()
        return json_response({"error": "You can only view your own exams."}, status=403)
    qs = conn.execute(
        "SELECT * FROM questions WHERE exam_id=? ORDER BY position", (exam_id,)
    ).fetchall()
    departments = _exam_departments(conn, exam_id)
    targets = target_classes(conn, exam)
    conn.close()
    return json_response(
        {
            "id": exam["id"],
            "title": exam["title"],
            "activityType": exam["activity_type"] or "exam",
            "duration": exam["duration"],
            "department": exam["department"] or (departments[0] if departments else "ALL"),
            "departments": departments,
            "targetClasses": targets,
            "yearLevel": exam["year_level"] or "",
            "subject": exam["subject"] or "",
            "sectionScope": exam["section_scope"] or "ALL",
            "questions": [_question_to_admin_dict(q) for q in qs],
        }
    )


def update_exam(request, exam_id):
    account = current_admin_account(request)
    if not account:
        return json_response({"error": "Your teacher session has expired. Sign in again to save your assessment.", "code": "staff_session_expired"}, status=401)
    if account["role"] != "teacher":
        return json_response({"error": "Sign in with the assessment's teacher account to save your changes.", "code": "teacher_required"}, status=403)
    conn = get_db()
    exam = conn.execute("SELECT * FROM exams WHERE id=? AND (created_by='' OR EXISTS (SELECT 1 FROM teachers t WHERE t.username=exams.created_by AND t.deleted_at IS NULL))", (exam_id,)).fetchone()
    if not exam:
        conn.close()
        return json_response({"error": "Exam not found."}, status=404)
    if exam["created_by"] != account["username"]:
        conn.close()
        return json_response({"error": "Sign in with the teacher account that owns this assessment to save your changes.", "code": "teacher_account_changed"}, status=403)

    data = read_json(request)
    title = (data.get("title") or "").strip()
    activity_type = (data.get("activityType") or "exam").strip().lower()
    duration = data.get("duration")
    targets, target_error = normalize_target_classes(data)
    if target_error:
        conn.close()
        return json_response({"error": target_error}, status=400)
    departments, year_level, section_scope = target_summary(targets)
    subject = (data.get("subject") or "").strip()
    questions = data.get("questions") or []

    if not title:
        conn.close()
        return json_response({"error": "Please enter an exam title."}, status=400)
    if activity_type not in ("exam", "quiz"):
        conn.close()
        return json_response({"error": "Choose either an exam or a quiz."}, status=400)
    if not isinstance(duration, int) or duration < 1:
        conn.close()
        return json_response({"error": "Duration must be at least 1 minute."}, status=400)
    if not departments or any(department not in option_values(SchoolOption.DEPARTMENT) for department in departments):
        conn.close()
        return json_response({"error": "Select at least one valid exam department."}, status=400)
    if not subject:
        conn.close()
        return json_response({"error": "Please enter the subject."}, status=400)
    normalized, err = _validate_and_normalize_questions(questions)
    if err:
        conn.close()
        return json_response({"error": err}, status=400)

    conn.execute(
        "UPDATE exams SET title=?, duration=?, department=?, year_level=?, subject=?, section_scope=?, activity_type=? WHERE id=?",
        (title, duration, departments[0], year_level, subject, section_scope, activity_type, exam_id),
    )
    conn.execute("DELETE FROM exam_departments WHERE exam_id=?", (exam_id,))
    conn.executemany("INSERT INTO exam_departments (exam_id, department) VALUES (?,?)", [(exam_id, department) for department in set(departments)])
    save_target_classes(conn, exam_id, targets)
    conn.execute("DELETE FROM questions WHERE exam_id=?", (exam_id,))
    _insert_questions(conn, exam_id, normalized)
    conn.commit()
    conn.close()
    return json_response({"ok": True, "id": exam_id})


def delete_exam(request, exam_id):
    account = current_admin_account(request)
    if not account or account["role"] != "teacher":
        return json_response({"error": "Only the exam's teacher can delete it."}, status=403)
    conn = get_db()
    exam = conn.execute("SELECT created_by FROM exams WHERE id=?", (exam_id,)).fetchone()
    if not exam:
        conn.close()
        return json_response({"error": "Exam not found."}, status=404)
    if exam["created_by"] != account["username"]:
        conn.close()
        return json_response({"error": "You can only delete your own exams."}, status=403)
    conn.execute("DELETE FROM questions WHERE exam_id=?", (exam_id,))
    conn.execute("DELETE FROM results WHERE exam_id=?", (exam_id,))
    conn.execute("DELETE FROM portal_assessmentactivity WHERE exam_id=?", (exam_id,))
    conn.execute("DELETE FROM exam_departments WHERE exam_id=?", (exam_id,))
    conn.execute("DELETE FROM exam_target_classes WHERE exam_id=?", (exam_id,))
    conn.execute("DELETE FROM exams WHERE id=?", (exam_id,))
    conn.commit()
    conn.close()
    return json_response({"ok": True})


def take_exam(request, exam_id):
    """Returns exam + questions WITHOUT the correct answers (student view)."""
    student = current_student_account(request)
    if not student:
        return json_response({"error": "Student sign in required."}, status=401)
    student_department = student["department"]
    student_year_level = student["yearLevel"]
    student_section = student["section"]
    conn = get_db()
    exam = conn.execute("SELECT * FROM exams WHERE id=? AND (created_by='' OR EXISTS (SELECT 1 FROM teachers t WHERE t.username=exams.created_by AND t.deleted_at IS NULL))", (exam_id,)).fetchone()
    if not exam:
        conn.close()
        return json_response({"error": "Exam not found."}, status=404)
    if not class_can_access(conn, exam_id, student_department, student_year_level, student_section):
        conn.close()
        return json_response({"error": "This exam is not available for your department, year level, and section."}, status=403)
    if conn.execute(
        "SELECT 1 FROM results WHERE exam_id=? AND roll_no=?",
        (exam_id, student["rollNo"]),
    ).fetchone():
        conn.close()
        return json_response({"error": "This assessment has already been submitted. Student access to its questions is closed."}, status=403)
    qs = conn.execute(
        "SELECT * FROM questions WHERE exam_id=? ORDER BY position", (exam_id,)
    ).fetchall()
    returned = conn.execute(
        "SELECT id, snapshot FROM portal_submissionreturn WHERE exam_id=? AND roll_no=? AND resubmitted_id='' ORDER BY returned_at DESC, id DESC LIMIT 1",
        (exam_id, student["rollNo"]),
    ).fetchone()
    exam_departments = _exam_departments(conn, exam_id)
    conn.close()
    questions_by_part = {}
    for q in qs:
        item = {"id": q["id"], "part": q["part"], "type": q["type"], "text": q["text"]}
        item["options"] = _question_options(q)
        questions_by_part.setdefault(q["part"], []).append(item)
    out_questions = []
    for part in sorted(questions_by_part):
        part_questions = questions_by_part[part]
        secrets.SystemRandom().shuffle(part_questions)
        out_questions.extend(part_questions)
    return json_response(
        {
            "id": exam["id"],
            "title": exam["title"],
            "activityType": exam["activity_type"] or "exam",
            "duration": exam["duration"],
            "department": exam["department"] or "ALL",
            "departments": exam_departments,
            "yearLevel": student_year_level,
            "subject": exam["subject"] or "",
            "sectionScope": student_section,
            "pointsPerQuestion": points_per_question(exam["activity_type"]),
            "pointsByType": question_point_values(exam["activity_type"]),
            "questions": out_questions,
            "returnedAttempt": {"returnId": returned["id"], "answers": json.loads(json.loads(returned["snapshot"])["answers_json"])} if returned else None,
        }
    )


# ---------------------------------------------------------------- results
PASSING_PERCENT = 50


def _grade_status(percent):
    return "passed" if float(percent or 0) >= PASSING_PERCENT else "failed"


def _grade_and_review(qs, answers, activity_type="exam"):
    """Grade each question using its activity and question type."""
    score = 0
    total = 0
    review = []
    for q in qs:
        question_points = points_per_question(activity_type, q["type"])
        total += question_points
        chosen = answers.get(q["id"])
        if q["type"] == "identification":
            chosen_val = str(chosen).strip().upper() if chosen not in (None, "") else None
            accepted = [normalize_answer(q["answer_text"])] + [
                normalize_answer(a) for a in json.loads(q["alternatives_json"] or "[]")
            ]
            is_correct = chosen_val is not None and normalize_answer(chosen_val) in accepted
            if is_correct:
                score += question_points
            review.append(
                {
                    "text": q["text"],
                    "type": "identification",
                    "options": [],
                    "correct": None,
                    "answer": q["answer_text"],
                    "chosen": chosen_val,
                    "isCorrect": is_correct,
                    "pointsAwarded": question_points if is_correct else 0,
                    "pointsPossible": question_points,
                }
            )
        else:
            options = _question_options(q)
            if chosen in (None, ""):
                chosen_idx = None
            elif q["type"] == "true_false" and isinstance(chosen, bool):
                chosen_idx = 0 if chosen else 1
            elif q["type"] == "true_false" and str(chosen).strip().upper() in ("TRUE", "FALSE"):
                chosen_idx = 0 if str(chosen).strip().upper() == "TRUE" else 1
            elif isinstance(chosen, (int, str)) and not isinstance(chosen, bool):
                chosen_idx = int(chosen)
            else:
                raise ValueError("Answer must be a choice index")
            if chosen_idx is not None and not 0 <= chosen_idx < len(options):
                raise ValueError("Answer choice is out of range")
            is_correct = chosen_idx is not None and chosen_idx == q["correct"]
            if is_correct:
                score += question_points
            review.append(
                {
                    "text": q["text"],
                    "type": q["type"],
                    "options": options,
                    "correct": q["correct"],
                    "chosen": chosen_idx,
                    "isCorrect": is_correct,
                    "pointsAwarded": question_points if is_correct else 0,
                    "pointsPossible": question_points,
                }
            )
    return score, total, review


def _student_result_summary(result, exam):
    """Allowlist receipt fields. Never include questions, answers or grading keys."""
    return {
        "id": result["id"], "examId": result["exam_id"], "examTitle": result["exam_title"],
        "activityType": exam["activity_type"] or "exam",
        "pointsPerQuestion": points_per_question(exam["activity_type"]),
        "pointsByType": question_point_values(exam["activity_type"]),
        "name": result["name"], "rollNo": result["roll_no"], "department": result["department"],
        "section": result["section"] or "", "yearLevel": result["year_level"] or "",
        "subject": exam["subject"] or "", "score": result["score"], "total": result["total"],
        "percent": result["percent"], "gradeStatus": _grade_status(result["percent"]),
        "timeTakenSec": result["time_taken_sec"],
        "autoSubmitted": bool(result["auto_submitted"]), "submitReason": result["submit_reason"] or "manual",
        "submittedAt": result["submitted_at"],
    }


def submit_result(request):
    data = read_json(request)
    exam_id = data.get("examId")
    answers = data.get("answers") or {}
    try:
        time_taken_sec = max(0, int(data.get("timeTakenSec") or 0))
    except (ValueError, TypeError):
        return json_response({"error": "Invalid time taken."}, status=400)
    submission_key = data.get("submissionId") or ""
    if not isinstance(submission_key, str) or len(submission_key) > 128:
        return json_response({"error": "Invalid submission ID."}, status=400)
    auto_submitted = bool(data.get("autoSubmitted"))
    submit_reason = (data.get("submitReason") or "manual").strip().lower()
    if submit_reason not in ("manual", "time_limit", "tab_switch"):
        submit_reason = "manual"

    account = current_student_account(request)
    if not account:
        return json_response({"error": "Student sign in required."}, status=401)
    if not isinstance(answers, dict):
        return json_response({"error": "Answers must be an object."}, status=400)
    activity_log = normalize_activity_log(data.get("activityLog"))

    conn = get_db()
    conn.execute("BEGIN IMMEDIATE")
    if settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
        conn.execute("SELECT id FROM students WHERE id=? FOR UPDATE", (account.get("studentId"),))
    student = conn.execute(
        "SELECT id, name, roll_no, department, section, year_level FROM students WHERE id=? AND deleted_at IS NULL",
        (account.get("studentId"),),
    ).fetchone()
    if not student:
        conn.close()
        request.session.flush()
        rotate_token(request)
        return json_response({"error": "Student account not found. Please sign in again."}, status=401)
    name = student["name"]
    roll_no = student["roll_no"]
    exam = conn.execute("SELECT * FROM exams WHERE id=? AND (created_by='' OR EXISTS (SELECT 1 FROM teachers t WHERE t.username=exams.created_by AND t.deleted_at IS NULL))", (exam_id,)).fetchone()
    if not exam:
        conn.close()
        return json_response({"error": "Exam not found."}, status=404)
    existing = conn.execute(
        "SELECT * FROM results WHERE exam_id=? AND roll_no=?", (exam_id, roll_no)
    ).fetchone()
    if existing:
        conn.close()
        # A lost HTTP response may cause the same attempt to be sent again.
        # Only the same student's original key can recover that saved result.
        if submission_key and existing["submission_key"] == submission_key:
            return json_response(_student_result_summary(existing, exam))
        error = (
            "Your quiz is already submitted. Ask your teacher to return it before trying again."
            if exam["activity_type"] == "quiz"
            else "You have already attempted this exam."
        )
        return json_response({"error": error}, status=409)

    previous_returns = conn.execute(
        "SELECT snapshot FROM portal_submissionreturn WHERE exam_id=? AND roll_no=?",
        (exam_id, roll_no),
    ).fetchall()
    if submission_key and any(submission_key == json.loads(item["snapshot"])["submission_key"] for item in previous_returns):
        conn.close()
        return json_response({"error": "Your teacher returned this submission. Open the assessment again to continue your saved answers."}, status=409)

    department = student["department"]
    section = student["section"] or ""
    year_level = student["year_level"] or ""
    if not class_can_access(conn, exam_id, department, year_level, section):
        conn.close()
        return json_response({"error": "This exam is not available for your department, year level, and section."}, status=403)

    qs = conn.execute(
        "SELECT * FROM questions WHERE exam_id=? ORDER BY position", (exam_id,)
    ).fetchall()

    try:
        score, total, review = _grade_and_review(qs, answers, exam["activity_type"])
    except (ValueError, TypeError, OverflowError):
        conn.close()
        return json_response({"error": "Invalid answer value."}, status=400)
    percent = (score / total * 100) if total else 0
    result_id = "res_" + uuid.uuid4().hex[:10]
    submitted_at = time.strftime("%Y-%m-%dT%H:%M:%S")

    recorded = conn.execute("SELECT activity_log_json FROM portal_assessmentactivity WHERE exam_id=? AND student_id=? AND submission_key=?", (exam_id, student["id"], submission_key)).fetchone()
    activity_log = merge_activity_logs(json.loads(recorded["activity_log_json"]) if recorded else None, activity_log)

    conn.execute(
        """INSERT INTO results
           (id, exam_id, exam_title, name, roll_no, score, total, percent,
            answers_json, submitted_at, time_taken_sec, auto_submitted, submit_reason, department,
            teacher_username, section, submission_key, year_level, activity_log_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            result_id, exam_id, exam["title"], name, roll_no, score, total, percent,
            json.dumps(answers), submitted_at, time_taken_sec, int(auto_submitted), submit_reason, department,
            exam["created_by"] or "", section, submission_key, year_level,
            json.dumps(activity_log) if activity_log is not None else None,
        ),
    )
    saved = conn.execute("SELECT * FROM results WHERE id=?", (result_id,)).fetchone()
    conn.execute("UPDATE portal_assessmentactivity SET result_id=?,activity_log_json=? WHERE exam_id=? AND student_id=? AND submission_key=?", (result_id, json.dumps(activity_log), exam_id, student["id"], submission_key))
    conn.execute(
        "UPDATE portal_submissionreturn SET resubmitted_id=? WHERE exam_id=? AND roll_no=? AND resubmitted_id=''",
        (result_id, exam_id, roll_no),
    )
    conn.commit()
    conn.close()
    return json_response(_student_result_summary(saved, exam))


def get_results(request):
    exam_id = request.GET.get("examId")
    roll_no = request.GET.get("rollNo")
    department = request.GET.get("department")
    section = request.GET.get("section")
    year_level = request.GET.get("yearLevel")
    account = current_admin_account(request)
    student = current_student_account(request)
    if not account and not student:
        return json_response({"error": "Sign in required."}, status=401)
    if student:
        roll_no = student["rollNo"]
    conn = get_db()
    q = "SELECT r.*, e.subject AS exam_subject, e.activity_type AS exam_activity_type FROM results r LEFT JOIN exams e ON e.id=r.exam_id WHERE 1=1"
    params = []
    if account and account["role"] == "teacher":
        q += " AND r.teacher_username=?"
        params.append(account["username"])
    if exam_id:
        q += " AND r.exam_id=?"
        params.append(exam_id)
    if roll_no:
        q += " AND r.roll_no=?"
        params.append(roll_no)
    if department:
        q += " AND r.department=?"
        params.append(department)
    if section:
        q += " AND r.section=?"
        params.append(section)
    if year_level:
        q += " AND r.year_level=?"
        params.append(year_level)
    q += " ORDER BY r.score DESC, r.submitted_at ASC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    out = [
        {
            "id": r["id"],
            "examId": r["exam_id"],
            "examTitle": r["exam_title"],
            "activityType": r["exam_activity_type"] or "exam",
            "pointsPerQuestion": points_per_question(r["exam_activity_type"]),
            "pointsByType": question_point_values(r["exam_activity_type"]),
            "name": r["name"],
            "rollNo": r["roll_no"],
            "department": r["department"],
            "section": r["section"] or "",
            "yearLevel": r["year_level"] or "",
            "subject": r["exam_subject"] or "",
            "score": r["score"],
            "total": r["total"],
            "percent": r["percent"],
            "gradeStatus": _grade_status(r["percent"]),
            "timeTakenSec": r["time_taken_sec"],
            "autoSubmitted": bool(r["auto_submitted"]),
            "submitReason": r["submit_reason"] or "manual",
            "submittedAt": r["submitted_at"],
            "activitySummary": activity_summary(r["activity_log_json"]),
        }
        for r in rows
    ]
    return json_response(out)


def get_result_review(request, result_id):
    account = current_admin_account(request)
    student = current_student_account(request)
    if not account and not student:
        return json_response({"error": "Sign in required."}, status=401)
    conn = get_db()
    r = conn.execute(
        "SELECT r.*, e.subject AS exam_subject, e.activity_type AS exam_activity_type FROM results r LEFT JOIN exams e ON e.id=r.exam_id WHERE r.id=?",
        (result_id,),
    ).fetchone()
    if not r:
        conn.close()
        return json_response({"error": "Result not found."}, status=404)
    if student and r["roll_no"] != student["rollNo"]:
        conn.close()
        return json_response({"error": "Result not found."}, status=404)
    if account and account["role"] == "teacher" and r["teacher_username"] != account["username"]:
        conn.close()
        return json_response({"error": "You can only review results from your students."}, status=403)
    qs = conn.execute(
        "SELECT * FROM questions WHERE exam_id=? ORDER BY position", (r["exam_id"],)
    ).fetchall()
    conn.close()
    answers = json.loads(r["answers_json"])
    _, _, review = _grade_and_review(qs, answers, r["exam_activity_type"])
    return json_response(
        {
            "id": r["id"],
            "examId": r["exam_id"],
            "examTitle": r["exam_title"],
            "activityType": r["exam_activity_type"] or "exam",
            "pointsPerQuestion": points_per_question(r["exam_activity_type"]),
            "pointsByType": question_point_values(r["exam_activity_type"]),
            "name": r["name"],
            "rollNo": r["roll_no"],
            "department": r["department"],
            "section": r["section"] or "",
            "yearLevel": r["year_level"] or "",
            "subject": r["exam_subject"] or "",
            "score": r["score"],
            "total": r["total"],
            "percent": r["percent"],
            "gradeStatus": _grade_status(r["percent"]),
            "timeTakenSec": r["time_taken_sec"],
            "autoSubmitted": bool(r["auto_submitted"]),
            "submitReason": r["submit_reason"] or "manual",
            "review": review,
            "activitySummary": activity_summary(r["activity_log_json"]),
            "activityLog": json.loads(r["activity_log_json"]) if r["activity_log_json"] else None,
            "submittedAt": r["submitted_at"],
        }
    )


def reopen_result(request, result_id):
    account = current_admin_account(request)
    if not account:
        return json_response({"error": "Your staff session has expired. Sign in again to return this submission."}, status=401)

    from .submissions import return_submission
    data = read_json(request)
    try:
        result = return_submission(result_id, account["username"], student_id=data.get("studentId"), teacher_only=account["role"] == "teacher")
    except PermissionError as error:
        return json_response({"error": str(error)}, status=403)
    except ValueError as error:
        return json_response({"error": str(error), "code": "student_id_verification_failed"}, status=400)
    if not result:
        return json_response({"error": "Result not found."}, status=404)
    return json_response({"ok": True, "examId": result["exam_id"], "rollNo": result["roll_no"]})
