"""Exercise uploads, private file links, recipient scopes, and replacements."""

from io import BytesIO, StringIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import test_app
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import connection
from django.test import Client, override_settings
from portal.accounts import permanently_delete_account
from portal.models import ActivityFileSubmission, LectureClass, LectureMaterial, SchoolOption, Student, Teacher
from portal.school_options import sections_in_use


class LearningMaterialTests(unittest.TestCase):
    setUpClass = classmethod(test_app.ExamPortalTests.setUpClass.__func__)
    tearDownClass = classmethod(test_app.ExamPortalTests.tearDownClass.__func__)
    tearDown = test_app.ExamPortalTests.tearDown

    def setUp(self):
        test_app.ExamPortalTests.setUp(self)
        test_app.ExamPortalTests.create_teacher(self)
        self.teacher = Client(headers={"X-Portal-Role": "teacher"})
        self.assertEqual(self.teacher.post("/api/admin/login", {"username": "teacher1", "password": "teacher-pass"}, content_type="application/json").status_code, 200)
        self.student = self.student_client("ID-001")

    def student_client(self, roll_no, **extra):
        client = Client(headers={"X-Portal-Role": "student"})
        data = {**test_app.ExamPortalTests.student_payload(roll_no), **extra}
        response = client.post("/api/students/signup", data, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        response = client.post("/api/students/login", {"idNumber": roll_no, "password": "student-pass"}, content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        return client

    @staticmethod
    def document(name="lecture.pdf", contents=None):
        suffix = Path(name).suffix.lower()
        if contents is None:
            if suffix == ".pdf":
                contents = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n%%EOF"
            elif suffix in (".doc", ".ppt", ".xls"):
                contents = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512
            else:
                output = BytesIO()
                with ZipFile(output, "w") as archive:
                    archive.writestr("[Content_Types].xml", "<Types/>")
                    archive.writestr({".docx": "word/document.xml", ".pptx": "ppt/presentation.xml", ".xlsx": "xl/workbook.xml"}[suffix], "<document/>")
                contents = output.getvalue()
        return SimpleUploadedFile(name, contents, content_type="application/octet-stream")

    def publish(self, **extra):
        payload = {
            "title": "Week 1 lecture and activity", "subject": "Programming",
            "instructions": "Read the material and upload your completed activity.",
            "requiresSubmission": "true", "file": self.document(),
            "targetClasses": json.dumps([{"department": "BSIT", "yearLevel": "1st Year", "section": "A"}]),
            **extra,
        }
        return self.teacher.post("/api/learning/materials", payload)

    def publish_id(self, **extra):
        response = self.publish(**extra)
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()["id"]

    def submit(self, material_id, client=None, **extra):
        return (client or self.student).post(f"/api/learning/materials/{material_id}/submissions", {"file": self.document("activity.docx"), **extra})

    def test_every_requested_document_type_can_be_shared_and_opened(self):
        for suffix in ("pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx"):
            with self.subTest(suffix=suffix):
                material_id = self.publish_id(file=self.document("Lecture." + suffix.upper()))
                material = next(item for item in self.student.get("/api/learning/materials").json() if item["id"] == material_id)
                self.assertEqual(material["filename"], "Lecture." + suffix.upper())
                self.assertIsNone(material["mySubmission"])
                # Follow a real href without the AJAX role header. Both student
                # and teacher cookies can exist in the same browser.
                browser = Client()
                browser.cookies.update(self.teacher.cookies)
                browser.cookies.update(self.student.cookies)
                response = browser.get(material["openUrl"])
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response["Content-Disposition"].startswith("inline" if suffix == "pdf" else "attachment"))
                self.assertIn("no-store", response["Cache-Control"])
                self.assertTrue(b"".join(response.streaming_content))
                download = browser.get(material["downloadUrl"])
                self.assertTrue(download["Content-Disposition"].startswith("attachment"))
                download.close()

    def test_only_exact_class_recipients_can_list_open_and_submit(self):
        material_id = self.publish_id()
        teacher_item = self.teacher.get("/api/learning/materials").json()[0]
        for client in (
            self.student_client("ID-002", section="B"),
            self.student_client("ID-003", yearLevel="2nd Year"),
            self.student_client("ID-004", department="BSN"),
        ):
            self.assertEqual(client.get("/api/learning/materials").json(), [])
            self.assertEqual(client.get(teacher_item["openUrl"].replace("teacher", "student")).status_code, 404)
            self.assertEqual(self.submit(material_id, client).status_code, 404)
        self.assertEqual(Client().get(teacher_item["openUrl"]).status_code, 401)
        self.assertEqual(Client().post("/api/learning/materials", {"file": self.document()}).status_code, 403)
        self.assertEqual(self.student.post("/api/learning/materials", {"file": self.document()}).status_code, 403)
        self.assertEqual(ActivityFileSubmission.objects.count(), 0)

    def test_one_material_reaches_selected_classes_across_courses_and_years(self):
        targets = [
            {"department": "BSIT", "yearLevel": "1st Year", "section": "A"},
            {"department": "BSCRIM", "yearLevel": "2nd Year", "section": "B"},
            {"department": "BSN", "yearLevel": "3rd Year", "section": "C"},
        ]
        material_id = self.publish_id(targetClasses=json.dumps(targets))
        students = [self.student, self.student_client("CRIM-001", department="BSCRIM", yearLevel="2nd Year", section="B"), self.student_client("NURSE-001", department="BSN", yearLevel="3rd Year", section="C")]
        for student in students:
            materials = student.get("/api/learning/materials").json()
            self.assertEqual([item["id"] for item in materials], [material_id])
            response = student.get(materials[0]["openUrl"])
            self.assertEqual(response.status_code, 200)
            response.close()
            self.assertEqual(self.submit(material_id, student).status_code, 200)
        outsider = self.student_client("CRIM-002", department="BSCRIM", yearLevel="1st Year", section="B")
        self.assertEqual(outsider.get("/api/learning/materials").json(), [])
        self.assertEqual(self.submit(material_id, outsider).status_code, 404)
        teacher_material = self.teacher.get("/api/learning/materials").json()[0]
        self.assertCountEqual(teacher_material["targetClasses"], targets)
        self.assertEqual(teacher_material["submissionCount"], 3)
        self.assertEqual(LectureMaterial.objects.count(), 1)

    def test_submission_can_be_replaced_and_only_owner_and_teacher_read_it(self):
        material_id = self.publish_id()
        submitted = self.submit(material_id)
        self.assertEqual(submitted.status_code, 200, submitted.content)
        first = submitted.json()["submission"]
        old_path = ActivityFileSubmission.objects.get().file.path
        material = self.student.get("/api/learning/materials").json()[0]
        self.assertEqual(material["mySubmission"]["id"], first["id"])
        peer = self.student_client("ID-002")
        self.assertIsNone(peer.get("/api/learning/materials").json()[0]["mySubmission"])
        self.assertEqual(peer.get(first["openUrl"]).status_code, 404)
        self.assertEqual(peer.get(f"/api/learning/materials/{material_id}/submissions").status_code, 403)
        records = self.teacher.get(f"/api/learning/materials/{material_id}/submissions").json()
        self.assertEqual(records[0]["rollNo"], "ID-001")
        response = self.teacher.get(records[0]["openUrl"])
        self.assertEqual(response.status_code, 200)
        response.close()
        replacement = self.submit(material_id, file=self.document("replacement.xlsx"))
        self.assertEqual(replacement.status_code, 200, replacement.content)
        self.assertEqual(ActivityFileSubmission.objects.count(), 1)
        self.assertEqual(replacement.json()["submission"]["id"], first["id"])
        self.assertEqual(replacement.json()["submission"]["filename"], "replacement.xlsx")
        self.assertFalse(Path(old_path).exists())
        self.assertEqual(self.teacher.get("/api/learning/materials").json()[0]["submissionCount"], 1)

    def test_other_teachers_and_archived_accounts_cannot_access_files(self):
        material_id = self.publish_id()
        self.submit(material_id)
        test_app.ExamPortalTests.create_teacher(self, username="teacher2")
        other = Client(headers={"X-Portal-Role": "teacher"})
        other.post("/api/admin/login", {"username": "teacher2", "password": "teacher-pass"}, content_type="application/json")
        self.assertEqual(other.get("/api/learning/materials").json(), [])
        self.assertEqual(other.delete(f"/api/learning/materials/{material_id}").status_code, 404)
        self.assertEqual(other.get(f"/api/learning/materials/{material_id}/submissions").status_code, 404)
        record = self.teacher.get("/api/learning/materials").json()[0]
        self.assertEqual(other.get(record["openUrl"]).status_code, 404)
        Teacher.objects.filter(username="teacher1").update(deleted_at="2026-11-11T08:00:00")
        self.assertEqual(self.student.get("/api/learning/materials").json(), [])
        self.assertEqual(self.student.get(record["openUrl"].replace("teacher", "student")).status_code, 404)
        Teacher.objects.filter(username="teacher1").update(deleted_at=None)
        Student.objects.filter(roll_no="ID-001").update(deleted_at="2026-11-11T08:00:00")
        self.assertEqual(self.submit(material_id).status_code, 401)

    def test_invalid_empty_disguised_multiple_and_oversized_files_are_rejected(self):
        for name, contents in (("bad.exe", b"MZ"), ("bad.pdf", b"<script>bad</script>"), ("empty.pdf", b""), ("bad.docx", b"not a zip")):
            with self.subTest(name=name):
                response = self.publish(file=self.document(name, contents))
                self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(self.publish(file=[self.document(), self.document()]).status_code, 400)
        self.assertEqual(self.publish(file=self.document("bad.docx", self.document("good.xlsx").read())).status_code, 400)
        with override_settings(LEARNING_FILE_MAX_BYTES=16):
            self.assertEqual(self.publish().status_code, 400)
        self.assertEqual(LectureMaterial.objects.count(), 0)
        self.assertEqual(list(Path(settings.MEDIA_ROOT).rglob("*.*")), [])

    def test_reading_material_without_submission_request_rejects_student_upload(self):
        material_id = self.publish_id(requiresSubmission="false")
        response = self.submit(material_id)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(ActivityFileSubmission.objects.count(), 0)

    def test_delete_cleans_up_material_and_submission_files(self):
        material_id = self.publish_id()
        self.submit(material_id)
        paths = [LectureMaterial.objects.get().file.path, ActivityFileSubmission.objects.get().file.path]
        response = self.teacher.delete(f"/api/learning/materials/{material_id}")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(LectureMaterial.objects.exists())
        self.assertFalse(LectureClass.objects.exists())
        self.assertFalse(ActivityFileSubmission.objects.exists())
        self.assertTrue(all(not Path(path).exists() for path in paths))

    def test_failed_database_write_removes_new_file_and_keeps_old_submission(self):
        material_id = self.publish_id()
        self.submit(material_id)
        before = {path for path in Path(settings.MEDIA_ROOT).rglob("*") if path.is_file()}
        with patch.object(ActivityFileSubmission, "save", side_effect=RuntimeError("database write failed")):
            with self.assertRaises(RuntimeError):
                self.submit(material_id)
        self.assertEqual({path for path in Path(settings.MEDIA_ROOT).rglob("*") if path.is_file()}, before)
        self.assertEqual(ActivityFileSubmission.objects.get().filename, "activity.docx")
        with patch.object(LectureClass.objects, "bulk_create", side_effect=RuntimeError("database write failed")):
            with self.assertRaises(RuntimeError):
                self.publish()
        self.assertEqual({path for path in Path(settings.MEDIA_ROOT).rglob("*") if path.is_file()}, before)
        self.assertEqual(LectureMaterial.objects.count(), 1)

    def test_permanent_account_deletion_cleans_files_and_preserves_other_records(self):
        material_id = self.publish_id()
        self.submit(material_id)
        old_path = ActivityFileSubmission.objects.get().file.path
        permanently_delete_account("student", Student.objects.get(roll_no="ID-001").pk)
        self.assertFalse(Path(old_path).exists())
        self.assertTrue(LectureMaterial.objects.exists())
        material_path = LectureMaterial.objects.get().file.path
        permanently_delete_account("teacher", Teacher.objects.get(username="teacher1").pk)
        self.assertFalse(Path(material_path).exists())
        self.assertFalse(LectureMaterial.objects.exists())

    def test_locked_old_download_does_not_remove_committed_replacement(self):
        material_id = self.publish_id()
        self.submit(material_id)
        original = ActivityFileSubmission.objects.get()
        old_path = original.file.path
        with self.assertLogs(level="ERROR"), patch.object(original.file.storage, "delete", side_effect=PermissionError("File is being downloaded")):
            response = self.submit(material_id, file=self.document("updated.pdf"))
        self.assertEqual(response.status_code, 200, response.content)
        saved = ActivityFileSubmission.objects.get()
        self.assertEqual(saved.filename, "updated.pdf")
        self.assertTrue(Path(saved.file.path).is_file())
        self.assertTrue(Path(old_path).is_file())

    def test_document_post_requires_csrf_and_sections_remain_protected(self):
        strict = Client(enforce_csrf_checks=True, headers={"X-Portal-Role": "teacher"})
        strict.cookies.update(self.teacher.cookies)
        response = strict.post("/api/learning/materials", {"file": self.document()})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "csrf_failed")
        token = strict.get("/api/csrf").json()["csrfToken"]
        self.teacher = strict
        self.publish_id(csrfmiddlewaretoken=token, targetClasses=json.dumps([{"department": "BSIT", "yearLevel": "2nd Year", "section": "F"}]))
        self.assertEqual(sections_in_use("BSIT", ["E", "F"], "2nd Year"), ["F"])

    def test_department_rename_updates_lecture_recipients(self):
        self.publish_id()
        client = test_app.ExamPortalTests.native_admin_client(self)
        option = SchoolOption.objects.get(category="department", value="BSIT")
        response = client.post(f"/admin/portal/schooloption/{option.pk}/change/", {"value": "BSICT", "section_count": "6", "position": str(option.position), "_save": "Save"})
        self.assertEqual(response.status_code, 302, response.content)
        self.assertEqual(LectureClass.objects.get().department, "BSICT")
        self.assertEqual(len(self.student.get("/api/learning/materials").json()), 1)

    def test_replaying_material_migration_preserves_metadata_and_files(self):
        material_id = self.publish_id()
        self.submit(material_id)
        before = (LectureMaterial.objects.get().file.name, ActivityFileSubmission.objects.get().file.name)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM django_migrations WHERE app='portal' AND name>='0015_lecture_materials'")
        call_command("migrate", interactive=False, verbosity=0, stdout=StringIO())
        self.assertEqual((LectureMaterial.objects.get().file.name, ActivityFileSubmission.objects.get().file.name), before)
        self.assertTrue(Path(LectureMaterial.objects.get().file.path).is_file())
        self.assertTrue(Path(ActivityFileSubmission.objects.get().file.path).is_file())
