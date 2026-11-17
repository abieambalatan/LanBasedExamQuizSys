import os
import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import shutil
import unittest
import uuid
from io import StringIO
from contextlib import closing, nullcontext
from urllib.parse import urlencode
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from random import Random
from threading import Barrier
from unittest.mock import patch

os.environ["DJANGO_SETTINGS_MODULE"] = "exam_portal.test_settings"
import django
django.setup()

from django.http import HttpResponse
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connections
from django.core.management import call_command, CommandError
from portal.models import Teacher, Student, Result, Exam, SchoolOption
from portal.admin import SchoolOptionAdmin
from django.contrib import admin as django_admin
from django.test import Client, RequestFactory, override_settings
from portal import db as portal_db
from portal import views as portal
from portal.middleware import PortalMiddleware
from portal.management.commands.migrate_sqlite_data import (
    adapt_row,
    ordered_source_tables,
    quote_identifier,
    target_has_seeded_school_options,
    table_rows_match,
)


class APIClient(Client):
    def post(self, path, json=None, **extra):
        return super().post(path, data=json, content_type="application/json", **extra)

    def put(self, path, json=None, **extra):
        return super().put(path, data=json, content_type="application/json", **extra)

    def delete(self, path, json=None, **extra):
        return super().delete(path, data={} if json is None else json, content_type="application/json", **extra)


class ExamPortalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema_dir = tempfile.TemporaryDirectory()
        cls.schema_db = os.path.join(cls.schema_dir.name, "schema.db")
        result = subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"], cwd=Path(__file__).parent, env={**os.environ, "EXAM_PORTAL_DB_PATH": cls.schema_db}, capture_output=True, text=True, timeout=30)
        if result.returncode:
            cls.schema_dir.cleanup()
            raise RuntimeError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.schema_dir.cleanup()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_admin_password = portal.ADMIN_PASSWORD

        self.settings_override = override_settings(
            SECRET_KEY="test-session-signing-key",
            ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"],
            PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
            MEDIA_ROOT=Path(self.temp_dir.name) / "uploads",
        )
        self.settings_override.enable()
        connections.close_all()
        test_db = os.path.join(self.temp_dir.name, "test.db")
        shutil.copyfile(self.schema_db, test_db)
        self.database_override = patch.dict(settings.DATABASES["default"], {"NAME": test_db})
        self.database_override.start()
        portal.ADMIN_PASSWORD = "configured-test-password"
        portal_db.init_db()
        get_user_model().objects.create_superuser(username="administrator", password="configured-test-password")
        self.client = APIClient()

    def tearDown(self):
        connections.close_all()
        self.database_override.stop()
        portal.ADMIN_PASSWORD = self.original_admin_password
        self.settings_override.disable()
        self.temp_dir.cleanup()

    @staticmethod
    def teacher_payload():
        return {
            "name": "Teacher One",
            "username": "teacher1",
            "departments": ["BSIT"],
            "password": "teacher-pass",
        }

    def create_teacher(self, username="teacher1", departments=None, password="teacher-pass"):
        departments = departments or ["BSIT"]
        name = "Teacher One"
        department = departments[0]
        with closing(portal.get_db()) as conn:
            conn.execute(
                """INSERT INTO teachers (id, name, username, department, password_hash, created_at)
                   VALUES (?,?,?,?,?,?)""",
                (
                    "tch_test_" + uuid.uuid4().hex,
                    name,
                    username,
                    department,
                    portal.generate_password_hash(password),
                    "2026-01-01T00:00:00",
                ),
            )
            conn.executemany(
                "INSERT INTO teacher_departments (teacher_username, department) VALUES (?,?)",
                [(username, item) for item in departments],
            )
            conn.commit()
        return True

    @staticmethod
    def student_payload(roll_no="ID-001"):
        return {
            "firstName": "Test",
            "lastName": "Student",
            "middleInitial": "A",
            "rollNo": roll_no,
            "department": "BSIT",
            "section": "A",
            "yearLevel": "1st Year",
            "password": "student-pass",
        }

    @staticmethod
    def exam_payload(title="Unit Test", activity_type="exam"):
        return {
            "title": title,
            "activityType": activity_type,
            "duration": 10,
            "departments": ["BSIT"],
            "yearLevel": "1st Year",
            "subject": "Programming",
            "sectionScope": "ALL",
            "questions": [
                {
                    "part": 1,
                    "type": "multiple_choice",
                    "text": "2 + 2?",
                    "options": ["3", "4", "5", "6"],
                    "correct": 1,
                },
                {
                    "part": 2,
                    "type": "identification",
                    "text": "Capital of the Philippines?",
                    "answerText": "Manila",
                    "alternatives": ["City of Manila"],
                },
            ],
        }

    def test_student_signup_saves_separate_names_without_teacher_enrollment(self):
        payload = {**self.student_payload(), "firstName": " Juan Miguel ", "lastName": " Dela Cruz ", "middleInitial": "p.", "teacherUsernames": ["nonexistent-teacher"]}
        response = self.client.post("/api/students/signup", json=payload)
        self.assertEqual(response.status_code, 200, response.content)
        student = Student.objects.get(roll_no="ID-001")
        self.assertEqual((student.first_name, student.last_name, student.middle_initial), ("Juan Miguel", "Dela Cruz", "P"))
        self.assertEqual(student.name, "Dela Cruz, Juan Miguel P.")
        self.assertEqual(student.teacher_username, "")
        with closing(portal.get_db()) as conn:
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='student_teachers'").fetchone())
        login = self.client.post("/api/students/login", json={"idNumber": "ID-001", "password": "student-pass"})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.json()["name"], "Dela Cruz, Juan Miguel P.")
        self.assertNotIn("teacherUsernames", login.json())
        self.assertEqual(self.client.get("/api/exams?studentView=1").json(), [])

    def test_student_name_validation_and_optional_middle_initial(self):
        for changes in ({"firstName": " "}, {"lastName": ""}, {"firstName": "X" * 256}, {"middleInitial": "AB"}, {"middleInitial": "1"}, {"middleInitial": "."}):
            with self.subTest(changes=changes):
                response = self.client.post("/api/students/signup", json={**self.student_payload(), **changes})
                self.assertEqual(response.status_code, 400, response.content)
        response = self.client.post("/api/students/signup", json={**self.student_payload(), "middleInitial": ""})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Student.objects.get(roll_no="ID-001").name, "Student, Test")
        self.assertEqual(self.client.post("/api/students/signup", json=self.student_payload()).status_code, 409)

    def test_superadmin_manages_dynamic_school_options(self):
        self.client.force_login(get_user_model().objects.get(username="administrator"))
        listing = self.client.get("/admin/portal/schooloption/")
        self.assertEqual(listing.status_code, 200)
        self.assertContainsText(listing, "Add school option")
        def admin_post(path, data):
            return self.client.generic(
                "POST",
                path,
                urlencode(data),
                content_type="application/x-www-form-urlencoded",
            )

        response = admin_post("/admin/portal/schooloption/add/", {
            "value": "BSAIS",
            "section_count": "3",
            "position": "20",
            "_save": "Save",
        })
        self.assertEqual(response.status_code, 302, response.content[:1000])
        department_option = SchoolOption.objects.get(category=SchoolOption.DEPARTMENT, value="BSAIS")
        self.assertEqual(department_option.section_count, 3)

        for path in ("/", "/index.html"):
            page = self.client.get(path)
            self.assertEqual(page.status_code, 200)
            self.assertContainsText(page, '"BSAIS"')
            self.assertContainsText(page, '"sections_by_department"')
            self.assertIn('"BSAIS": ["A", "B", "C"]', page.content.decode())
            self.assertNotIn('"5th Year"', page.content.decode())

        payload = {
            **self.student_payload("CUSTOM-001"),
            "department": "BSAIS",
            "yearLevel": "4th Year",
            "section": "C",
        }
        signup = self.client.post("/api/students/signup", json=payload)
        self.assertEqual(signup.status_code, 200, signup.content)
        student = Student.objects.get(roll_no="CUSTOM-001")
        self.assertEqual(self.client.post("/api/students/signup", json={
            **self.student_payload("CUSTOM-INVALID-SECTION"),
            "department": "BSAIS",
            "section": "D",
        }).status_code, 400)
        self.assertEqual(self.client.post("/api/students/signup", json={
            **self.student_payload("CUSTOM-INVALID-YEAR"),
            "department": "BSAIS",
            "yearLevel": "5th Year",
        }).status_code, 400)

        teacher = APIClient()
        self.create_teacher("custom-option-teacher", ["BSAIS"], "teacher-pass")
        login = teacher.post("/api/admin/login", json={
            "username": "custom-option-teacher",
            "password": "teacher-pass",
        })
        self.assertEqual(login.status_code, 200, login.content)
        exam_data = {
            **self.exam_payload("Custom options assessment"),
            "targetClasses": [{"department": "BSAIS", "yearLevel": "4th Year", "section": "C"}],
        }
        exam = teacher.post("/api/exams", json=exam_data)
        self.assertEqual(exam.status_code, 200, exam.content)
        invalid_exam = teacher.post("/api/exams", json={
            **self.exam_payload("Invalid section assessment"),
            "targetClasses": [{"department": "BSAIS", "yearLevel": "4th Year", "section": "D"}],
        })
        self.assertEqual(invalid_exam.status_code, 400, invalid_exam.content)

        option_admin = SchoolOptionAdmin(SchoolOption, django_admin.site)
        request = RequestFactory().get("/admin/portal/schooloption/")
        self.assertFalse(option_admin.has_delete_permission(
            request, SchoolOption.objects.get(category=SchoolOption.DEPARTMENT, value="BSAIS")
        ))

        response = admin_post(f"/admin/portal/schooloption/{department_option.pk}/change/", {
            "value": "BSAIX",
            "section_count": "3",
            "position": str(department_option.position),
            "_save": "Save",
        })
        self.assertEqual(response.status_code, 302, response.content)

        student.refresh_from_db()
        self.assertEqual((student.department, student.year_level, student.section), ("BSAIX", "4th Year", "C"))
        saved_exam = next(
            row for row in teacher.get("/api/exams").json()
            if row["title"] == "Custom options assessment"
        )
        self.assertEqual(
            saved_exam["targetClasses"],
            [{"department": "BSAIX", "yearLevel": "4th Year", "section": "C"}],
        )
        page_content = self.client.get("/").content.decode()
        self.assertIn('"BSAIX"', page_content)
        self.assertNotIn('"BSAIS"', page_content)

        renamed_option = SchoolOption.objects.get(category=SchoolOption.DEPARTMENT, value="BSAIX")
        blocked_reduction = admin_post(f"/admin/portal/schooloption/{renamed_option.pk}/change/", {
            "value": "BSAIX",
            "section_count": "2",
            "position": str(renamed_option.position),
            "_save": "Save",
        })
        self.assertEqual(blocked_reduction.status_code, 200)
        self.assertContainsText(blocked_reduction, "existing records use C")
        renamed_option.refresh_from_db()
        self.assertEqual(renamed_option.section_count, 3)

        unused_option = SchoolOption.objects.create(
            category=SchoolOption.DEPARTMENT,
            value="UNUSED",
            position=30,
            section_count=2,
        )
        self.assertTrue(option_admin.has_delete_permission(request, unused_option))
        delete = admin_post(f"/admin/portal/schooloption/{unused_option.pk}/delete/", {"post": "yes"})
        self.assertEqual(delete.status_code, 302, delete.content[:1000])
        self.assertFalse(SchoolOption.objects.filter(pk=unused_option.pk).exists())

    def test_sections_are_configured_and_validated_for_each_department_year(self):
        client = self.native_admin_client()
        department = SchoolOption.objects.get(category=SchoolOption.DEPARTMENT, value="BSIT")
        def configure(first, second):
            return client.post(f"/admin/portal/schooloption/{department.pk}/change/", {
                "value": "BSIT", "position": department.position, "section_count": "6",
                "year_1_sections": str(first), "year_2_sections": str(second), "_save": "Save",
            })
        self.assertEqual(configure(3, 4).status_code, 302)
        department.refresh_from_db()
        self.assertEqual(department.year_section_counts, {"1st Year": 3, "2nd Year": 4})
        from portal.school_options import sections_for_department, school_options_payload
        self.assertEqual(sections_for_department("BSIT", "1st Year"), ["A", "B", "C"])
        self.assertEqual(sections_for_department("BSIT", "2nd Year"), ["A", "B", "C", "D"])
        self.assertEqual(school_options_payload()["sections_by_department_and_year"]["BSIT"]["2nd Year"], ["A", "B", "C", "D"])
        first_year = {**self.student_payload("FIRST-D"), "yearLevel": "1st Year", "section": "D"}
        self.assertEqual(self.client.post("/api/students/signup", json=first_year).status_code, 400)
        self.assertEqual(self.client.post("/api/students/signup", json={**first_year, "rollNo": "SECOND-D", "yearLevel": "2nd Year"}).status_code, 200)
        self.create_teacher()
        teacher = APIClient()
        teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"})
        invalid = {"department": "BSIT", "yearLevel": "1st Year", "section": "D"}
        self.assertEqual(teacher.post("/api/exams", json={**self.exam_payload(), "targetClasses": [invalid]}).status_code, 400)
        valid = {**invalid, "yearLevel": "2nd Year"}
        created = teacher.post("/api/exams", json={**self.exam_payload(), "targetClasses": [valid]})
        self.assertEqual(created.status_code, 200, created.content)
        all_sections = teacher.post("/api/exams", json=self.exam_payload("First-year activity"))
        self.assertEqual(all_sections.status_code, 200)
        activity = teacher.get(f"/api/exams/{all_sections.json()['id']}").json()
        self.assertEqual([target["section"] for target in activity["targetClasses"]], ["A", "B", "C"])
        # Another year's section D must not block reducing the first year's unused D.
        self.assertEqual(configure(3, 4).status_code, 302)
        blocked = configure(3, 3)
        self.assertEqual(blocked.status_code, 200)
        self.assertContainsText(blocked, "2nd Year: existing records use D")
        department.refresh_from_db()
        self.assertEqual(department.year_section_counts["2nd Year"], 4)

    def test_published_exam_access_uses_program_year_and_section_for_all_teachers(self):
        teachers = []
        for username in ("teacher1", "teacher2"):
            teacher = APIClient()
            self.create_teacher(username, ["BSIT", "BEED"])
            self.assertEqual(teacher.post("/api/admin/login", json={"username": username, "password": "teacher-pass"}).status_code, 200)
            teachers.append(teacher)
        self.assertEqual(self.client.post("/api/students/signup", json=self.student_payload()).status_code, 200)
        self.assertEqual(self.client.post("/api/students/login", json={"idNumber": "ID-001", "password": "student-pass"}).status_code, 200)
        # The old enrollment column and signed-in sessions must no longer restrict access.
        student = Student.objects.get(roll_no="ID-001")
        with closing(portal.get_db()) as conn:
            conn.execute("UPDATE students SET teacher_username=? WHERE id=?", ("teacher1", student.pk))
            conn.commit()
        session = self.client.session
        account = session["account"]
        account["teacherUsernames"] = ["teacher1"]
        session["account"] = account
        session.save()
        self.client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key

        available, blocked = [], []
        cases = [
            (teachers[0], {}, True),
            (teachers[1], {"sectionScope": "A"}, True),
            (teachers[1], {"departments": ["BSIT", "BEED"]}, True),
            (teachers[1], {"departments": ["BEED"]}, False),
            (teachers[1], {"yearLevel": "2nd Year"}, False),
            (teachers[1], {"sectionScope": "B"}, False),
        ]
        for index, (teacher, changes, allowed) in enumerate(cases):
            response = teacher.post("/api/exams", json={**self.exam_payload(f"Scope {index}"), **changes})
            self.assertEqual(response.status_code, 200, response.content)
            exam_id = response.json()["id"]
            (available if allowed else blocked).append(exam_id)
        for query in ("studentView=1", "studentView=1&department=BEED&yearLevel=2nd%20Year&section=B&teacherUsernames=teacher2"):
            listed = self.client.get(f"/api/exams?{query}")
            self.assertEqual(listed.status_code, 200)
            self.assertCountEqual([exam["id"] for exam in listed.json()], available)
        for exam_id in available + blocked:
            allowed = exam_id in available
            with self.subTest(exam_id=exam_id, allowed=allowed):
                take = self.client.get(f"/api/exams/{exam_id}/take?department=BEED&section=B&yearLevel=2nd%20Year")
                self.assertEqual(take.status_code, 200 if allowed else 403, take.content)
                submit = self.client.post("/api/results", json={"examId": exam_id, "answers": {}, "department": "BEED", "section": "B", "yearLevel": "2nd Year"})
                self.assertEqual(submit.status_code, 200 if allowed else 403, submit.content)

    def test_target_classes_match_complete_combinations_and_keep_submission_year(self):
        teacher = APIClient()
        self.create_teacher(departments=["BSIT", "BSCRIM", "BSHM"])
        teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"})
        targets = [
            {"department": "BSIT", "yearLevel": "1st Year", "section": "A"},
            {"department": "BSIT", "yearLevel": "2nd Year", "section": "B"},
            {"department": "BSCRIM", "yearLevel": "3rd Year", "section": "C"},
        ]
        payload = {**self.exam_payload(), "targetClasses": targets}
        created = teacher.post("/api/exams", json=payload)
        self.assertEqual(created.status_code, 200, created.content)
        exam_id = created.json()["id"]
        self.assertCountEqual(teacher.get(f"/api/exams/{exam_id}").json()["targetClasses"], targets)
        classes = targets + [
            {"department": "BSIT", "yearLevel": "1st Year", "section": "B"},
            {"department": "BSIT", "yearLevel": "3rd Year", "section": "C"},
            {"department": "BSCRIM", "yearLevel": "1st Year", "section": "A"},
        ]
        students = []
        for index, target in enumerate(classes):
            client = APIClient()
            student_id = f"CLASS-{index}"
            self.assertEqual(client.post("/api/students/signup", json={**self.student_payload(student_id), **target}).status_code, 200)
            client.post("/api/students/login", json={"idNumber": student_id, "password": "student-pass"})
            allowed = index < len(targets)
            listed = client.get("/api/exams?studentView=1&department=BSIT&yearLevel=1st%20Year&section=A").json()
            self.assertEqual([row["id"] for row in listed], [exam_id] if allowed else [])
            take = client.get(f"/api/exams/{exam_id}/take?department=BSIT&yearLevel=1st%20Year&section=A")
            self.assertEqual(take.status_code, 200 if allowed else 403)
            if allowed:
                self.assertEqual(take.json()["yearLevel"], target["yearLevel"])
                self.assertEqual(take.json()["sectionScope"], target["section"])
                students.append(client)
            else:
                self.assertEqual(client.post("/api/results", json={"examId": exam_id, "answers": {}, **targets[0]}).status_code, 403)

        barrier = Barrier(len(students))
        def submit(item):
            index, client = item
            barrier.wait(timeout=10)
            response = client.post("/api/results", json={"examId": exam_id, "answers": {}, "submissionId": f"attempt-{index}", "yearLevel": "4th Year"})
            return response.status_code, response.json()
        with ThreadPoolExecutor(max_workers=len(students)) as pool:
            submitted = list(pool.map(submit, enumerate(students)))
        self.assertEqual([status for status, _ in submitted], [200] * len(students))
        self.assertEqual([row["yearLevel"] for _, row in submitted], [row["yearLevel"] for row in targets])
        self.assertEqual(len({row["id"] for _, row in submitted}), len(targets))
        for index, client in enumerate(students):
            self.assertEqual(client.post("/api/results", json={"examId": exam_id, "answers": {}}).status_code, 409)
            self.assertEqual(client.get(f"/api/exams/{exam_id}/take").status_code, 403)
            receipt = client.post("/api/results", json={"examId": exam_id, "answers": {}, "submissionId": f"attempt-{index}"})
            self.assertEqual(receipt.json()["id"], submitted[index][1]["id"])

        filtered = teacher.get(f"/api/results?examId={exam_id}&department=BSIT&yearLevel=2nd%20Year&section=B").json()
        self.assertEqual([row["rollNo"] for row in filtered], ["CLASS-1"])
        # Retargeting and promotion must not relabel already saved class results.
        moved = [{"department": "BSHM", "yearLevel": "4th Year", "section": "F"}]
        self.assertEqual(teacher.put(f"/api/exams/{exam_id}", json={**payload, "targetClasses": moved}).status_code, 200)
        Student.objects.filter(roll_no="CLASS-1").update(year_level="4th Year", section="F")
        history = teacher.get(f"/api/results?examId={exam_id}").json()
        self.assertEqual({row["rollNo"]: row["yearLevel"] for row in history}, {f"CLASS-{i}": row["yearLevel"] for i, row in enumerate(targets)})
        review = teacher.get(f"/api/results/{submitted[1][1]['id']}/review").json()
        self.assertEqual((review["yearLevel"], review["section"]), ("2nd Year", "B"))
        self.assertEqual(students[0].get("/api/exams?studentView=1").json(), [])
        self.assertEqual(teacher.delete(f"/api/exams/{exam_id}").status_code, 200)
        with closing(portal.get_db()) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) c FROM exam_target_classes WHERE exam_id=?", (exam_id,)).fetchone()["c"], 0)

    def test_target_class_validation_and_all_department_exam_access(self):
        teacher = APIClient()
        self.create_teacher()
        teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"})
        valid = {"department": "BSIT", "yearLevel": "2nd Year", "section": "A"}
        for invalid in ([], None, {}, [None], [valid, {}], [{**valid, "yearLevel": "5th Year"}], [{**valid, "section": "ALL"}], [{**valid, "department": "UNKNOWN"}], [valid] * 121):
            response = teacher.post("/api/exams", json={**self.exam_payload(), "targetClasses": invalid})
            self.assertEqual(response.status_code, 400, response.content)
        other_department_target = {**valid, "department": "BSN"}
        allowed = teacher.post("/api/exams", json={
            **self.exam_payload("Other department assessment"),
            "targetClasses": [other_department_target],
        })
        self.assertEqual(allowed.status_code, 200, allowed.content)
        other_exam_id = allowed.json()["id"]
        self.assertEqual(
            teacher.get(f"/api/exams/{other_exam_id}").json()["targetClasses"],
            [other_department_target],
        )
        retargeted = teacher.put(f"/api/exams/{other_exam_id}", json={
            **self.exam_payload("Other department assessment"),
            "targetClasses": [{**valid, "department": "BEED"}],
        })
        self.assertEqual(retargeted.status_code, 200, retargeted.content)
        self.assertEqual(
            teacher.get(f"/api/exams/{other_exam_id}").json()["targetClasses"],
            [{**valid, "department": "BEED"}],
        )
        created = teacher.post("/api/exams", json={**self.exam_payload(), "targetClasses": [valid, valid]})
        self.assertEqual(created.status_code, 200)
        exam_id = created.json()["id"]
        self.assertEqual(teacher.get(f"/api/exams/{exam_id}").json()["targetClasses"], [valid])
        retargeted_all_departments = teacher.put(
            f"/api/exams/{exam_id}",
            json={**self.exam_payload(), "targetClasses": [valid, {**valid, "department": "BSN"}]},
        )
        self.assertEqual(retargeted_all_departments.status_code, 200, retargeted_all_departments.content)
        self.assertCountEqual(
            teacher.get(f"/api/exams/{exam_id}").json()["targetClasses"],
            [valid, {**valid, "department": "BSN"}],
        )

    def test_target_class_migration_preserves_legacy_access_and_results(self):
        clients, payload = self.submission_fixture()
        result = clients[0].post("/api/results", json=payload).json()
        filename = os.path.join(self.temp_dir.name, "test.db")
        connections.close_all()
        with closing(sqlite3.connect(filename)) as conn:
            original = conn.execute("SELECT id, exam_id, name, roll_no, score, answers_json FROM results").fetchall()
            conn.execute("DROP TABLE exam_target_classes")
            conn.execute("DROP INDEX idx_results_class")
            conn.execute("ALTER TABLE results DROP COLUMN year_level")
            conn.execute("DELETE FROM django_migrations WHERE app='portal' AND name>='0004_exam_target_classes'")
            conn.commit()
        migrated = subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"], cwd=Path(__file__).parent, env={**os.environ, "EXAM_PORTAL_DB_PATH": filename}, capture_output=True, text=True, timeout=30)
        self.assertEqual(migrated.returncode, 0, migrated.stderr)
        with closing(sqlite3.connect(filename)) as conn:
            self.assertEqual(conn.execute("SELECT id, exam_id, name, roll_no, score, answers_json FROM results").fetchall(), original)
            self.assertEqual(conn.execute("SELECT year_level FROM results WHERE id=?", (result["id"],)).fetchone()[0], "1st Year")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM exam_target_classes").fetchone()[0], 0)
            self.assertEqual(
                conn.execute(
                    "SELECT DISTINCT category FROM portal_schooloption"
                ).fetchall(),
                [("department",)],
            )
            self.assertEqual(
                conn.execute(
                    "SELECT MIN(section_count), MAX(section_count) FROM portal_schooloption"
                ).fetchone(),
                (6, 6),
            )
        self.assertEqual([row["id"] for row in clients[0].get("/api/exams?studentView=1").json()], [payload["examId"]])
        # A student in another section retains access to the legacy ALL-sections exam.
        self.client.post("/api/students/signup", json={**self.student_payload("LEGACY-F"), "section": "F"})
        self.client.post("/api/students/login", json={"idNumber": "LEGACY-F", "password": "student-pass"})
        self.assertEqual(self.client.get(f"/api/exams/{payload['examId']}/take").status_code, 200)

    def test_student_name_migration_preserves_existing_accounts(self):
        self.assertEqual(self.client.post("/api/students/signup", json=self.student_payload()).status_code, 200)
        filename = os.path.join(self.temp_dir.name, "test.db")
        connections.close_all()
        with closing(sqlite3.connect(filename)) as conn:
            original = conn.execute("SELECT id, name, roll_no, password_hash FROM students").fetchall()
            for column in ("first_name", "last_name", "middle_initial"):
                conn.execute(f"ALTER TABLE students DROP COLUMN {column}")
            conn.execute("DELETE FROM django_migrations WHERE app='portal' AND name>='0003_student_name_parts'")
            conn.commit()
        environment = {**os.environ, "EXAM_PORTAL_DB_PATH": filename}
        migrated = subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"], cwd=Path(__file__).parent, env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(migrated.returncode, 0, migrated.stderr)
        with closing(sqlite3.connect(filename)) as conn:
            self.assertEqual(conn.execute("SELECT id, name, roll_no, password_hash FROM students").fetchall(), original)
            self.assertEqual(conn.execute("SELECT first_name, last_name, middle_initial FROM students").fetchone(), ("", "", ""))
        self.assertEqual(self.client.post("/api/students/login", json={"idNumber": "ID-001", "password": "student-pass"}).status_code, 200)
        self.assertEqual(self.client.post("/api/students/signup", json=self.student_payload("ID-NEW")).status_code, 200)

    def test_teacher_retargeting_updates_student_exam_visibility(self):
        teacher = APIClient()
        self.create_teacher()
        self.assertEqual(teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"}).status_code, 200)
        exam_id = teacher.post("/api/exams", json=self.exam_payload()).json()["id"]
        for roll_no, section in (("ID-A", "A"), ("ID-B", "B")):
            self.assertEqual(self.client.post("/api/students/signup", json={**self.student_payload(roll_no), "section": section}).status_code, 200)
        response = teacher.put(f"/api/exams/{exam_id}", json={**self.exam_payload(), "sectionScope": "B"})
        self.assertEqual(response.status_code, 200)
        for roll_no, expected in (("ID-A", []), ("ID-B", [exam_id])):
            self.assertEqual(self.client.post("/api/students/login", json={"idNumber": roll_no, "password": "student-pass"}).status_code, 200)
            self.assertEqual([exam["id"] for exam in self.client.get("/api/exams?studentView=1").json()], expected)

    def test_admin_authentication(self):
        with nullcontext(self.client) as client:
            self.assertEqual(
                client.post(
                    "/api/admin/login",
                    json={"username": "administrator", "password": "configured-test-password"},
                ).status_code,
                200,
            )
            self.assertEqual(
                client.post(
                    "/api/admin/login",
                    json={"username": "administrator", "password": "wrong-password"},
                ).status_code,
                401,
            )

    def native_admin_client(self):
        client = Client()
        client.force_login(get_user_model().objects.get(username="administrator"))
        return client

    def test_native_superadmin_login_and_legacy_session_bypass_are_protected(self):
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        legacy = APIClient()
        session = legacy.session
        session["account"] = {"role": "admin", "username": "administrator"}
        session.save()
        legacy.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
        self.assertEqual(legacy.get("/api/teachers").status_code, 403)
        staff = get_user_model().objects.create_user(username="staff-only", password="staff-pass", is_staff=True)
        staff_client = Client()
        staff_client.force_login(staff)
        self.assertEqual(staff_client.get("/admin/").status_code, 302)
        self.assertEqual(staff_client.get("/api/teachers").status_code, 403)
        signed_in = Client(enforce_csrf_checks=True)
        shared_login = signed_in.get("/admin/login/")
        self.assertEqual(shared_login.status_code, 302)
        self.assertEqual(shared_login.headers["Location"], "/login")
        signed_in.get("/login").close()
        token = signed_in.cookies["csrftoken"].value
        response = signed_in.post("/api/admin/login", data={"username": "administrator", "password": "configured-test-password"}, content_type="application/json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["redirect"], "/admin/")
        dashboard = signed_in.get("/admin/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertContainsText(dashboard, "AbieksExamSys")
        self.assertEqual(signed_in.get("/api/teachers").status_code, 200)
        get_user_model().objects.filter(username="administrator").update(is_superuser=False)
        self.assertEqual(signed_in.get("/api/teachers").status_code, 403)
        self.assertEqual(signed_in.get("/admin/").status_code, 302)

    def test_superadmin_logout_returns_to_shared_login_and_requires_csrf(self):
        client = APIClient(enforce_csrf_checks=True)
        token = client.get("/api/csrf").json()["csrfToken"]
        login = client.post("/api/admin/login", json={"username": "administrator", "password": "configured-test-password"}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(login.status_code, 200)
        self.assertEqual(client.get("/admin/").status_code, 200)
        self.assertEqual(client.get("/admin/logout/").status_code, 405)
        self.assertEqual(client.post("/admin/logout/").status_code, 403)
        self.assertEqual(client.get("/admin/").status_code, 200)
        token = client.get("/api/csrf").json()["csrfToken"]
        logout = client.post("/admin/logout/?next=/", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(logout.status_code, 302)
        self.assertEqual(logout.headers["Location"], "/login")
        self.assertEqual(client.get("/api/teachers").status_code, 403)
        return_to_login = client.get("/admin/", follow=True)
        self.assertEqual(return_to_login.status_code, 200)
        self.assertEqual(return_to_login.redirect_chain[-1][0], "/login")
        return_to_login.close()
        self.create_teacher()
        token = client.get("/api/csrf").json()["csrfToken"]
        teacher_login = client.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(teacher_login.status_code, 200)
        self.assertEqual(teacher_login.json()["role"], "teacher")
        self.assertNotIn("redirect", teacher_login.json())
        self.assertEqual(client.get("/api/students/managed").status_code, 200)
        self.assertEqual(client.get("/api/teachers").status_code, 403)

    def assertContainsText(self, response, text):
        self.assertIn(text, response.content.decode())

    def test_native_admin_creates_teacher_and_changes_departments_and_password(self):
        client = self.native_admin_client()
        created = client.post("/admin/portal/teacher/add/", {"name": "Native Teacher", "username": "native-teacher", "departments": ["BSIT", "BEED"], "password1": "new-teacher-pass", "password2": "new-teacher-pass", "_save": "Save"})
        self.assertEqual(created.status_code, 302)
        teacher = Teacher.objects.get(username="native-teacher")
        login = APIClient().post("/api/admin/login", json={"username": "native-teacher", "password": "new-teacher-pass"})
        self.assertEqual(login.status_code, 200)
        self.assertCountEqual(login.json()["departments"], ["BSIT", "BEED"])
        changed = client.post(f"/admin/portal/teacher/{teacher.pk}/change/", {"name": "Updated Teacher", "username": "cannot-rename", "departments": ["BSIT"], "password1": "reset-teacher-pass", "password2": "reset-teacher-pass", "_save": "Save"})
        self.assertEqual(changed.status_code, 302)
        teacher.refresh_from_db()
        self.assertEqual((teacher.name, teacher.username), ("Updated Teacher", "native-teacher"))
        self.assertEqual(APIClient().post("/api/admin/login", json={"username": "native-teacher", "password": "new-teacher-pass"}).status_code, 401)
        updated_login = APIClient().post("/api/admin/login", json={"username": "native-teacher", "password": "reset-teacher-pass"})
        self.assertEqual(updated_login.status_code, 200)
        self.assertEqual(updated_login.json()["departments"], ["BSIT"])
        self.assertEqual(client.get(f"/admin/portal/teacher/{teacher.pk}/delete/").status_code, 403)

    def test_teacher_admin_displays_new_and_multiple_departments_after_saving(self):
        SchoolOption.objects.create(category=SchoolOption.DEPARTMENT, value="BSAIS")
        client = self.native_admin_client()
        for username, departments, expected in (
            ("custom-department-teacher", ["BSAIS"], "BSAIS"),
            ("multiple-department-teacher", ["BSIT", "BEED"], "BEED, BSIT"),
        ):
            with self.subTest(departments=departments):
                created = client.post("/admin/portal/teacher/add/", {
                    "name": username, "username": username, "departments": departments,
                    "password1": "teacher-pass", "password2": "teacher-pass", "_save": "Save",
                }, follow=True)
                self.assertEqual(created.status_code, 200)
                self.assertEqual(created.redirect_chain[-1][0], "/admin/portal/teacher/")
                listing = client.get("/admin/portal/teacher/", {"q": username})
                self.assertRegex(listing.content.decode(), rf'<td class="field-[^"]+">{expected}</td>')
                teacher = Teacher.objects.get(username=username)
                editing = client.get(f"/admin/portal/teacher/{teacher.pk}/change/")
                self.assertCountEqual(editing.context_data["adminform"].form["departments"].value(), departments)

        teacher = Teacher.objects.get(username="multiple-department-teacher")
        changed = client.post(f"/admin/portal/teacher/{teacher.pk}/change/", {
            "name": teacher.name, "departments": ["BSAIS", "BSHM"],
            "password1": "", "password2": "", "_save": "Save",
        })
        self.assertEqual(changed.status_code, 302)
        listing = client.get("/admin/portal/teacher/", {"q": teacher.username})
        self.assertRegex(listing.content.decode(), r'<td class="field-[^"]+">BSAIS, BSHM</td>')

    def test_teacher_admin_filters_every_assigned_department_and_legacy_accounts(self):
        self.create_teacher("multi-teacher", ["BSIT", "BEED"])
        self.create_teacher("other-teacher", ["BSHM"])
        self.create_teacher("legacy-teacher", ["BEED"])
        with closing(portal.get_db()) as conn:
            conn.execute("DELETE FROM teacher_departments WHERE teacher_username=?", ("legacy-teacher",))
            conn.commit()
        client = self.native_admin_client()
        for department, expected in (
            ("BSIT", ["multi-teacher"]),
            ("BEED", ["multi-teacher", "legacy-teacher"]),
            ("BSHM", ["other-teacher"]),
        ):
            with self.subTest(department=department):
                listing = client.get("/admin/portal/teacher/", {"department": department})
                self.assertEqual(listing.status_code, 200)
                self.assertCountEqual(
                    [teacher.username for teacher in listing.context_data["cl"].result_list], expected,
                )
        listing = client.get("/admin/portal/teacher/", {"q": "legacy-teacher"})
        self.assertRegex(listing.content.decode(), r'<td class="field-[^"]+">BEED</td>')

    def test_native_admin_archives_restores_and_reviews_without_losing_records(self):
        students, payload = self.submission_fixture()
        submitted = students[0].post("/api/results", json=payload).json()
        teacher = Teacher.objects.get(username="teacher1")
        client = self.native_admin_client()
        student = Student.objects.get(roll_no="ID-001")
        teacher_client = APIClient()
        teacher_client.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"})
        self.assertEqual(teacher_client.delete(f"/api/students/{student.pk}", json={"confirmation": "DELETE"}).status_code, 200)
        student.refresh_from_db()
        self.assertIsNotNone(student.deleted_at)
        student_action = {"action": "restore_students", "_selected_action": [student.pk], "index": "0"}
        archived_students = client.get("/admin/portal/student/?student_status=archived")
        self.assertEqual(archived_students.status_code, 200)
        self.assertContainsText(archived_students, "ID-001")
        self.assertEqual(Result.objects.count(), 1)
        student_action["action"] = "restore_students"
        self.assertEqual(client.post("/admin/portal/student/", student_action).status_code, 302)
        student.refresh_from_db()
        self.assertIsNone(student.deleted_at)
        self.assertEqual(Result.objects.count(), 1)
        self.assertEqual(client.get("/admin/portal/result/").status_code, 404)
        self.assertEqual(client.get("/admin/portal/submissionreturn/").status_code, 404)
        self.assertEqual(Result.objects.count(), 1)
        # Teachers retain their own review and verified return controls.
        self.assertEqual(teacher_client.get(f"/api/results/{submitted['id']}/review").status_code, 200)
        self.assertEqual(teacher_client.delete(f"/api/results/{submitted['id']}", json={"studentId": "ID-001"}).status_code, 200)
        self.assertEqual(students[0].get(f"/api/exams/{payload['examId']}/take").status_code, 200)

    def test_superadmin_permanent_delete_requires_confirmation_and_cannot_be_retrieved(self):
        from portal.accounts import RETIRED_PREFIX
        clients, payload = self.submission_fixture()
        receipt = clients[0].post("/api/results", json=payload).json()
        admin = self.native_admin_client()
        for model, obj, login_path, login_data in (
            (Teacher, Teacher.objects.get(username="teacher1"), "/api/admin/login", {"username": "teacher1", "password": "teacher-pass"}),
            (Student, Student.objects.get(roll_no="ID-001"), "/api/students/login", {"idNumber": "ID-001", "password": "student-pass"}),
        ):
            name = model._meta.model_name
            url = f"/admin/portal/{name}/{obj.pk}/account/delete/"
            self.assertContainsText(admin.get(f"/admin/portal/{name}/"), "DELETE permanently")
            confirmation_page = admin.get(url)
            self.assertEqual(confirmation_page.status_code, 200)
            if name == "student":
                self.assertContainsText(confirmation_page, "exam results and returned submissions will also be permanently deleted")
            for confirmation in ("", "delete"):
                rejected = admin.post(url, {"confirm_account_action": "yes", "confirmation": confirmation})
                self.assertEqual(rejected.status_code, 200)
                self.assertTrue(model.objects.filter(pk=obj.pk).exists())
            self.assertEqual(admin.post(url, {"confirm_account_action": "yes", "confirmation": "DELETE"}).status_code, 302)
            self.assertFalse(model.objects.filter(pk=obj.pk).exists())
            self.assertEqual(APIClient().post(login_path, json=login_data).status_code, 401)
            retrieve = f"/admin/portal/{name}/{obj.pk}/account/retrieve/"
            self.assertEqual(admin.get(retrieve).status_code, 404)
            self.assertEqual(admin.post(retrieve, {"confirm_account_action": "yes"}).status_code, 404)
            self.assertEqual(admin.post(f"/api/{name}s/{obj.pk}/restore").status_code, 404)
            if name == "teacher":
                self.assertTrue(Result.objects.filter(pk=receipt["id"]).exists())
                self.assertTrue(Result.objects.get(pk=receipt["id"]).teacher_username.startswith(RETIRED_PREFIX))
            else:
                self.assertFalse(Result.objects.filter(pk=receipt["id"]).exists())
            self.assertEqual(Exam.objects.count(), 1)
        portal_db.init_db()
        self.assertEqual((Exam.objects.count(), Result.objects.count()), (1, 0))
        # Reusing identifiers creates new accounts with no access to the old work.
        self.create_teacher()
        teacher_client = APIClient()
        self.assertEqual(teacher_client.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"}).status_code, 200)
        self.assertEqual(teacher_client.get("/api/exams").json(), [])
        self.assertEqual(teacher_client.get(f"/api/results/{receipt['id']}/review").status_code, 404)
        student_client = APIClient()
        self.assertEqual(student_client.post("/api/students/signup", json=self.student_payload()).status_code, 200)
        student_client.post("/api/students/login", json={"idNumber": "ID-001", "password": "student-pass"})
        self.assertEqual(student_client.get("/api/results").json(), [])
        self.assertEqual(student_client.get(f"/api/results/{receipt['id']}/review").status_code, 404)
        self.assertEqual(clients[0].get("/api/exams?studentView=1").status_code, 401)

    def test_superadmin_api_permanent_student_delete_removes_results_and_returns(self):
        from portal.models import SubmissionReturn
        clients, payload = self.submission_fixture()
        teacher = APIClient()
        teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"})
        receipt = clients[0].post("/api/results", json=payload).json()
        teacher.delete(f"/api/results/{receipt['id']}", json={"studentId": "ID-001"})
        clients[0].post("/api/results", json={**payload, "submissionId": "fresh"})
        student = Student.objects.get(roll_no="ID-001")
        old_teacher = Teacher.objects.get(username="teacher1")
        admin = self.native_admin_client()
        teacher.delete(f"/api/students/{student.pk}", json={"confirmation": "DELETE"})
        self.assertEqual(admin.delete(f"/api/students/{student.pk}").status_code, 400)
        for kind, obj, model in (("student", student, Student), ("teacher", old_teacher, Teacher)):
            response = admin.delete(f"/api/{kind}s/{obj.pk}", {"confirmation": "DELETE"}, content_type="application/json")
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["permanentlyDeleted"])
            self.assertFalse(model.objects.filter(pk=obj.pk).exists())
            self.assertEqual(admin.post(f"/api/{kind}s/{obj.pk}/restore").status_code, 404)
        self.assertFalse(SubmissionReturn.objects.filter(result_id=receipt["id"]).exists())
        self.assertEqual(Result.objects.count(), 0)
        self.create_teacher()
        self.assertEqual(teacher.post("/api/exams", json=self.exam_payload()).status_code, 401)
        # Reusing a student ID cannot make any deleted exam records reappear.
        self.client.post("/api/students/signup", json=self.student_payload())
        self.client.post("/api/students/login", json={"idNumber": "ID-001", "password": "student-pass"})
        self.assertEqual(self.client.get("/api/results").json(), [])

    def test_superadmin_bulk_deletion_is_permanent_for_active_and_disabled_accounts(self):
        clients, payload = self.submission_fixture()
        clients[0].post("/api/results", json=payload)
        admin = self.native_admin_client()
        for kind, model, obj in (("teacher", Teacher, Teacher.objects.get(username="teacher1")),
                                 ("student", Student, Student.objects.get(roll_no="ID-001"))):
            # Disabled accounts must also be eligible for permanent deletion.
            model.objects.filter(pk=obj.pk).update(deleted_at="2026-10-21T10:00:00")
            action = {"action": f"archive_{kind}s", "_selected_action": [obj.pk], "index": "0"}
            self.assertEqual(admin.post(f"/admin/portal/{kind}/", action).status_code, 200)
            self.assertTrue(model.objects.filter(pk=obj.pk).exists())
            action["confirmation"] = "DELETE"
            self.assertEqual(admin.post(f"/admin/portal/{kind}/", action).status_code, 302)
            self.assertFalse(model.objects.filter(pk=obj.pk).exists())
            action["action"] = f"restore_{kind}s"
            admin.post(f"/admin/portal/{kind}/", action)
            self.assertFalse(model.objects.filter(pk=obj.pk).exists())
        self.assertEqual((Exam.objects.count(), Result.objects.count()), (1, 0))

    def test_postgresql_query_adapter_translates_sqlite_placeholders_and_conflicts(self):
        prepare_sql = portal_db.PostgresConnection._prepare_sql
        self.assertEqual(prepare_sql("SELECT * FROM students WHERE id=?"), "SELECT * FROM students WHERE id=%s")
        self.assertEqual(
            prepare_sql("INSERT OR IGNORE INTO exam_departments (exam_id, department) VALUES (?,?)"),
            "INSERT INTO exam_departments (exam_id, department) VALUES (%s,%s) ON CONFLICT DO NOTHING",
        )
        self.assertEqual(prepare_sql("BEGIN IMMEDIATE"), "BEGIN")

    def test_sqlite_data_migration_requires_postgresql_target(self):
        with self.assertRaises(CommandError):
            call_command("migrate_sqlite_data", stdout=StringIO())

    def test_sqlite_data_migration_includes_django_data_but_not_migration_history(self):
        source = sqlite3.connect(":memory:")
        source.row_factory = sqlite3.Row
        source.executescript(
            "CREATE TABLE django_migrations (id INTEGER);"
            "CREATE TABLE django_content_type (id INTEGER);"
            "CREATE TABLE portal_schooloption (id INTEGER);"
            "CREATE TABLE auth_user (id INTEGER);"
            "CREATE TABLE student_teachers (student_id TEXT, teacher_username TEXT);"
            "CREATE TABLE custom_app_data (id INTEGER);"
        )
        tables = ordered_source_tables(source)
        source.close()

        self.assertEqual(
            tables,
            ["django_content_type", "portal_schooloption", "auth_user", "custom_app_data"],
        )
        self.assertEqual(quote_identifier('table"name'), '"table""name"')
        self.assertEqual(
            adapt_row(
                (1, 0, None),
                ["is_superuser", "is_staff", "last_login"],
                {"is_superuser": "boolean", "is_staff": "boolean", "last_login": "timestamp"},
            ),
            (True, False, None),
        )
        target = sqlite3.connect(":memory:")
        target.row_factory = sqlite3.Row
        target.execute("CREATE TABLE portal_schooloption (id INTEGER, category TEXT, value TEXT, position INTEGER)")
        from portal.constants import DEFAULT_SCHOOL_OPTIONS
        index = 1
        for category, values in DEFAULT_SCHOOL_OPTIONS.items():
            for position, value in enumerate(values):
                target.execute(
                    "INSERT INTO portal_schooloption VALUES (?,?,?,?)",
                    (index, category, value, position),
                )
                index += 1
        self.assertTrue(target_has_seeded_school_options(target))
        target.execute("UPDATE portal_schooloption SET value='Customized' WHERE id=1")
        self.assertFalse(target_has_seeded_school_options(target))
        target.close()

    def test_sqlite_data_migration_resume_only_accepts_identical_table_rows(self):
        source = sqlite3.connect(":memory:")
        target = sqlite3.connect(":memory:")
        source.row_factory = sqlite3.Row
        target.row_factory = sqlite3.Row
        source.execute("CREATE TABLE students (id TEXT, name TEXT)")
        target.execute("CREATE TABLE students (id TEXT, name TEXT)")
        source.execute("INSERT INTO students VALUES (?, ?)", ("student-1", "Student One"))
        target.execute("INSERT INTO students VALUES (?, ?)", ("student-1", "Student One"))
        self.assertTrue(table_rows_match(source, target, "students", ["id", "name"]))

        target.execute("UPDATE students SET name='Different Student'")
        self.assertFalse(table_rows_match(source, target, "students", ["id", "name"]))
        source.close()
        target.close()

    def test_native_admin_resets_student_password(self):
        self.create_teacher()
        self.client.post("/api/students/signup", json=self.student_payload())
        student = Student.objects.get(roll_no="ID-001")
        client = self.native_admin_client()
        changed = client.post(f"/admin/portal/student/{student.pk}/change/", {"password1": "native-reset-pass", "password2": "native-reset-pass", "_save": "Save"})
        self.assertEqual(changed.status_code, 302)
        self.assertEqual(APIClient().post("/api/students/login", json={"idNumber": "ID-001", "password": "native-reset-pass"}).status_code, 200)
        self.assertEqual(APIClient().post("/api/students/login", json={"idNumber": "ID-001", "password": "student-pass"}).status_code, 401)

    def test_superadmin_bootstrap_never_overwrites_existing_credentials(self):
        with patch("portal.views._load_admin_password", return_value="different-password"):
            call_command("bootstrap_superadmin", stdout=StringIO())
        user = get_user_model().objects.get(username="administrator")
        self.assertTrue(user.check_password("configured-test-password"))
        self.assertFalse(user.check_password("different-password"))
        with patch.dict(os.environ, {"EXAM_PORTAL_ADMIN_USERNAME": "new-superadmin"}), patch("portal.views._load_admin_password", return_value="new-admin-pass"):
            call_command("bootstrap_superadmin", stdout=StringIO())
        new_admin = get_user_model().objects.get(username="new-superadmin")
        self.assertTrue(new_admin.is_superuser)
        self.assertTrue(new_admin.check_password("new-admin-pass"))
        get_user_model().objects.filter(username="administrator").update(is_superuser=False)
        with self.assertRaises(CommandError):
            call_command("bootstrap_superadmin", stdout=StringIO())

    def test_django_csrf_tokens_rotate_and_protect_all_write_methods(self):
        self.create_teacher()
        client = APIClient(enforce_csrf_checks=True)
        credentials = {"username": "teacher1", "password": "teacher-pass"}
        missing = client.post("/api/admin/login", json=credentials)
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(missing.headers["Cache-Control"], "no-store")
        token = client.get("/api/csrf").json()["csrfToken"]
        foreign = client.post("/api/admin/login", json=credentials, HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN="http://other.invalid")
        self.assertEqual(foreign.status_code, 403)
        signed_in = client.post("/api/admin/login", json=credentials, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(signed_in.status_code, 200)
        self.assertTrue(signed_in.cookies["aralhub_session"]["httponly"])
        self.assertEqual(signed_in.cookies["aralhub_session"]["samesite"], "Lax")
        self.assertEqual(client.post("/api/exams", json=self.exam_payload(), HTTP_X_CSRFTOKEN=token).status_code, 403)
        token = client.get("/api/csrf").json()["csrfToken"]
        created = client.post("/api/exams", json=self.exam_payload(), HTTP_X_CSRFTOKEN=token)
        self.assertEqual(created.status_code, 200)
        exam_id = created.json()["id"]
        self.assertEqual(client.put(f"/api/exams/{exam_id}", json=self.exam_payload()).status_code, 403)
        self.assertEqual(client.put(f"/api/exams/{exam_id}", json=self.exam_payload(), HTTP_X_CSRFTOKEN=token).status_code, 200)
        self.assertEqual(client.delete(f"/api/exams/{exam_id}").status_code, 403)
        self.assertEqual(client.delete(f"/api/exams/{exam_id}", HTTP_X_CSRFTOKEN=token).status_code, 200)
        self.assertEqual(client.post("/api/logout", HTTP_X_CSRFTOKEN=token).status_code, 200)
        self.assertEqual(client.get("/api/students/managed").status_code, 403)

    def test_existing_passwords_still_work_and_new_passwords_use_django(self):
        self.create_teacher()
        self.client.post("/api/students/signup", json=self.student_payload())
        salt = "synthetic-legacy-salt"
        legacy_teacher = "scrypt:32768:8:1$" + salt + "$" + hashlib.scrypt(b"teacher-pass", salt=salt.encode(), n=32768, r=8, p=1, maxmem=128 * 1024 * 1024).hex()
        legacy_student = "pbkdf2:sha256:600000$" + salt + "$" + hashlib.pbkdf2_hmac("sha256", b"student-pass", salt.encode(), 600000).hex()
        conn = portal.get_db()
        conn.execute("UPDATE teachers SET password_hash=?", (legacy_teacher,))
        conn.execute("UPDATE students SET password_hash=?", (legacy_student,))
        conn.commit()
        conn.close()
        teacher = APIClient()
        self.assertEqual(teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"}).status_code, 200)
        self.assertEqual(self.client.post("/api/students/login", json={"idNumber": "ID-001", "password": "student-pass"}).status_code, 200)
        self.assertEqual(self.client.post("/api/students/login", json={"idNumber": "ID-001", "password": "wrong-pass"}).status_code, 401)
        with override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.PBKDF2PasswordHasher"]):
            encoded = portal.generate_password_hash("synthetic-password")
            self.assertTrue(encoded.startswith("pbkdf2_sha256$"))
            self.assertTrue(portal.check_password_hash(encoded, "synthetic-password"))
            self.assertFalse(portal.check_password_hash(encoded, "wrong-password"))

    def test_django_serves_frontend_assets_and_rejects_invalid_requests(self):
        for path, content_type in [("/", "text/html"), ("/index.html", "text/html"), ("/login", "text/html"), ("/static/admin/css/base.css", "text/css"), ("/css/modern.css", "text/css"), ("/js/common.js", "text/javascript"), ("/exam_template.txt", "text/plain")]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.headers["Content-Type"].startswith(content_type))
                response.close()
        self.assertEqual(self.client.get("/admin.html").headers["Location"], "/admin/")
        self.assertEqual(Teacher.objects.count(), 0)
        self.assertEqual(self.client.post("/api/teachers/signup", json=self.teacher_payload()).status_code, 405)
        self.assertEqual(Teacher.objects.count(), 0)
        for path in ("/.admin_password", "/exam.db", "/api/missing", "/../exam.db"):
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get("/", HTTP_HOST="untrusted.invalid").status_code, 400)
        self.assertEqual(self.client.post("/api/exams/missing/take").status_code, 405)
        invalid = Client().post("/api/students/login", data="{invalid", content_type="application/json")
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("error", invalid.json())
        self.assertEqual(self.client.post("/api/students/login", json=[]).status_code, 400)

    def test_django_migration_preserves_existing_records_and_is_idempotent(self):
        self.create_teacher()
        self.client.post("/api/students/signup", json=self.student_payload())
        teacher = APIClient()
        teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"})
        exam_id = teacher.post("/api/exams", json=self.exam_payload()).json()["id"]
        self.client.post("/api/students/login", json={"idNumber": "ID-001", "password": "student-pass"})
        self.client.post("/api/results", json={"examId": exam_id, "answers": {}})
        filename = os.path.join(self.temp_dir.name, "test.db")
        with closing(sqlite3.connect(filename)) as conn:
            conn.execute("DELETE FROM django_migrations WHERE app='portal'")
            conn.commit()

        def records():
            with closing(sqlite3.connect(filename)) as conn:
                return {table: conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall() for table in ("teachers", "teacher_departments", "students", "exams", "exam_departments", "questions", "results")}

        before = records()
        environment = {**os.environ, "EXAM_PORTAL_DB_PATH": filename}
        for _ in range(2):
            result = subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"], cwd=Path(__file__).parent, env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(records(), before)
        with closing(sqlite3.connect(filename)) as conn:
            result_id, exam_id = conn.execute("SELECT id, exam_id FROM results LIMIT 1").fetchone()
            question_count = conn.execute("SELECT COUNT(*) FROM questions WHERE exam_id=?", (exam_id,)).fetchone()[0]
            conn.execute("UPDATE results SET score=1, total=?, percent=50 WHERE id=?", (question_count, result_id))
            conn.execute(
                "UPDATE results SET score=1, total=?, percent=2 WHERE id=?",
                (question_count * 2, result_id),
            )
            conn.execute("DELETE FROM django_migrations WHERE app='portal' AND name>='0011_correct_two_point_scores'")
            conn.commit()
        result = subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"], cwd=Path(__file__).parent, env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        with closing(sqlite3.connect(filename)) as conn:
            self.assertEqual(conn.execute("SELECT score, total, percent FROM results WHERE id=?", (result_id,)).fetchone(), (2, question_count * 2, 50))

    def test_retired_enrollment_migration_preserves_active_records_and_stays_removed(self):
        clients, payload = self.submission_fixture()
        self.assertEqual(clients[0].post("/api/results", json=payload).status_code, 200)
        student = Student.objects.get(roll_no="ID-001")
        filename = os.path.join(self.temp_dir.name, "test.db")
        connections.close_all()
        with closing(sqlite3.connect(filename)) as conn:
            conn.execute("CREATE TABLE student_teachers (student_id TEXT NOT NULL, teacher_username TEXT NOT NULL, PRIMARY KEY (student_id, teacher_username))")
            conn.execute("INSERT INTO student_teachers VALUES (?, ?)", (student.pk, "teacher1"))
            conn.execute("DELETE FROM django_migrations WHERE app='portal' AND name>='0008_remove_legacy_student_teachers'")
            conn.commit()

        def active_records():
            with closing(sqlite3.connect(filename)) as conn:
                tables = [row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT IN ('student_teachers', 'django_migrations') ORDER BY name"
                )]
                return {
                    table: conn.execute(f'SELECT * FROM {quote_identifier(table)} ORDER BY rowid').fetchall()
                    for table in tables
                }

        before = active_records()
        for _ in range(2):
            migrated = subprocess.run(
                [sys.executable, "manage.py", "migrate", "--noinput"],
                cwd=Path(__file__).parent,
                env={**os.environ, "EXAM_PORTAL_DB_PATH": filename},
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(migrated.returncode, 0, migrated.stderr)
            self.assertEqual(active_records(), before)
        portal_db.init_db()
        with closing(sqlite3.connect(filename)) as conn:
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='student_teachers'").fetchone())
        self.assertEqual(active_records(), before)

    def test_student_password_reset_is_limited_to_admin_and_program_teacher(self):
        self.create_teacher()
        other_teacher = self.teacher_payload()
        other_teacher["username"] = "teacher2"
        other_teacher["departments"] = ["BEED"]
        self.create_teacher("teacher2", ["BEED"])
        self.assertEqual(
            self.client.post("/api/students/signup", json=self.student_payload()).status_code,
            200,
        )
        self.assertEqual(self.client.get("/api/students/managed").status_code, 403)

        assigned_teacher = APIClient()
        self.assertEqual(
            assigned_teacher.post(
                "/api/admin/login",
                json={"username": "teacher1", "password": "teacher-pass"},
            ).status_code,
            200,
        )
        managed_students = assigned_teacher.get("/api/students/managed")
        self.assertEqual(len(managed_students.json()), 1)
        self.assertNotIn("password_hash", managed_students.json()[0])
        student_id = managed_students.json()[0]["id"]
        self.assertEqual(
            assigned_teacher.post(
                f"/api/students/{student_id}/reset-password",
                json={"password": "new-student-pass"},
            ).status_code,
            200,
        )

        student = APIClient()
        self.assertEqual(
            student.post(
                "/api/students/login",
                json={"idNumber": "ID-001", "password": "student-pass"},
            ).status_code,
            401,
        )
        self.assertEqual(
            student.post(
                "/api/students/login",
                json={"idNumber": "ID-001", "password": "new-student-pass"},
            ).status_code,
            200,
        )

        unassigned_teacher = APIClient()
        self.assertEqual(
            unassigned_teacher.post(
                "/api/admin/login",
                json={"username": "teacher2", "password": "teacher-pass"},
            ).status_code,
            200,
        )
        self.assertEqual(unassigned_teacher.get("/api/students/managed").json(), [])
        self.assertEqual(
            unassigned_teacher.post(
                f"/api/students/{student_id}/reset-password",
                json={"password": "unauthorized-pass"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/admin/login",
                json={"username": "administrator", "password": "configured-test-password"},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                f"/api/students/{student_id}/reset-password",
                json={"password": "admin-student-pass"},
            ).status_code,
            200,
        )

    def test_student_archive_and_restore_are_limited_to_assigned_staff_and_keep_results(self):
        student_clients, payload = self.submission_fixture()
        submitted = student_clients[0].post("/api/results", json=payload).json()
        student = Student.objects.get(roll_no="ID-001")

        teacher = APIClient()
        self.create_teacher("teacher2", ["BEED"])
        self.assertEqual(
            teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"}).status_code,
            200,
        )
        other_teacher = APIClient()
        self.assertEqual(
            other_teacher.post("/api/admin/login", json={"username": "teacher2", "password": "teacher-pass"}).status_code,
            200,
        )
        self.assertEqual(other_teacher.delete(f"/api/students/{student.pk}", json={"confirmation": "DELETE"}).status_code, 403)
        self.assertEqual(other_teacher.get("/api/students/archived").json(), [])

        for confirmation in (None, "delete", "WRONG"):
            response = teacher.delete(f"/api/students/{student.pk}", json={"confirmation": confirmation})
            self.assertEqual(response.status_code, 400)
            self.assertIsNone(Student.objects.get(pk=student.pk).deleted_at)
        archived = teacher.delete(f"/api/students/{student.pk}", json={"confirmation": "DELETE"})
        self.assertEqual(archived.status_code, 200, archived.content)
        student.refresh_from_db()
        self.assertTrue(student.deleted_at)
        self.assertEqual(teacher.get("/api/students/managed").json(), [])
        archived_students = teacher.get("/api/students/archived").json()
        self.assertEqual([row["id"] for row in archived_students], [student.pk])
        self.assertEqual(teacher.delete(f"/api/students/{student.pk}", json={"confirmation": "DELETE"}).status_code, 409)
        self.assertEqual(student_clients[0].get("/api/exams?studentView=1").status_code, 401)
        self.assertEqual(
            APIClient().post("/api/students/login", json={"idNumber": "ID-001", "password": "student-pass"}).status_code,
            401,
        )
        self.assertEqual(Result.objects.filter(pk=submitted["id"]).count(), 1)

        restored = teacher.post(f"/api/students/{student.pk}/restore", json={})
        self.assertEqual(restored.status_code, 403)
        admin = self.native_admin_client()
        self.assertEqual(admin.post(f"/api/students/{student.pk}/restore").status_code, 200)
        self.assertIsNone(Student.objects.get(pk=student.pk).deleted_at)
        self.assertEqual(
            APIClient().post("/api/students/login", json={"idNumber": "ID-001", "password": "student-pass"}).status_code,
            200,
        )

        self.assertEqual(teacher.delete(f"/api/students/{student.pk}", json={"confirmation": "DELETE"}).status_code, 200)
        self.client.force_login(get_user_model().objects.get(username="administrator"))
        self.assertEqual([row["id"] for row in self.client.get("/api/students/archived").json()], [student.pk])
        self.assertEqual(self.client.post(f"/api/students/{student.pk}/restore", json={}).status_code, 200)
        self.assertEqual(Result.objects.filter(pk=submitted["id"]).count(), 1)

    def test_only_super_admin_can_reset_teacher_password(self):
        self.create_teacher()
        self.assertEqual(self.client.get("/api/teachers").status_code, 403)

        teacher = APIClient()
        self.assertEqual(
            teacher.post(
                "/api/admin/login",
                json={"username": "teacher1", "password": "teacher-pass"},
            ).status_code,
            200,
        )
        teacher_records = self.client.post(
            "/api/admin/login",
            json={"username": "administrator", "password": "configured-test-password"},
        )
        self.assertEqual(teacher_records.status_code, 200)
        teacher_id = self.client.get("/api/teachers").json()[0]["id"]

        self.assertEqual(
            teacher.post(
                f"/api/teachers/{teacher_id}/reset-password",
                json={"password": "unauthorized-pass"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                f"/api/teachers/{teacher_id}/reset-password",
                json={"password": "new-teacher-pass"},
            ).status_code,
            200,
        )
        self.assertEqual(
            teacher.post(
                "/api/admin/login",
                json={"username": "teacher1", "password": "teacher-pass"},
            ).status_code,
            401,
        )
        self.assertEqual(
            teacher.post(
                "/api/admin/login",
                json={"username": "teacher1", "password": "new-teacher-pass"},
            ).status_code,
            200,
        )

    def test_student_teacher_and_superadmin_sessions_are_independent_and_teacher_can_return_without_login(self):
        self.create_teacher()
        self.client.post("/api/students/signup", json=self.student_payload())
        client = APIClient(enforce_csrf_checks=True)
        teacher_headers = {"HTTP_X_PORTAL_ROLE": "teacher"}
        student_headers = {"HTTP_X_PORTAL_ROLE": "student"}

        def token(headers):
            return client.get("/api/csrf", **headers).json()["csrfToken"]

        csrf = token(teacher_headers)
        logged_in = client.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"}, HTTP_X_CSRFTOKEN=csrf, **teacher_headers)
        self.assertEqual(logged_in.status_code, 200)
        teacher_cookie_name = settings.SESSION_COOKIE_NAME + "_teacher"
        student_cookie_name = settings.SESSION_COOKIE_NAME + "_student"
        teacher_cookie = client.cookies[teacher_cookie_name].value
        csrf = token(teacher_headers)
        created = client.post("/api/exams", json=self.exam_payload(), HTTP_X_CSRFTOKEN=csrf, **teacher_headers)
        self.assertEqual(created.status_code, 200, created.content)
        exam_id = created.json()["id"]
        logged_in_student = client.post("/api/students/login", json={"idNumber": "ID-001", "password": "student-pass"}, HTTP_X_CSRFTOKEN=csrf, **student_headers)
        self.assertEqual(logged_in_student.status_code, 200)
        self.assertEqual(client.cookies[teacher_cookie_name].value, teacher_cookie)
        self.assertIn(student_cookie_name, client.cookies)
        self.assertEqual(client.get("/api/exams?studentView=1", **student_headers).json()[0]["id"], exam_id)
        self.assertEqual(client.get("/api/exams", **teacher_headers).status_code, 200)
        stale = client.post("/api/results", json={"examId": exam_id, "answers": {}}, HTTP_X_CSRFTOKEN=csrf, **student_headers)
        self.assertEqual((stale.status_code, stale.json()["code"]), (403, "csrf_failed"))
        csrf = token(student_headers)
        submitted = client.post("/api/results", json={"examId": exam_id, "answers": {}}, HTTP_X_CSRFTOKEN=csrf, **student_headers)
        self.assertEqual(submitted.status_code, 200, submitted.content)
        result_id = submitted.json()["id"]
        returned = client.delete(f"/api/results/{result_id}", json={"studentId": "ID-001"}, HTTP_X_CSRFTOKEN=csrf, **teacher_headers)
        self.assertEqual(returned.status_code, 200, returned.content)
        self.assertEqual(client.get(f"/api/exams/{exam_id}/take", **student_headers).status_code, 200)
        attacker = APIClient()
        attacker.cookies[teacher_cookie_name] = client.cookies[student_cookie_name].value
        self.assertEqual(attacker.get("/api/exams", **teacher_headers).status_code, 401)
        self.assertEqual(client.post("/api/logout", HTTP_X_CSRFTOKEN=csrf, **student_headers).status_code, 200)
        self.assertEqual(client.get("/api/exams?studentView=1", **student_headers).status_code, 401)
        self.assertEqual(client.get("/api/results", **teacher_headers).status_code, 200)
        csrf = token(teacher_headers)
        superadmin_login = client.post("/api/admin/login", json={"username": "administrator", "password": "configured-test-password"}, HTTP_X_CSRFTOKEN=csrf, **teacher_headers)
        self.assertEqual(superadmin_login.json()["role"], "admin")
        self.assertEqual(client.get("/admin/").status_code, 200)
        self.assertEqual(client.get("/api/exams", **teacher_headers).status_code, 200)

    def test_existing_teacher_cookie_upgrades_once_and_logout_does_not_restore_it(self):
        self.create_teacher()
        client = APIClient()
        client.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"})
        default = settings.SESSION_COOKIE_NAME
        self.assertTrue(client.cookies[default].value)
        teacher_headers = {"HTTP_X_PORTAL_ROLE": "teacher"}
        upgraded = client.get("/api/exams", **teacher_headers)
        self.assertEqual(upgraded.status_code, 200)
        self.assertTrue(client.cookies[default + "_teacher"].value)
        self.assertFalse(client.cookies[default].value)
        client.post("/api/logout", **teacher_headers)
        self.assertEqual(client.get("/api/exams", **teacher_headers).status_code, 401)

    def test_teacher_can_reauthenticate_and_publish_fifty_questions_without_losing_permissions(self):
        self.create_teacher()
        teacher = APIClient()
        login = {"username": "teacher1", "password": "teacher-pass"}
        teacher.post("/api/admin/login", json=login)
        teacher.post("/api/logout", json={})
        payload = self.exam_payload("Imported midterm")
        payload["expectedTeacherUsername"] = "teacher1"
        payload["questions"] = [{**self.exam_payload()["questions"][0], "text": f"Question {index + 1}"} for index in range(50)]
        expired = teacher.post("/api/exams", json=payload)
        self.assertEqual(expired.status_code, 401)
        self.assertEqual(expired.json()["code"], "staff_session_expired")
        self.assertEqual(Exam.objects.count(), 0)
        teacher.post("/api/admin/login", json=login)
        created = teacher.post("/api/exams", json=payload)
        self.assertEqual(created.status_code, 200, created.content)
        exam_id = created.json()["id"]
        self.assertEqual(len(teacher.get(f"/api/exams/{exam_id}").json()["questions"]), 50)
        teacher.post("/api/logout", json={})
        expired_edit = teacher.put(f"/api/exams/{exam_id}", json=payload)
        self.assertEqual(expired_edit.status_code, 401)
        admin = self.native_admin_client()
        forbidden = admin.post("/api/exams", json=payload)
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(forbidden.json()["code"], "teacher_required")
        self.create_teacher(username="other-teacher")
        teacher.post("/api/admin/login", json={"username": "other-teacher", "password": "teacher-pass"})
        changed = teacher.post("/api/exams", json=payload)
        self.assertEqual(changed.status_code, 403)
        self.assertEqual(changed.json()["code"], "teacher_account_changed")
        self.assertEqual(teacher.put(f"/api/exams/{exam_id}", json=payload).json()["code"], "teacher_account_changed")
        self.assertEqual(Exam.objects.count(), 1)

    def test_teacher_can_create_and_manage_exam(self):
        teacher = APIClient()
        self.create_teacher()
        self.assertEqual(
            teacher.post(
                "/api/admin/login",
                json={"username": "teacher1", "password": "teacher-pass"},
            ).status_code,
            200,
        )

        created = teacher.post("/api/exams", json=self.exam_payload())
        self.assertEqual(created.status_code, 200)
        exam_id = created.json()["id"]

        listed = teacher.get("/api/exams").json()
        self.assertTrue(any(item["id"] == exam_id for item in listed))

        updated = teacher.put(
            f"/api/exams/{exam_id}",
            json=self.exam_payload("Updated Unit Test"),
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(teacher.get(f"/api/exams/{exam_id}").json()["title"], "Updated Unit Test")

        self.assertEqual(teacher.delete(f"/api/exams/{exam_id}").status_code, 200)
        self.assertEqual(teacher.get(f"/api/exams/{exam_id}").status_code, 404)

    def assert_no_answer_details(self, value):
        forbidden = {"review", "questions", "answers", "answers_json", "correct", "answerText", "answer", "alternatives", "chosen", "isCorrect", "options"}
        if isinstance(value, dict):
            self.assertFalse(forbidden.intersection(value), value)
            for item in value.values():
                self.assert_no_answer_details(item)
        elif isinstance(value, list):
            for item in value:
                self.assert_no_answer_details(item)

    def test_student_receipts_hide_answers_and_own_review_includes_correct_answers(self):
        teacher = APIClient()
        self.create_teacher()
        self.assertEqual(
            teacher.post(
                "/api/admin/login",
                json={"username": "teacher1", "password": "teacher-pass"},
            ).status_code,
            200,
        )

        exam = teacher.post("/api/exams", json=self.exam_payload())
        exam_id = exam.json()["id"]

        self.assertEqual(self.client.post("/api/students/signup", json=self.student_payload()).status_code, 200)

        student = APIClient()
        self.assertEqual(
            student.post(
                "/api/students/login",
                json={"idNumber": "ID-001", "password": "student-pass"},
            ).status_code,
            200,
        )

        take_exam = student.get(f"/api/exams/{exam_id}/take")
        self.assertEqual(take_exam.status_code, 200)
        self.assertEqual(take_exam.json()["pointsPerQuestion"], 2)
        questions = take_exam.json()["questions"]
        answers = {questions[0]["id"]: 1, questions[1]["id"]: "Manila"}

        invalid = student.post("/api/results", json={"examId": exam_id, "answers": {questions[0]["id"]: "invalid-number"}})
        self.assertEqual(invalid.status_code, 400)
        payload = {
            "examId": exam_id,
            "answers": answers,
            "submissionId": "test-attempt-1",
            "autoSubmitted": True,
            "submitReason": "tab_switch",
        }
        submitted = student.post("/api/results", json=payload)
        self.assertEqual(submitted.status_code, 200)

        result = submitted.json()
        self.assertEqual((result["name"], result["rollNo"], result["score"], result["total"]), ("Student, Test A.", "ID-001", 4, 4))
        self.assertEqual((result["percent"], result["gradeStatus"]), (100, "passed"))
        self.assertTrue(result["autoSubmitted"])
        self.assertEqual(result["submitReason"], "tab_switch")
        self.assertEqual(student.get("/api/results?rollNo=ID-001").json()[0]["examId"], exam_id)
        self.assert_no_answer_details(result)
        student_review_response = student.get(f"/api/results/{result['id']}/review")
        self.assertEqual(student_review_response.status_code, 200)
        student_review = student_review_response.json()["review"]
        self.assertEqual(len(student_review), 2)
        self.assertTrue(all("isCorrect" in item and "pointsAwarded" in item for item in student_review))
        self.assertEqual(student_review[0]["correct"], 1)
        self.assertEqual(student_review[1]["answer"], "MANILA")
        other_student = APIClient()
        self.assertEqual(self.client.post("/api/students/signup", json=self.student_payload("ID-002")).status_code, 200)
        self.assertEqual(other_student.post("/api/students/login", json={"idNumber": "ID-002", "password": "student-pass"}).status_code, 200)
        self.assertEqual(other_student.get(f"/api/results/{result['id']}/review").status_code, 404)
        self.assertEqual(student.get(f"/api/exams/{exam_id}/take").status_code, 403)
        self.assertEqual(student.get(f"/api/exams/{exam_id}").status_code, 401)
        listed = student.get("/api/results?rollNo=ANOTHER-STUDENT")
        self.assertEqual(listed.status_code, 200)
        self.assert_no_answer_details(listed.json())
        self.assertTrue(all(item["rollNo"] == "ID-001" for item in listed.json()))
        self.assertEqual(listed.headers["Cache-Control"], "no-store")
        self.assertEqual(submitted.headers["Cache-Control"], "no-store")
        teacher_review = teacher.get(f"/api/results/{result['id']}/review")
        self.assertEqual(teacher_review.status_code, 200)
        self.assertEqual(len(teacher_review.json()["review"]), 2)
        self.assertTrue(all(question["pointsPossible"] == 2 for question in teacher_review.json()["review"]))
        self.assertEqual(sum(question["pointsAwarded"] for question in teacher_review.json()["review"]), result["score"])

        replay = student.post("/api/results", json={**payload, "answers": {}})
        self.assertEqual(replay.status_code, 200)
        self.assertEqual(replay.json()["id"], result["id"])
        self.assertEqual(replay.json()["score"], 4)
        self.assertEqual(replay.json()["submittedAt"], result["submittedAt"])
        self.assert_no_answer_details(replay.json())
        self.assertEqual(replay.json()["gradeStatus"], "passed")
        self.assertEqual(student.post("/api/results", json={**payload, "submissionId": "different"}).status_code, 409)
        self.assertEqual(student.post("/api/results", json={"examId": exam_id, "answers": answers}).status_code, 409)

        anonymous = APIClient()
        self.assertEqual(anonymous.get(f"/api/results/{result['id']}/review").status_code, 401)
        other_teacher_payload = {**self.teacher_payload(), "username": "teacher2"}
        other_teacher = APIClient()
        self.create_teacher("teacher2")
        self.assertEqual(other_teacher.post("/api/admin/login", json={"username": "teacher2", "password": "teacher-pass"}).status_code, 200)
        self.assertEqual(other_teacher.get(f"/api/results/{result['id']}/review").status_code, 403)

    def submission_fixture(self):
        teacher = APIClient()
        self.create_teacher()
        self.assertEqual(teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"}).status_code, 200)
        exam_id = teacher.post("/api/exams", json=self.exam_payload()).json()["id"]
        self.assertEqual(self.client.post("/api/students/signup", json=self.student_payload()).status_code, 200)
        clients = [APIClient() for _ in range(2)]
        for client in clients:
            self.assertEqual(client.post("/api/students/login", json={"idNumber": "ID-001", "password": "student-pass"}).status_code, 200)
        return clients, {"examId": exam_id, "answers": {}, "submissionId": "same-concurrent-attempt"}

    def test_activity_log_survives_submission_retry_and_teacher_return(self):
        from portal.models import SubmissionReturn
        clients, payload = self.submission_fixture()
        kinds = ["attempt_started", "focus_lost", "warning_started", "page_hidden",
                 "page_visible", "focus_returned", "warning_acknowledged", "submit_manual"]
        activity = {"version": 1, "complete": True, "truncated": False, "events": [
            {"type": kind, "at": 1794441600000 + i * 1000,
             "hidden": kind == "page_hidden", "focused": kind not in ("focus_lost", "page_hidden")}
            for i, kind in enumerate(kinds)
        ]}
        payload["activityLog"] = activity
        original = clients[0].post("/api/results", json=payload)
        self.assertEqual(original.status_code, 200)
        result_id = original.json()["id"]
        teacher = APIClient()
        teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"})
        detail = teacher.get(f"/api/results/{result_id}/review").json()
        self.assertEqual(detail["activityLog"], activity)
        self.assertEqual(detail["activitySummary"], {
            "focusLossCount": 1, "hiddenCount": 1, "warningCount": 1, "complete": True, "truncated": False,
        })
        listed = teacher.get(f"/api/results?examId={payload['examId']}").json()[0]
        self.assertEqual(listed["activitySummary"], detail["activitySummary"])
        self.assertNotIn("activityLog", listed)
        self.assertEqual(clients[0].get(f"/api/results/{result_id}/review").json()["activityLog"], activity)
        self.assertEqual(APIClient().get(f"/api/results/{result_id}/review").status_code, 401)
        self.create_teacher("other-teacher")
        other = APIClient()
        other.post("/api/admin/login", json={"username": "other-teacher", "password": "teacher-pass"})
        self.assertEqual(other.get(f"/api/results/{result_id}/review").status_code, 403)
        self.assertEqual(other.get("/api/results").json(), [])
        self.client.post("/api/students/signup", json=self.student_payload("ID-002"))
        other_student = APIClient()
        other_student.post("/api/students/login", json={"idNumber": "ID-002", "password": "student-pass"})
        self.assertEqual(other_student.get(f"/api/results/{result_id}/review").status_code, 404)

        # A lost response cannot overwrite the first receipt's activity evidence.
        retry = clients[1].post("/api/results", json={**payload, "activityLog": None})
        self.assertEqual(retry.json()["id"], result_id)
        self.assertEqual(teacher.get(f"/api/results/{result_id}/review").json()["activityLog"], activity)
        self.assertEqual(teacher.delete(f"/api/results/{result_id}", json={"studentId": "ID-001"}).status_code, 200)
        snapshot = json.loads(SubmissionReturn.objects.get(result_id=result_id).snapshot)
        self.assertEqual(json.loads(snapshot["activity_log_json"]), activity)
        fresh = clients[0].post("/api/results", json={**payload, "submissionId": "returned-attempt", "activityLog": None})
        self.assertEqual(fresh.status_code, 200)
        self.assertIsNone(teacher.get(f"/api/results/{fresh.json()['id']}/review").json()["activitySummary"])

    def test_live_monitor_records_before_submission_and_keeps_evidence_on_stale_requests(self):
        from portal.models import AssessmentActivity
        clients, payload = self.submission_fixture()
        teacher = APIClient()
        teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"})
        url = f"/api/exams/{payload['examId']}/activity"
        log = {"version": 1, "complete": True, "truncated": False, "events": []}
        body = {"submissionId": payload["submissionId"], "activityLog": log, "pageHidden": False, "windowFocused": True}
        self.assertEqual(APIClient().post(url, json=body).status_code, 401)
        self.assertEqual(clients[0].get(url).status_code, 401)
        self.assertEqual(clients[0].post(url, json=body).status_code, 200)
        self.assertEqual(Result.objects.count(), 0)
        for i, kind in enumerate(["focus_lost", "warning_started", "page_hidden", "page_visible", "focus_returned", "warning_acknowledged", "focus_lost"]):
            log["events"].append({"type": kind, "at": 1794441600000+i*1000, "hidden": kind == "page_hidden", "focused": kind in ("page_visible", "focus_returned", "warning_acknowledged")})
        current = {**body, "windowFocused": False}
        self.assertEqual(clients[0].post(url, json=current).status_code, 200)
        self.assertEqual(clients[0].post(url, json=current).status_code, 200)
        self.assertEqual(clients[0].post(url, json={**body, "activityLog": {**log, "events": []}}).status_code, 200)
        attempts = teacher.get(url).json()
        self.assertEqual(len(attempts), 1)
        attempt = attempts[0]
        self.assertEqual(attempt["activitySummary"]["focusLossCount"], 2)
        self.assertEqual(attempt["activitySummary"]["hiddenCount"], 1)
        self.assertEqual(attempt["status"], "unfocused")
        self.assertNotIn("activityLog", attempt)
        detail_url = f"{url}/{attempt['id']}"
        self.assertEqual(teacher.get(detail_url).json()["activityLog"], log)
        with patch("portal.monitoring.time.time", return_value=attempt["receivedAt"]/1000+31):
            self.assertEqual(teacher.get(url).json()[0]["status"], "not_reporting")
        self.create_teacher("other-monitor")
        other = APIClient()
        other.post("/api/admin/login", json={"username": "other-monitor", "password": "teacher-pass"})
        self.assertEqual(other.get(url).status_code, 403)
        self.assertEqual(other.get(detail_url).status_code, 403)
        self.assertEqual(clients[0].get(detail_url).status_code, 401)
        self.assertEqual(teacher.get(url + "/missing").status_code, 404)
        # Submission still retains server evidence if its browser copy is stale.
        submitted = clients[0].post("/api/results", json={**payload, "activityLog": None})
        self.assertEqual(submitted.status_code, 200)
        receipt = teacher.get(f"/api/results/{submitted.json()['id']}/review").json()
        self.assertEqual(receipt["activityLog"], log)
        self.assertEqual(teacher.get(url).json()[0]["status"], "submitted")
        self.assertTrue(clients[0].post(url, json=current).json()["submitted"])
        self.assertEqual(AssessmentActivity.objects.count(), 1)
        teacher.delete(f"/api/results/{submitted.json()['id']}", json={"studentId": "ID-001"})
        self.assertEqual(clients[0].post(url, json=current).status_code, 409)
        self.assertEqual(clients[0].post(url, json={**body, "submissionId": "fresh-attempt", "activityLog": {**log, "events": []}}).status_code, 200)
        self.assertEqual(AssessmentActivity.objects.count(), 2)

    def test_activity_log_validation_and_legacy_receipts(self):
        clients, payload = self.submission_fixture()
        base = {"version": 1, "complete": True, "truncated": False, "events": []}
        event = {"type": "focus_lost", "at": 1794441600000, "hidden": False, "focused": False}
        invalid = [[], "invalid", {**base, "version": 2}, {**base, "complete": 1},
                   {**base, "events": [event] * 2001},
                   *({**base, "events": [{**event, **change}]} for change in [
                       {"type": "alt_tab"}, {"type": []}, {"at": True}, {"at": -1},
                       {"hidden": "false"}, {"focused": None},
                   ])]
        for activity in invalid:
            with self.subTest(activity=str(activity)[:100]):
                response = clients[0].post("/api/results", json={**payload, "activityLog": activity})
                self.assertEqual(response.status_code, 400)
        self.assertEqual(Result.objects.count(), 0)
        result = clients[0].post("/api/results", json=payload)
        self.assertEqual(result.status_code, 200)
        detail = clients[0].get(f"/api/results/{result.json()['id']}/review").json()
        self.assertIsNone(detail["activityLog"])
        self.assertIsNone(detail["activitySummary"])

    def test_simultaneous_retries_save_one_result(self):
        clients, payload = self.submission_fixture()
        barrier = Barrier(2)

        def submit(client):
            barrier.wait(timeout=10)
            response = client.post("/api/results", json=payload)
            return response.status_code, response.json()

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(submit, clients))
        self.assertEqual([status for status, _ in responses], [200, 200])
        self.assertEqual(responses[0][1]["id"], responses[1][1]["id"])
        conn = portal.get_db()
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM results").fetchone()[0], 1)
        conn.close()

    def test_busy_database_returns_retryable_response_and_releases_connections(self):
        clients, payload = self.submission_fixture()
        writer = portal.get_db()
        writer.execute("BEGIN IMMEDIATE")
        get_db = portal.get_db

        def short_timeout():
            conn = get_db()
            conn.execute("PRAGMA busy_timeout=10")
            return conn

        try:
            with patch.object(portal, "get_db", side_effect=short_timeout):
                response = clients[0].post("/api/results", json=payload)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers["Retry-After"], "1")
        finally:
            writer.close()
        self.assertEqual(clients[0].post("/api/results", json=payload).status_code, 200)

    def test_wal_and_request_database_cleanup(self):
        conn = portal.get_db()
        self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0], 30000)
        conn.close()
        def failed_request(request):
            connection = portal.get_db()
            connection.execute("BEGIN IMMEDIATE")
            return HttpResponse(status=400)

        PortalMiddleware(failed_request)(RequestFactory().get("/api/test-cleanup"))
        # Request teardown must roll back even if the route never called close().
        conn = portal.get_db()
        conn.execute("BEGIN IMMEDIATE")
        conn.close()

    def test_published_questions_are_randomized_for_students_within_parts(self):
        teacher = APIClient()
        self.create_teacher()
        self.assertEqual(teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"}).status_code, 200)
        templates = self.exam_payload()["questions"] + [
            {"part": 3, "type": "true_false", "text": "True statement", "correct": 0},
            {"part": 4, "type": "matching", "text": "CPU", "options": ["Screen", "Processes instructions"], "correct": 1},
        ]
        for activity_type in ("exam", "quiz"):
            with self.subTest(activity_type=activity_type):
                payload = self.exam_payload(activity_type=activity_type)
                payload["questions"] = [
                    {**question, "text": f"{question['text']} ({index + 1})"}
                    for question in templates for index in range(4)
                ]
                published = teacher.post("/api/exams", json=payload)
                self.assertEqual(published.status_code, 200)
                exam_id = published.json()["id"]
                saved = teacher.get(f"/api/exams/{exam_id}").json()["questions"]
                by_id = {question["id"]: question for question in saved}
                students = []
                for index in range(2):
                    roll_no = f"{activity_type}-{index}"
                    student = APIClient()
                    self.assertEqual(student.post("/api/students/signup", json=self.student_payload(roll_no)).status_code, 200)
                    self.assertEqual(student.post("/api/students/login", json={"idNumber": roll_no, "password": "student-pass"}).status_code, 200)
                    students.append(student)

                # Seed only the test's RNG so different orders are reproducible.
                with patch("portal.views.secrets.SystemRandom", return_value=Random(2026)):
                    responses = [student.get(f"/api/exams/{exam_id}/take") for student in students]
                self.assertTrue(all(response.status_code == 200 for response in responses))
                question_sets = [response.json()["questions"] for response in responses]
                orders = [[question["id"] for question in questions] for questions in question_sets]
                self.assertNotEqual(orders[0], orders[1])
                for student, questions, order in zip(students, question_sets, orders):
                    self.assertCountEqual(order, by_id)
                    self.assertNotEqual(order, list(by_id))
                    self.assertEqual([question["part"] for question in questions], [1] * 4 + [2] * 4 + [3] * 4 + [4] * 4)
                    for question in questions:
                        self.assertEqual(question, {key: by_id[question["id"]][key] for key in ("id", "part", "type", "text", "options")})
                    answers = {
                        question["id"]: by_id[question["id"]]["answerText" if question["type"] == "identification" else "correct"]
                        for question in questions
                    }
                    submitted = student.post("/api/results", json={"examId": exam_id, "answers": answers})
                    self.assertEqual(submitted.status_code, 200)
                    result = submitted.json()
                    expected = 16 if activity_type == "quiz" else 24
                    self.assertEqual((result["score"], result["total"]), (expected, expected))
                    review = teacher.get(f"/api/results/{result['id']}/review").json()["review"]
                    self.assertTrue(all(question["isCorrect"] for question in review))
                self.assertEqual(teacher.get(f"/api/exams/{exam_id}").json()["questions"], saved)

    def test_four_part_exam_create_edit_grade_and_review(self):
        teacher = APIClient()
        self.create_teacher()
        self.assertEqual(teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"}).status_code, 200)
        payload = self.exam_payload()
        payload["questions"] += [
            {"part": 3, "type": "true_false", "text": "The Earth revolves around the Sun.", "correct": 0},
            {"part": 3, "type": "true_false", "text": "A keyboard is an output device.", "correct": 1},
            {"part": 4, "type": "matching", "text": "CPU", "options": ["Screen", "Printer", "Disk", "Mouse", "Processes instructions"], "correct": 4},
            {"part": 4, "type": "matching", "text": "Monitor", "options": ["Displays images", "Produces printed copies"], "correct": 0},
        ]
        response = teacher.post("/api/exams", json=payload)
        self.assertEqual(response.status_code, 200, response.json())
        exam_id = response.json()["id"]
        saved = teacher.get(f"/api/exams/{exam_id}").json()
        self.assertEqual([q["part"] for q in saved["questions"]], [1, 2, 3, 3, 4, 4])
        self.assertEqual(saved["questions"][2]["options"], ["True", "False"])
        self.assertEqual(saved["questions"][4]["options"], payload["questions"][4]["options"])
        self.assertEqual(teacher.put(f"/api/exams/{exam_id}", json={**payload, "questions": saved["questions"]}).status_code, 200)
        self.assertEqual(self.client.post("/api/students/signup", json=self.student_payload()).status_code, 200)
        self.assertEqual(self.client.post("/api/students/login", json={"idNumber": "ID-001", "password": "student-pass"}).status_code, 200)
        questions = self.client.get(f"/api/exams/{exam_id}/take").json()["questions"]
        self.assertEqual(len(questions), 6)
        for q in questions:
            self.assertNotIn("correct", q)
            self.assertNotIn("answerText", q)
            self.assertNotIn("alternatives", q)
        answers_by_text = {q["text"]: q.get("answerText") if q.get("type") == "identification" else q["correct"] for q in payload["questions"]}
        answers_by_text["Monitor"] = 1
        answers = {q["id"]: answers_by_text[q["text"]] for q in questions}
        cpu_id = next(q["id"] for q in questions if q["text"] == "CPU")
        invalid = {**answers, cpu_id: 5}
        self.assertEqual(self.client.post("/api/results", json={"examId": exam_id, "answers": invalid}).status_code, 400)
        response = self.client.post("/api/results", json={"examId": exam_id, "answers": answers, "submissionId": "four-part"})
        self.assertEqual(response.status_code, 200, response.json())
        result = response.json()
        self.assertEqual((result["score"], result["total"]), (7, 8))
        self.assert_no_answer_details(result)
        own_review = self.client.get(f"/api/results/{result['id']}/review")
        self.assertEqual(own_review.status_code, 200)
        self.assertTrue(all("correct" in item for item in own_review.json()["review"]))
        review = teacher.get(f"/api/results/{result['id']}/review")
        self.assertEqual(review.status_code, 200)
        details = review.json()["review"]
        self.assertEqual(details[2]["type"], "true_false")
        self.assertEqual(details[4]["options"][4], "Processes instructions")
        self.assertFalse(details[5]["isCorrect"])
        admin = APIClient()
        admin.post("/api/admin/login", json={"username": "administrator", "password": "configured-test-password"})
        self.assertNotIn("rating_score", admin.get("/api/teachers").json()[0])
        self.assertEqual(admin.get(f"/api/results/{result['id']}/review").json()["review"], details)

    def test_quiz_questions_reopen_only_when_teacher_returns_submission(self):
        clients, payload = self.submission_fixture()
        conn = portal.get_db()
        conn.execute("UPDATE exams SET activity_type='quiz' WHERE id=?", (payload["examId"],))
        conn.commit()
        conn.close()
        result = clients[0].post("/api/results", json=payload).json()
        self.assert_no_answer_details(result)
        for index, client in enumerate(clients):
            self.assertEqual(client.get(f"/api/exams/{payload['examId']}/take").status_code, 403)
            review = client.get(f"/api/results/{result['id']}/review")
            self.assertEqual(review.status_code, 200)
            self.assertTrue(all("correct" in item for item in review.json()["review"]))
        anonymous = APIClient()
        unauthorized = anonymous.delete(f"/api/results/{result['id']}")
        self.assertEqual(unauthorized.status_code, 401)
        self.assertIn("staff session has expired", unauthorized.json()["error"])
        self.assertEqual(clients[0].get(f"/api/exams/{payload['examId']}/take").status_code, 403)
        teacher = APIClient()
        teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"})
        self.assertEqual(teacher.delete(f"/api/results/{result['id']}", json={"studentId": "ID-001"}).status_code, 200)
        self.assertEqual(clients[0].get(f"/api/exams/{payload['examId']}/take").status_code, 200)

    def test_exam_and_quiz_use_their_own_point_values_in_all_reviews(self):
        self.create_teacher()
        teacher = APIClient()
        teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"})
        self.client.post("/api/students/signup", json=self.student_payload())
        self.client.post("/api/students/login", json={"idNumber": "ID-001", "password": "student-pass"})
        for kind, points in (("exam", 2), ("quiz", 1)):
            with self.subTest(kind=kind):
                payload = self.exam_payload(activity_type=kind)
                payload["questions"] += [
                    {"type": "true_false", "text": "Statement", "correct": 0},
                    {"type": "matching", "text": "Match", "options": ["A", "B"], "correct": 1},
                ]
                exam_id = teacher.post("/api/exams", json=payload).json()["id"]
                take = self.client.get(f"/api/exams/{exam_id}/take").json()
                self.assertEqual(take["pointsPerQuestion"], points)
                questions = teacher.get(f"/api/exams/{exam_id}").json()["questions"]
                answers = {q["id"]: (q["answerText"] if q["type"] == "identification" else q["correct"]) for q in questions[:2]}
                receipt = self.client.post("/api/results", json={"examId": exam_id, "answers": answers, "pointsPerQuestion": 99, "activityType": "exam"}).json()
                self.assertEqual((receipt["score"], receipt["total"], receipt["percent"]), (2 * points, 4 if kind == "quiz" else 6, 50 if kind == "quiz" else 4 / 6 * 100))
                self.assertEqual(receipt["pointsPerQuestion"], points)
                for client in (self.client, teacher):
                    listed = client.get(f"/api/results?examId={exam_id}").json()[0]
                    self.assertEqual((listed["score"], listed["total"], listed["pointsPerQuestion"]), (2 * points, 4 if kind == "quiz" else 6, points))
                    review = client.get(f"/api/results/{receipt['id']}/review").json()
                    self.assertTrue(all(item["pointsPossible"] == (1 if kind == "quiz" or item["type"] in ("true_false", "matching") else 2) for item in review["review"]))
                    self.assertEqual(sum(item["pointsAwarded"] for item in review["review"]), receipt["score"])

    def test_question_type_migration_updates_active_and_returned_exam_scores_once(self):
        from importlib import import_module
        from django.db import connection
        from portal.models import SubmissionReturn
        self.create_teacher()
        teacher = APIClient()
        teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"})
        self.client.post("/api/students/signup", json=self.student_payload())
        self.client.post("/api/students/login", json={"idNumber": "ID-001", "password": "student-pass"})
        payload = self.exam_payload()
        payload["questions"] += [
            {"type": "true_false", "text": "Statement", "correct": 0},
            {"type": "matching", "text": "Match", "options": ["A", "B"], "correct": 1},
        ]
        exam_id = teacher.post("/api/exams", json=payload).json()["id"]
        questions = teacher.get(f"/api/exams/{exam_id}").json()["questions"]
        answers = {q["id"]: (q["answerText"] if q["type"] == "identification" else q["correct"]) for q in questions}
        answers[questions[-1]["id"]] = 0  # One incorrect matching answer.
        receipt = self.client.post("/api/results", json={"examId": exam_id, "answers": answers}).json()
        self.assertEqual((receipt["score"], receipt["total"]), (5, 6))
        Result.objects.filter(pk=receipt["id"]).update(score=6, total=8, percent=75)
        teacher.delete(f"/api/results/{receipt['id']}", json={"studentId": "ID-001"})
        fresh = self.client.post("/api/results", json={"examId": exam_id, "answers": answers, "submissionId": "new-weighted"}).json()
        Result.objects.filter(pk=fresh["id"]).update(score=6, total=8, percent=75)
        correct = import_module("portal.migrations.0014_question_type_points").correct_exam_scores
        for _ in range(2):
            with connection.schema_editor() as editor:
                correct(None, editor)
            result = Result.objects.get(pk=fresh["id"])
            saved = json.loads(SubmissionReturn.objects.get(result_id=receipt["id"]).snapshot)
            self.assertEqual((result.score, result.total), (5, 6))
            self.assertAlmostEqual(result.percent, 5 / 6 * 100)
            self.assertEqual((saved["score"], saved["total"]), (5, 6))
            self.assertEqual(json.loads(saved["answers_json"]), answers)
            self.assertEqual(json.loads(result.answers_json), answers)

    def test_quiz_score_migration_corrects_active_and_returned_scores_once(self):
        from importlib import import_module
        from django.db import connection
        from portal.models import Result, SubmissionReturn
        clients, payload = self.submission_fixture()
        teacher = APIClient()
        teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"})
        receipt = clients[0].post("/api/results", json=payload).json()
        with closing(portal.get_db()) as conn:
            conn.execute("UPDATE exams SET activity_type='quiz' WHERE id=?", (payload["examId"],))
            conn.execute("UPDATE results SET score=2, total=4, percent=50 WHERE id=?", (receipt["id"],))
            conn.commit()
        teacher.delete(f"/api/results/{receipt['id']}", json={"studentId": "ID-001"})
        active = clients[0].post("/api/results", json={**payload, "submissionId": "new-quiz"}).json()
        Result.objects.filter(pk=active["id"]).update(score=2, total=4, percent=50)
        exam_id = teacher.post("/api/exams", json=self.exam_payload()).json()["id"]
        exam_result = clients[0].post("/api/results", json={"examId": exam_id, "answers": {}}).json()
        Result.objects.filter(pk=exam_result["id"]).update(score=2, total=4, percent=50)
        correct = import_module("portal.migrations.0013_quiz_one_point").correct_quiz_scores
        for _ in range(2):
            with connection.schema_editor() as editor:
                correct(None, editor)
            result = Result.objects.get(pk=active["id"])
            self.assertEqual((result.score, result.total, result.percent), (1, 2, 50))
            original = json.loads(SubmissionReturn.objects.get(result_id=receipt["id"]).snapshot)
            self.assertEqual((original["score"], original["total"], original["percent"]), (1, 2, 50))
            unchanged = Result.objects.get(pk=exam_result["id"])
            self.assertEqual((unchanged.score, unchanged.total, unchanged.percent), (2, 4, 50))

    def test_return_preserves_answers_and_allows_one_new_submission(self):
        from portal.models import SubmissionReturn
        clients, payload = self.submission_fixture()
        teacher = APIClient()
        teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"})
        questions = teacher.get(f"/api/exams/{payload['examId']}").json()["questions"]
        payload["answers"] = {questions[0]["id"]: 1}
        original = clients[0].post("/api/results", json=payload).json()
        for verification in ({}, {"studentId": ""}, {"studentId": "WRONG"}, {"studentId": 123}, {"studentId": ["ID-001"]}):
            rejected = teacher.delete(f"/api/results/{original['id']}", json=verification)
            self.assertEqual(rejected.status_code, 400)
            self.assertEqual(rejected.json()["code"], "student_id_verification_failed")
            self.assertTrue(Result.objects.filter(pk=original["id"]).exists())
            self.assertEqual(SubmissionReturn.objects.count(), 0)
            self.assertEqual(clients[0].get(f"/api/exams/{payload['examId']}/take").status_code, 403)
        self.create_teacher(username="another")
        other = APIClient()
        other.post("/api/admin/login", json={"username": "another", "password": "teacher-pass"})
        self.assertEqual(other.delete(f"/api/results/{original['id']}").status_code, 403)
        self.assertEqual(SubmissionReturn.objects.count(), 0)
        self.assertEqual(teacher.delete(f"/api/results/{original['id']}", json={"studentId": "ID-001"}).status_code, 200)
        archived = SubmissionReturn.objects.get(result_id=original["id"])
        self.assertEqual(json.loads(json.loads(archived.snapshot)["answers_json"]), payload["answers"])
        reopened = clients[0].get(f"/api/exams/{payload['examId']}/take").json()
        self.assertEqual(reopened["returnedAttempt"]["answers"], payload["answers"])
        self.assertTrue(all("correct" not in item for item in reopened["questions"]))
        self.assertTrue(clients[0].get("/api/exams?studentView=1").json()[0]["returned"])
        self.assertEqual(clients[0].post("/api/results", json=payload).status_code, 409)
        fresh = {**payload, "submissionId": "new-attempt"}
        saved = clients[0].post("/api/results", json=fresh)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(clients[0].post("/api/results", json=fresh).json()["id"], saved.json()["id"])
        archived.refresh_from_db()
        self.assertEqual(archived.resubmitted_id, saved.json()["id"])
        self.assertEqual(teacher.delete(f"/api/results/{saved.json()['id']}", json={"studentId": "ID-001"}).status_code, 200)
        self.assertEqual(clients[0].post("/api/results", json=payload).status_code, 409)
        self.assertEqual(SubmissionReturn.objects.count(), 2)

    def test_modern_superadmin_dashboard_and_live_endpoint_require_superuser(self):
        clients, payload = self.submission_fixture()
        self.assertEqual(clients[0].get("/admin/live/").status_code, 302)
        teacher = APIClient()
        teacher.post("/api/admin/login", json={"username": "teacher1", "password": "teacher-pass"})
        self.assertEqual(teacher.get("/admin/live/").status_code, 302)
        admin = self.native_admin_client()
        dashboard = admin.get("/admin/")
        self.assertContainsText(dashboard, "Your campus.")
        self.assertContainsText(dashboard, "admin/aralhub.css")
        self.assertNotIn(b"Latest submissions", dashboard.content)
        self.assertNotIn(b' id="campusRecent"', dashboard.content)
        self.assertNotIn(b'/admin/portal/result/', dashboard.content)
        self.assertNotIn(b'/admin/portal/submissionreturn/', dashboard.content)
        self.assertNotIn(b'Returned assessments', dashboard.content)
        self.assertEqual(set(admin.get("/admin/live/").json()), {"students", "teachers", "assessments"})
        receipt = clients[0].post("/api/results", json=payload).json()
        live = admin.get("/admin/live/")
        self.assertNotIn("submissions", live.json())
        self.assertNotIn("returned", live.json())
        self.assertTrue(Result.objects.filter(pk=receipt["id"]).exists())
        self.assertNotIn("recent", live.json())
        self.assertIn("no-cache", live.headers["Cache-Control"])
        for asset in ("aralhub.css", "aralhub-dashboard.js"):
            response = admin.get("/static/admin/" + asset)
            self.assertEqual(response.status_code, 200)
            response.close()

    def test_new_question_types_reject_invalid_answer_keys(self):
        for question in [
            {"type": "true_false", "text": "Statement", "correct": 2},
            {"type": "matching", "text": "Prompt", "options": ["Only one"], "correct": 0},
            {"type": "matching", "text": "Prompt", "options": ["A", "B"], "correct": 2},
            {"type": "matching", "text": "Prompt", "options": ["A", ""], "correct": 0},
            {"type": "unsupported", "text": "Prompt"},
        ]:
            with self.subTest(question=question):
                normalized, error = portal._validate_and_normalize_questions([question])
                self.assertIsNone(normalized)
                self.assertTrue(error)

    def test_question_options_migration_preserves_existing_questions(self):
        conn = portal.get_db()
        conn.execute("ALTER TABLE questions DROP COLUMN options_json")
        conn.execute("INSERT INTO questions (id,exam_id,position,text,option_a,option_b,option_c,option_d,correct) VALUES ('legacy-q','legacy-exam',0,'Legacy question','A','B','C','D',1)")
        conn.commit()
        conn.close()
        portal_db.init_db()
        conn = portal.get_db()
        question = conn.execute("SELECT * FROM questions WHERE id='legacy-q'").fetchone()
        self.assertEqual(portal._question_options(question), ["A", "B", "C", "D"])
        self.assertEqual(portal._grade_and_review([question], {"legacy-q": 1})[:2], (2, 2))
        conn.close()

    def test_grade_status_uses_half_score_as_passing_threshold(self):
        self.assertEqual(portal._grade_status(49.99), "failed")
        self.assertEqual(portal._grade_status(50), "passed")
        self.assertEqual(portal._grade_status(100), "passed")


if __name__ == "__main__":
    unittest.main()
