"""Convert saved two-point quiz scores without regrading submitted answers."""

import json
from django.db import migrations


def correct_quiz_scores(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """UPDATE results SET score=score/2, total=total/2
               WHERE exam_id IN (SELECT id FROM exams WHERE activity_type='quiz')
                 AND total>0 AND score % 2=0
                 AND total=2*(SELECT COUNT(*) FROM questions WHERE questions.exam_id=results.exam_id)"""
        )
        cursor.execute(
            """SELECT a.id, a.snapshot, COUNT(q.id)
               FROM portal_submissionreturn a
               JOIN exams e ON e.id=a.exam_id AND e.activity_type='quiz'
               LEFT JOIN questions q ON q.exam_id=e.id
               GROUP BY a.id, a.snapshot"""
        )
        for return_id, raw, question_count in cursor.fetchall():
            saved = json.loads(raw)
            score, total = saved.get("score", 0), saved.get("total", 0)
            if question_count and total == question_count * 2 and score % 2 == 0:
                saved.update(score=score // 2, total=total // 2)
                cursor.execute(
                    "UPDATE portal_submissionreturn SET snapshot=%s WHERE id=%s",
                    [json.dumps(saved), return_id],
                )


class Migration(migrations.Migration):
    dependencies = [("portal", "0012_submissionreturn")]
    operations = [migrations.RunPython(correct_quiz_scores, migrations.RunPython.noop)]
