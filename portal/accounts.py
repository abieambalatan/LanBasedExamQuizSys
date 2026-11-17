"""Permanently remove accounts without handing their historical work to new users."""

import json
import uuid

from django.db import connection, transaction

from .models import ActivityFileSubmission, LectureMaterial, Student, Teacher
from .constants import RETIRED_ACCOUNT_PREFIX
from .learning_uploads import delete_files_after_commit


RETIRED_PREFIX = RETIRED_ACCOUNT_PREFIX


@transaction.atomic
def permanently_delete_account(kind, account_id):
    model = {"student": Student, "teacher": Teacher}[kind]
    account = model.objects.select_for_update().filter(pk=account_id).first()
    if account is None:
        return False
    if kind == "teacher":
        from .learning import delete_material_records
        delete_material_records(LectureMaterial.objects.filter(teacher_id=account_id))
    else:
        submissions = ActivityFileSubmission.objects.filter(student_id=account_id)
        files = [(item.file.storage, item.file.name) for item in submissions]
        submissions.delete()
        delete_files_after_commit(files)
    with connection.cursor() as cursor:
        if kind == "teacher":
            retired = RETIRED_PREFIX + uuid.uuid4().hex
            cursor.execute("UPDATE exams SET created_by=%s WHERE created_by=%s", [retired, account.username])
            cursor.execute("UPDATE results SET teacher_username=%s WHERE teacher_username=%s", [retired, account.username])
            cursor.execute("UPDATE students SET teacher_username='' WHERE teacher_username=%s", [account.username])
            cursor.execute("DELETE FROM teacher_departments WHERE teacher_username=%s", [account.username])
            cursor.execute("SELECT id,snapshot FROM portal_submissionreturn")
            for return_id, raw in cursor.fetchall():
                saved = json.loads(raw)
                if saved.get("teacher_username") == account.username:
                    saved["teacher_username"] = retired
                    cursor.execute("UPDATE portal_submissionreturn SET snapshot=%s WHERE id=%s", [json.dumps(saved), return_id])
        else:
            cursor.execute("DELETE FROM portal_assessmentactivity WHERE student_id=%s", [account_id])
            cursor.execute("DELETE FROM results WHERE roll_no=%s", [account.roll_no])
            cursor.execute("DELETE FROM portal_submissionreturn WHERE roll_no=%s", [account.roll_no])
        cursor.execute(f"DELETE FROM {model._meta.db_table} WHERE id=%s", [account_id])
    return True
