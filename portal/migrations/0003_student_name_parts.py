"""Add structured student names while preserving existing names and accounts."""

from django.db import migrations, models


def add_name_columns(apps, schema_editor):
    from portal.db import ensure_student_name_columns, get_db

    conn = get_db()
    try:
        ensure_student_name_columns(conn)
        conn.commit()
    finally:
        conn.close()


class Migration(migrations.Migration):
    dependencies = [("portal", "0002_initial")]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(add_name_columns, reverse_code=migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="student", name="first_name",
                    field=models.CharField(max_length=255, blank=True, default=""),
                ),
                migrations.AddField(
                    model_name="student", name="last_name",
                    field=models.CharField(max_length=255, blank=True, default=""),
                ),
                migrations.AddField(
                    model_name="student", name="middle_initial",
                    field=models.CharField(max_length=1, blank=True, default=""),
                ),
            ],
        ),
    ]
