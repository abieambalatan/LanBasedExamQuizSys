"""Persist attempt activity immediately and expose it only to authorized staff."""

import json
import time
import uuid

from django.conf import settings
from django.core.exceptions import BadRequest

from .assessment_activity import activity_summary, merge_activity_logs, normalize_activity_log
from .db import get_db
from .http import json_response, read_json
from .targets import class_can_access


def save_activity(request, exam_id):
    from .views import current_student_account
    student = current_student_account(request)
    if not student:
        return json_response({"error": "Student sign in required."}, status=401)
    data = read_json(request)
    key = data.get("submissionId")
    log = normalize_activity_log(data.get("activityLog"))
    if (not isinstance(key, str) or not key or len(key) > 128 or log is None
            or type(data.get("pageHidden")) is not bool or type(data.get("windowFocused")) is not bool):
        raise BadRequest("Invalid assessment monitoring update.")
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
            conn.execute("SELECT id FROM students WHERE id=? FOR UPDATE", (student["studentId"],)).fetchone()
        exam = conn.execute("SELECT * FROM exams WHERE id=? AND (created_by='' OR EXISTS (SELECT 1 FROM teachers t WHERE t.username=exams.created_by AND t.deleted_at IS NULL))", (exam_id,)).fetchone()
        if not exam:
            return json_response({"error": "Exam not found."}, status=404)
        if not class_can_access(conn, exam_id, student["department"], student["yearLevel"], student["section"]):
            return json_response({"error": "Assessment is not assigned to your class."}, status=403)
        result = conn.execute("SELECT submission_key FROM results WHERE exam_id=? AND roll_no=?", (exam_id, student["rollNo"])).fetchone()
        if result:
            if result["submission_key"] == key:
                return json_response({"ok": True, "submitted": True})
            return json_response({"error": "This assessment has already been submitted."}, status=409)
        returns = conn.execute("SELECT snapshot FROM portal_submissionreturn WHERE exam_id=? AND roll_no=?", (exam_id, student["rollNo"])).fetchall()
        if any(json.loads(row["snapshot"]).get("submission_key") == key for row in returns):
            return json_response({"error": "This attempt was returned. Continue using a fresh attempt."}, status=409)
        old = conn.execute("SELECT * FROM portal_assessmentactivity WHERE exam_id=? AND student_id=? AND submission_key=?", (exam_id, student["studentId"], key)).fetchone()
        merged = merge_activity_logs(json.loads(old["activity_log_json"]) if old else None, log)
        # A conflicting browser copy must not silently replace accepted evidence.
        if merged["events"] != log["events"] and len(log["events"]) >= len(merged["events"]):
            return json_response({"error": "Another copy of this attempt has different activity. Keep only one assessment tab open."}, status=409)
        if len(log["events"]) < len(merged["events"]):
            return json_response({"ok": True, "eventCount": len(merged["events"]), "receivedAt": int(old["received_at"] * 1000)})
        now = time.time()
        if old:
            conn.execute("UPDATE portal_assessmentactivity SET activity_log_json=?,received_at=?,page_hidden=?,window_focused=? WHERE id=?", (json.dumps(merged), now, data["pageHidden"], data["windowFocused"], old["id"]))
        else:
            conn.execute("""INSERT INTO portal_assessmentactivity
                (id,exam_id,student_id,submission_key,activity_log_json,created_at,received_at,page_hidden,window_focused,result_id)
                VALUES (?,?,?,?,?,?,?,?,?,?)""", (uuid.uuid4().hex, exam_id, student["studentId"], key, json.dumps(merged), now, now, data["pageHidden"], data["windowFocused"], ""))
        conn.commit()
        return json_response({"ok": True, "eventCount": len(merged["events"]), "receivedAt": int(now * 1000)})
    finally:
        conn.close()


def _serialize(row, *, detail=False):
    status = "submitted" if row["result_id"] else (
        "not_reporting" if time.time() - row["received_at"] > 30 else
        "hidden" if row["page_hidden"] else "unfocused" if not row["window_focused"] else "on_exam")
    out = {"id": row["id"], "examId": row["exam_id"], "name": row["name"], "rollNo": row["roll_no"],
           "department": row["department"], "yearLevel": row["year_level"], "section": row["section"],
           "receivedAt": int(row["received_at"] * 1000), "status": status,
           "activitySummary": activity_summary(row["activity_log_json"])}
    if detail:
        out["activityLog"] = json.loads(row["activity_log_json"])
    return out


def get_activity(request, exam_id, activity_id=None):
    from .views import current_admin_account
    account = current_admin_account(request)
    if not account:
        return json_response({"error": "Staff sign in required."}, status=401)
    conn = get_db()
    try:
        exam = conn.execute("SELECT created_by FROM exams WHERE id=?", (exam_id,)).fetchone()
        if not exam:
            return json_response({"error": "Exam not found."}, status=404)
        if account["role"] == "teacher" and exam["created_by"] != account["username"]:
            return json_response({"error": "You can only monitor your own assessments."}, status=403)
        query = """SELECT a.*,s.name,s.roll_no,s.department,s.year_level,s.section
            FROM portal_assessmentactivity a JOIN students s ON s.id=a.student_id WHERE a.exam_id=?"""
        params = [exam_id]
        if activity_id:
            query += " AND a.id=?"
            params.append(activity_id)
        rows = conn.execute(query + " ORDER BY a.received_at DESC,a.id", params).fetchall()
        if activity_id:
            return json_response(_serialize(rows[0], detail=True)) if rows else json_response({"error": "Attempt not found."}, status=404)
        return json_response([_serialize(row) for row in rows])
    finally:
        conn.close()
