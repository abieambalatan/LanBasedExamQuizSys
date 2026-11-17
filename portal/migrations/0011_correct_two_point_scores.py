from django.db import migrations


def correct_odd_scores(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """UPDATE results
               SET score = score * 2,
                   percent = (score * 200.0) / total
               WHERE total = 2 * (
                   SELECT COUNT(*) FROM questions
                   WHERE questions.exam_id = results.exam_id
               )
                 AND score % 2 = 1
                 AND score <= (
                   SELECT COUNT(*) FROM questions
                   WHERE questions.exam_id = results.exam_id
               )"""
        )


class Migration(migrations.Migration):
    dependencies = [("portal", "0010_two_points_per_question")]

    operations = [
        migrations.RunPython(correct_odd_scores, reverse_code=migrations.RunPython.noop),
    ]
