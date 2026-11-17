"""A shared sign-in entry point; roles come only from verified account records."""

from functools import wraps

from django.conf import settings
from django.contrib.auth import authenticate, login as django_login
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.middleware.csrf import rotate_token

from .http import json_response, read_json
from .models import Student, Teacher
from .security import check_password_hash


ROLE_PERMISSIONS = {
    "student": ["assessments.take", "materials.read", "activities.submit", "results.own"],
    "teacher": ["assessments.manage", "materials.manage", "submissions.review", "students.manage", "results.review"],
    "admin": ["teachers.manage", "students.manage", "school.manage", "results.review"],
}
ROLE_DASHBOARDS = {"student": "/student", "teacher": "/teacher", "admin": "/admin/"}


def student_profile(student):
    return {
        "role": "student", "studentId": student.pk, "name": student.name,
        "rollNo": student.roll_no, "department": student.department,
        "section": student.section or "", "yearLevel": student.year_level or "",
    }


def teacher_profile(teacher):
    from .db import get_db
    conn = get_db()
    try:
        departments = [row["department"] for row in conn.execute(
            "SELECT department FROM teacher_departments WHERE teacher_username=? ORDER BY department", (teacher.username,),
        ).fetchall()]
    finally:
        conn.close()
    return {"role": "teacher", "teacherId": teacher.pk, "name": teacher.name, "username": teacher.username, "department": teacher.department, "departments": departments}


def identity_payload(account):
    role = account["role"]
    return {"account": account, "role": role, "permissions": ROLE_PERMISSIONS[role], "redirect": ROLE_DASHBOARDS[role]}


def current_identity(request):
    from .views import current_admin_account, current_student_account
    account = current_admin_account(request) or current_student_account(request)
    return account if account else None


def require_page_role(role):
    """Protect the HTML entry as well as the APIs it uses."""
    def decorate(view):
        @wraps(view)
        def guarded(request, *args, **kwargs):
            account = current_identity(request)
            if not account:
                return HttpResponseRedirect("/login")
            if account["role"] != role:
                return HttpResponseRedirect(ROLE_DASHBOARDS[account["role"]])
            return view(request, *args, **kwargs)
        return guarded
    return decorate


def session_account(request):
    account = current_identity(request)
    if not account:
        return json_response({"error": "Sign in required."}, status=401)
    return json_response(identity_payload(account))


def login(request):
    data = read_json(request)
    identifier, password = data.get("username", ""), data.get("password", "")
    if not isinstance(identifier, str) or not isinstance(password, str) or not identifier.strip() or not password:
        return json_response({"error": "Enter your username or student ID and password."}, status=400)
    identifier = identifier.strip()
    candidates = []
    native_user = authenticate(request, username=identifier, password=password)
    if native_user and native_user.is_active and native_user.is_staff and native_user.is_superuser:
        candidates.append(({"role": "admin", "name": native_user.get_full_name() or native_user.username, "username": native_user.username, "department": "ALL"}, native_user))
    for teacher in Teacher.objects.filter(username=identifier, deleted_at__isnull=True):
        if check_password_hash(teacher.password_hash, password):
            candidates.append((teacher_profile(teacher), None))
    for student in Student.objects.filter(Q(roll_no=identifier) | Q(username=identifier), deleted_at__isnull=True):
        if student.password_hash and check_password_hash(student.password_hash, password):
            candidates.append((student_profile(student), None))
    if not candidates:
        return json_response({"error": "Incorrect username, student ID, or password."}, status=401)
    if len(candidates) != 1:
        return json_response({"error": "These sign-in details match more than one account. Ask the school administrator to assign a unique teacher username or student ID.", "code": "ambiguous_credentials"}, status=409)
    account, native_user = candidates[0]
    role = account["role"]
    cookie = settings.SESSION_COOKIE_NAME + (f"_{role}" if role in ("student", "teacher") else "")
    # Neither a submitted role nor X-Portal-Role can decide the resulting role.
    request.portal_session_cookie = cookie
    request.session = type(request.session)(request.COOKIES.get(cookie))
    request.session.flush()
    request.portal_replace_other_sessions = True
    if native_user:
        django_login(request, native_user)
    else:
        rotate_token(request)
        request.session["account"] = account
    return json_response({"ok": True, **identity_payload(account)})
