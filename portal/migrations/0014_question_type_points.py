"""Adjust original two-point exam totals while preserving submitted answers."""
import json

from django.db import migrations


def correct_exam_scores(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT id FROM exams WHERE activity_type='exam'")
        for (exam_id,) in cursor.fetchall():
            cursor.execute("SELECT id, type, correct FROM questions WHERE exam_id=%s", [exam_id])
            questions = cursor.fetchall()
            lightweight = [(qid, kind, correct) for qid, kind, correct in questions
                           if kind in ('true_false', 'matching')]
            if not lightweight:
                continue
            ids = {q[0] for q in questions}

            def adjusted(saved):
                if saved.get('total') != 2 * len(questions) or saved.get('score', 0) % 2:
                    return None
                answers = json.loads(saved['answers_json'])
                # Edited assessments cannot safely reconstruct the original grading.
                if not isinstance(answers, dict) or not set(answers).issubset(ids):
                    return None
                deducted = 0
                for qid, kind, correct in lightweight:
                    chosen = answers.get(qid)
                    if chosen in (None, ''):
                        continue
                    if kind == 'true_false' and isinstance(chosen, bool):
                        chosen = 0 if chosen else 1
                    elif kind == 'true_false' and str(chosen).strip().upper() in ('TRUE', 'FALSE'):
                        chosen = 0 if str(chosen).strip().upper() == 'TRUE' else 1
                    elif isinstance(chosen, (int, str)) and not isinstance(chosen, bool):
                        try:
                            chosen = int(chosen)
                        except ValueError:
                            return None
                    else:
                        return None
                    deducted += chosen == correct
                score = saved['score'] - deducted
                total = saved['total'] - len(lightweight)
                if not 0 <= score <= total:
                    return None
                return dict(score=score, total=total, percent=score / total * 100)

            cursor.execute("SELECT id, score, total, answers_json FROM results WHERE exam_id=%s", [exam_id])
            for result_id, score, total, answers_json in cursor.fetchall():
                values = adjusted(dict(score=score, total=total, answers_json=answers_json))
                if values:
                    cursor.execute("UPDATE results SET score=%s,total=%s,percent=%s WHERE id=%s",
                                   [values['score'], values['total'], values['percent'], result_id])
            cursor.execute("SELECT id, snapshot FROM portal_submissionreturn WHERE exam_id=%s", [exam_id])
            for return_id, raw in cursor.fetchall():
                saved = json.loads(raw)
                values = adjusted(saved)
                if values:
                    saved.update(values)
                    cursor.execute("UPDATE portal_submissionreturn SET snapshot=%s WHERE id=%s",
                                   [json.dumps(saved), return_id])


class Migration(migrations.Migration):
    dependencies = [('portal', '0013_quiz_one_point')]
    operations = [migrations.RunPython(correct_exam_scores, migrations.RunPython.noop)]
