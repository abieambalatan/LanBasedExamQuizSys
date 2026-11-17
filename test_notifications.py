"""Verify activity submissions continue to work without teacher notifications."""

import unittest

from django.db import connection
import test_learning
from portal.models import ActivityFileSubmission


class ActivitySubmissionWithoutNotificationsTests(unittest.TestCase):
    setUpClass = classmethod(test_learning.LearningMaterialTests.setUpClass.__func__)
    tearDownClass = classmethod(test_learning.LearningMaterialTests.tearDownClass.__func__)
    setUp = test_learning.LearningMaterialTests.setUp
    tearDown = test_learning.LearningMaterialTests.tearDown
    student_client = test_learning.LearningMaterialTests.student_client
    document = staticmethod(test_learning.LearningMaterialTests.document)
    publish = test_learning.LearningMaterialTests.publish
    publish_id = test_learning.LearningMaterialTests.publish_id
    submit = test_learning.LearningMaterialTests.submit

    def test_student_upload_and_replacement_work_without_notification_records(self):
        material_id = self.publish_id()
        first = self.submit(material_id)
        self.assertEqual(first.status_code, 200, first.content)
        replacement = self.submit(material_id, file=self.document("revised.docx"))
        self.assertEqual(replacement.status_code, 200, replacement.content)
        self.assertEqual(ActivityFileSubmission.objects.filter(material_id=material_id).count(), 1)
        self.assertEqual(ActivityFileSubmission.objects.get(material_id=material_id).filename, "revised.docx")

    def test_teacher_notification_api_is_removed(self):
        for path in (
            "/api/notifications",
            "/api/notifications/read-all",
            "/api/notifications/notification-id/read",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.teacher.get(path).status_code, 404)

    def test_notification_table_is_removed_by_migrations(self):
        self.assertNotIn(
            "portal_activitysubmissionnotification",
            connection.introspection.table_names(),
        )
