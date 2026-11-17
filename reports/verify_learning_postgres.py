"""Run a private-file workflow in a disposable PostgreSQL schema.

Uses the normal PostgreSQL environment variables. No public classroom records
are read or changed; all fixture tables and files are removed on completion.
"""

from concurrent.futures import ThreadPoolExecutor
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
schema = "learning_verify_" + uuid.uuid4().hex
os.environ["DJANGO_SETTINGS_MODULE"] = "exam_portal.settings"
os.environ["PGOPTIONS"] = "-c search_path=" + schema

import django
django.setup()

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection, connections
from django.test import Client, override_settings
from portal.db import get_db
from portal.models import ActivityFileSubmission, ActivitySubmissionNotification, LectureMaterial, Teacher
from portal.security import generate_password_hash


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def pdf(name):
    return SimpleUploadedFile(name, b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF", "application/pdf")


created = False
try:
    with connection.cursor() as cursor:
        cursor.execute(f'CREATE SCHEMA "{schema}"')
        created = True
        cursor.execute("SELECT current_schema()")
        check(cursor.fetchone()[0] == schema, "Verification schema was not selected")
    with tempfile.TemporaryDirectory(prefix="learning-postgres-") as upload_dir, override_settings(
        MEDIA_ROOT=upload_dir, ALLOWED_HOSTS=["testserver"], PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    ):
        call_command("migrate", interactive=False, stdout=StringIO(), verbosity=0)
        Teacher.objects.create(id="teacher-test", name="Verification Teacher", username="verify_teacher", department="BSIT", password_hash=generate_password_hash("verify-pass"))
        conn = get_db()
        conn.execute("INSERT INTO teacher_departments (teacher_username,department) VALUES (?,?)", ("verify_teacher", "BSIT"))
        conn.commit()
        conn.close()
        teacher = Client(headers={"X-Portal-Role": "teacher"})
        response = teacher.post("/api/auth/login", {"username": "verify_teacher", "password": "verify-pass"}, content_type="application/json")
        check(response.status_code == 200 and response.json()["role"] == "teacher" and response.json()["redirect"] == "/teacher", "Shared teacher login failed")
        check(teacher.get("/teacher").status_code == 200, "Verified teacher dashboard failed")
        check(teacher.get("/api/teachers").status_code == 403, "Teacher received superadmin permissions")
        student = Client(headers={"X-Portal-Role": "student"})
        profile = {"firstName": "Test", "lastName": "Student", "rollNo": "VERIFY-001", "department": "BSIT", "yearLevel": "1st Year", "section": "A", "password": "verify-pass"}
        check(student.post("/api/students/signup", profile, content_type="application/json").status_code == 200, "Student signup failed")
        response = student.post("/api/auth/login", {"username": "VERIFY-001", "password": "verify-pass", "role": "teacher"}, content_type="application/json")
        check(response.status_code == 200 and response.json()["role"] == "student" and response.json()["redirect"] == "/student", "Shared student login or server role enforcement failed")
        check(student.get("/student").status_code == 200 and student.get("/teacher").status_code == 302, "Student dashboard role boundary failed")
        check(student.post("/api/learning/materials", {}).status_code == 403, "Student received teacher upload permissions")
        response = teacher.post("/api/learning/materials", {
            "title": "Verification activity", "subject": "Programming", "requiresSubmission": "true", "file": pdf("lecture.pdf"),
            "targetClasses": json.dumps([{"department": "BSIT", "yearLevel": "1st Year", "section": "A"}]),
        })
        check(response.status_code == 201, "Material creation failed")
        material_id = response.json()["id"]
        material = student.get("/api/learning/materials").json()[0]
        response = student.get(material["openUrl"])
        check(response.status_code == 200 and b"".join(response.streaming_content).startswith(b"%PDF-"), "PDF open failed")
        path = f"/api/learning/materials/{material_id}/submissions"

        def submit(index):
            client = Client(headers={"X-Portal-Role": "student"})
            client.cookies.update(student.cookies)
            try:
                return client.post(path, {"file": pdf(f"activity-{index}.pdf")}).status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(pool.map(submit, range(4)))
        check(statuses == [200] * 4, "Simultaneous replacements failed")
        check(ActivityFileSubmission.objects.count() == 1, "Duplicate activity submissions were stored")
        alerts = teacher.get("/api/notifications").json()
        check(alerts["unreadCount"] == 4 and len(alerts["items"]) == 4, "Submission notifications were not committed with uploads")
        check(student.get("/api/notifications").status_code == 403, "Student received teacher notifications")
        check(teacher.post(f'/api/notifications/{alerts["items"][0]["id"]}/read').json()["unreadCount"] == 3, "Read notification count failed")
        check(teacher.post("/api/notifications/read-all").json()["unreadCount"] == 0, "Mark all read failed")
        check(len([item for item in Path(upload_dir).rglob("*") if item.is_file()]) == 2, "Replacement left old files behind")
        submissions = teacher.get(path).json()
        check(submissions[0]["rollNo"] == "VERIFY-001", "Teacher review did not include student identity")
        response = teacher.get(submissions[0]["downloadUrl"])
        check(response.status_code == 200, "Teacher file download failed")
        response.close()
        check(teacher.delete(f"/api/learning/materials/{material_id}").status_code == 200, "Delete failed")
        check(not LectureMaterial.objects.exists() and not ActivityFileSubmission.objects.exists(), "Delete left database records")
        check(not ActivitySubmissionNotification.objects.exists(), "Delete left notifications")
        check(not any(item.is_file() for item in Path(upload_dir).rglob("*")), "Delete left private files")
        print("PASS: PostgreSQL login, RBAC, migrations, uploads, concurrent replacements, unread notifications, mark read/all, review/download, and cleanup")
finally:
    if created:
        # The identifier is generated above, never supplied by a user or config.
        check(schema.startswith("learning_verify_") and len(schema) == 48, "Unexpected cleanup schema")
        with connection.cursor() as cursor:
            cursor.execute(f'DROP SCHEMA "{schema}" CASCADE')
    connections.close_all()
