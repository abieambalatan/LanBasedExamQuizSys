"""Add exact class recipients and preserve the year level of each submission."""

from django.db import migrations, models


def add_target_classes(apps, schema_editor):
    from portal.db import get_db
    from portal.targets import ensure_target_class_schema

    conn = get_db()
    try:
        ensure_target_class_schema(conn)
        conn.commit()
    finally:
        conn.close()


class Migration(migrations.Migration):
    atomic = False
    dependencies = [("portal", "0003_student_name_parts")]
    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[migrations.RunPython(add_target_classes, reverse_code=migrations.RunPython.noop)],
        state_operations=[migrations.AddField(
            model_name="result", name="year_level", field=models.TextField(blank=True, default=""),
        )],
    )]
