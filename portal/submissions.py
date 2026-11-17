"""Return a saved assessment atomically, retaining its original evidence."""

import json
import uuid
from django.conf import settings
from .db import get_db
from .models import timestamp


def return_submission(result_id, username, *, student_id, teacher_only=False):
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
            # Match submission lock ordering so return and submit cannot race.
            conn.execute(
                "SELECT id FROM students WHERE roll_no=(SELECT roll_no FROM results WHERE id=?) FOR UPDATE",
                (result_id,),
            ).fetchall()
        result = conn.execute("SELECT * FROM results WHERE id=?", (result_id,)).fetchone()
        if not result:
            return None
        if teacher_only and result["teacher_username"] != username:
            raise PermissionError("You can only return submissions for your own assessments.")
        if not isinstance(student_id, str) or not student_id.strip():
            raise ValueError("Enter the student's ID number to return this submission.")
        if student_id.strip() != result["roll_no"]:
            raise ValueError("Student ID does not match this submission. The assessment has not been returned.")
        conn.execute(
            """INSERT INTO portal_submissionreturn
               (id, result_id, exam_id, roll_no, snapshot, returned_by, returned_at, resubmitted_id)
               VALUES (?,?,?,?,?,?,?,?)""",
            ("ret_" + uuid.uuid4().hex, result_id, result["exam_id"], result["roll_no"],
             json.dumps(dict(result)), username, timestamp(), ""),
        )
        conn.execute("DELETE FROM results WHERE id=?", (result_id,))
        conn.commit()
        return dict(result)
    finally:
        conn.close()
