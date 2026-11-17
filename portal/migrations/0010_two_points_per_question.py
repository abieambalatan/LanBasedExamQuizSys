from django.db import migrations


def scale_existing_scores(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """UPDATE results
               SET score = score * 2, total = total * 2
               WHERE total = (
                   SELECT COUNT(*) FROM questions
                   WHERE questions.exam_id = results.exam_id
               )"""
        )


class Migration(migrations.Migration):
    dependencies = [("portal", "0009_department_year_sections")]

    operations = [
        migrations.RunPython(scale_existing_scores, reverse_code=migrations.RunPython.noop),
    ]
