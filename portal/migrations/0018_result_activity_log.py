"""Keep browser activity evidence with each submitted assessment."""

from django.db import migrations, models


def add_activity_column(apps, schema_editor):
    from portal.db import ensure_result_activity_column, get_db

    conn = get_db()
    try:
        ensure_result_activity_column(conn)
        conn.commit()
    finally:
        conn.close()


class Migration(migrations.Migration):
    dependencies = [("portal", "0017_remove_activity_submission_notifications")]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_activity_column, migrations.RunPython.noop)],
            state_operations=[migrations.AddField(
                model_name="result", name="activity_log_json",
                field=models.TextField(null=True, blank=True, editable=False),
            )],
        ),
    ]
