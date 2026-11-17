from django.db import migrations, models


def add_student_archive_column(apps, schema_editor):
    from portal.db import ensure_student_archive_column, get_db

    conn = get_db()
    try:
        ensure_student_archive_column(conn)
        conn.commit()
    finally:
        conn.close()


class Migration(migrations.Migration):
    dependencies = [("portal", "0006_department_section_counts")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    add_student_archive_column,
                    reverse_code=migrations.RunPython.noop,
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="student",
                    name="deleted_at",
                    field=models.TextField(blank=True, editable=False, null=True),
                ),
            ],
        ),
    ]
