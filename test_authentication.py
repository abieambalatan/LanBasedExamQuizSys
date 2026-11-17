"""Shared sign-in, protected dashboards, and server-side role boundaries."""

import json
import unittest

import test_app
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from portal.models import Student, Teacher
from portal.security import generate_password_hash


class SharedLoginTests(unittest.TestCase):
    setUpClass = classmethod(test_app.ExamPortalTests.setUpClass.__func__)
    tearDownClass = classmethod(test_app.ExamPortalTests.tearDownClass.__func__)
    tearDown = test_app.ExamPortalTests.tearDown

    def setUp(self):
        test_app.ExamPortalTests.setUp(self)
        test_app.ExamPortalTests.create_teacher(self)
        self.client.post("/api/students/signup", json=test_app.ExamPortalTests.student_payload())

    def login(self, client=None, **extra):
        client = client or self.client
        return client.post("/api/auth/login", data=json.dumps({"username": "teacher1", "password": "teacher-pass", **extra}), content_type="application/json")

    def test_one_login_detects_teacher_and_student_without_role_selection(self):
        teacher = Client()
        response = self.login(teacher)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()["role"], response.json()["redirect"]), ("teacher", "/teacher"))
        self.assertIn(settings.SESSION_COOKIE_NAME + "_teacher", response.cookies)
        self.assertIn("materials.manage", response.json()["permissions"])
        self.assertNotIn("notifications.read", response.json()["permissions"])
        self.assertNotIn("password", json.dumps(response.json()))
        student = Client()
        response = self.login(student, username="ID-001", password="student-pass")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual((response.json()["role"], response.json()["redirect"]), ("student", "/student"))
        self.assertIn(settings.SESSION_COOKIE_NAME + "_student", response.cookies)
        self.assertIn("activities.submit", response.json()["permissions"])
        self.assertNotIn("materials.manage", response.json()["permissions"])

    def test_shared_entry_and_old_sign_in_addresses(self):
        page = self.client.get("/login")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"renderPortalLogin()", page.content)
        self.assertEqual(page["Cache-Control"], "no-store")
        for address in ("/administrator", "/administrator.html", "/admin/login/"):
            response = self.client.get(address)
            self.assertEqual((response.status_code, response["Location"]), (302, "/login"))

    def test_dashboards_require_authenticated_roles_and_bootstrap_without_passwords(self):
        for path in ("/student", "/teacher"):
            response = self.client.get(path)
            self.assertEqual((response.status_code, response["Location"]), (302, "/login"))
        teacher = Client()
        self.login(teacher)
        response = teacher.get("/teacher")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"role": "teacher"', response.content)
        self.assertNotIn(b"teacher-pass", response.content)
        self.assertEqual(teacher.get("/student").status_code, 302)
        student = Client()
        self.login(student, username="ID-001", password="student-pass")
        response = student.get("/student")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'"role": "student"', response.content)
        self.assertNotIn(b"student-pass", response.content)
        self.assertEqual(student.get("/teacher").status_code, 302)

    def test_student_cannot_select_teacher_role_or_get_teacher_permissions(self):
        client = Client(headers={"X-Portal-Role": "teacher"})
        response = self.login(client, username="ID-001", password="student-pass", role="teacher", permissions=["materials.manage"])
        self.assertEqual(response.json()["role"], "student")
        self.assertFalse(response.cookies.get(settings.SESSION_COOKIE_NAME + "_teacher").value)
        # Even placing a signed student cookie in the teacher-cookie slot must
        # not change the identity inside it or grant teacher endpoints.
        client.cookies[settings.SESSION_COOKIE_NAME + "_teacher"] = client.cookies[settings.SESSION_COOKIE_NAME + "_student"].value
        session = client.get("/api/auth/session").json()
        self.assertEqual(session["role"], "student")
        self.assertNotIn("assessments.manage", session["permissions"])
        self.assertEqual(client.post("/api/learning/materials", {}).status_code, 403)
        self.assertIn(client.post("/api/exams", {}, content_type="application/json").status_code, (401, 403))
        self.assertEqual(client.get("/api/teachers").status_code, 403)
        self.assertEqual(client.get("/api/students/managed").status_code, 403)
        self.assertEqual(client.get("/admin/").status_code, 302)

    def test_teacher_cannot_get_superadmin_actions_or_submit_as_student(self):
        client = Client(headers={"X-Portal-Role": "teacher"})
        self.login(client, role="admin")
        self.assertEqual(client.get("/api/teachers").status_code, 403)
        self.assertEqual(client.get("/admin/").status_code, 302)
        self.assertEqual(client.post("/api/results", {}, content_type="application/json").status_code, 401)
        self.assertEqual(client.post("/api/learning/materials/missing/submissions", {}).status_code, 401)

    def test_superadmin_uses_same_login_and_requires_native_superuser(self):
        client = Client()
        response = self.login(client, username="administrator", password="configured-test-password")
        self.assertEqual((response.status_code, response.json()["role"], response.json()["redirect"]), (200, "admin", "/admin/"))
        self.assertEqual(client.get("/admin/").status_code, 200)
        get_user_model().objects.create_user(username="ordinary-staff", password="staff-pass", is_staff=True)
        self.assertEqual(self.login(Client(), username="ordinary-staff", password="staff-pass").status_code, 401)

    def test_incorrect_empty_and_non_text_credentials_do_not_create_session(self):
        for credentials in ({"password": "wrong"}, {"username": "missing"}, {"username": []}, {"password": {}}):
            client = Client()
            response = self.login(client, **credentials)
            self.assertIn(response.status_code, (400, 401))
            self.assertNotIn(settings.SESSION_COOKIE_NAME + "_teacher", response.cookies)
        for username in ("missing", "teacher1", "ID-001"):
            response = self.login(Client(), username=username, password="wrong")
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["error"], "Incorrect username, student ID, or password.")

    def test_ambiguous_credentials_never_choose_a_more_privileged_account(self):
        Student.objects.filter(roll_no="ID-001").update(roll_no="teacher1", password_hash=generate_password_hash("teacher-pass"))
        response = self.login(Client())
        self.assertEqual((response.status_code, response.json()["code"]), (409, "ambiguous_credentials"))
        self.assertNotIn(settings.SESSION_COOKIE_NAME + "_teacher", response.cookies)
        # An overlapping identifier with distinct passwords can still resolve
        # the correct account, without a role picker or username precedence.
        Student.objects.filter(roll_no="teacher1").update(password_hash=generate_password_hash("student-pass"))
        self.assertEqual(self.login(Client(), password="student-pass").json()["role"], "student")
        self.assertEqual(self.login(Client()).json()["role"], "teacher")

    def test_archived_or_deleted_accounts_lose_access_on_refresh(self):
        client = Client(headers={"X-Portal-Role": "teacher"})
        self.login(client)
        Teacher.objects.filter(username="teacher1").update(deleted_at="2026-11-11T08:00:00")
        self.assertEqual(client.get("/api/auth/session").status_code, 401)
        self.assertEqual(client.get("/teacher").status_code, 302)
        self.assertEqual(self.login(Client()).status_code, 401)
        student = Client(headers={"X-Portal-Role": "student"})
        self.login(student, username="ID-001", password="student-pass")
        Student.objects.filter(roll_no="ID-001").update(deleted_at="2026-11-11T08:00:00")
        self.assertEqual(student.get("/api/auth/session").status_code, 401)
        self.assertEqual(student.get("/student").status_code, 302)

    def test_shared_login_and_logout_require_csrf_and_rotate_token(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(self.login(client).status_code, 403)
        client.get("/login")
        original_token = client.cookies["csrftoken"].value
        response = client.post("/api/auth/login", {"username": "teacher1", "password": "teacher-pass"}, content_type="application/json", HTTP_X_CSRFTOKEN=original_token)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotEqual(client.cookies["csrftoken"].value, original_token)
        self.assertEqual(client.post("/api/logout", HTTP_X_PORTAL_ROLE="teacher").status_code, 403)
        token = client.get("/api/csrf", HTTP_X_PORTAL_ROLE="teacher").json()["csrfToken"]
        self.assertEqual(client.post("/api/logout", HTTP_X_PORTAL_ROLE="teacher", HTTP_X_CSRFTOKEN=token).status_code, 200)
        self.assertEqual(client.get("/teacher").status_code, 302)

    def test_session_metadata_refreshes_student_class_from_database(self):
        client = Client(headers={"X-Portal-Role": "student"})
        self.login(client, username="ID-001", password="student-pass")
        Student.objects.filter(roll_no="ID-001").update(section="B", year_level="2nd Year")
        account = client.get("/api/auth/session").json()["account"]
        self.assertEqual((account["section"], account["yearLevel"]), ("B", "2nd Year"))

    def test_shared_sign_in_replaces_teacher_or_admin_identity_with_student(self):
        client = Client()
        self.login(client)
        self.assertEqual(client.get("/teacher").status_code, 200)
        self.login(client, username="ID-001", password="student-pass")
        self.assertFalse(client.cookies[settings.SESSION_COOKIE_NAME + "_teacher"].value)
        self.assertEqual(client.get("/teacher").status_code, 302)
        self.assertEqual(client.get("/student").status_code, 200)
        self.login(client, username="administrator", password="configured-test-password")
        self.assertEqual(client.get("/admin/").status_code, 200)
        self.assertEqual(client.get("/student").status_code, 302)
        self.login(client, username="ID-001", password="student-pass")
        self.assertFalse(client.cookies[settings.SESSION_COOKIE_NAME].value)
        self.assertEqual(client.get("/admin/").status_code, 302)
        self.assertEqual(client.get("/api/teachers", HTTP_X_PORTAL_ROLE="teacher").status_code, 403)
