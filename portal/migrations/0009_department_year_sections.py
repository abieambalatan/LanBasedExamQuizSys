"""Allow each department's year levels to have different section counts."""

from django.db import migrations, models


def add_year_sections(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        columns = {column.name for column in connection.introspection.get_table_description(cursor, "portal_schooloption")}
    if "year_section_counts" not in columns:
        column_type = "jsonb" if connection.vendor == "postgresql" else "text"
        schema_editor.execute(
            f"ALTER TABLE portal_schooloption ADD COLUMN year_section_counts {column_type} DEFAULT '{{}}' NOT NULL"
        )


class Migration(migrations.Migration):
    dependencies = [("portal", "0008_remove_legacy_student_teachers")]
    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[migrations.RunPython(add_year_sections, migrations.RunPython.noop)],
        state_operations=[migrations.AddField(
            model_name="schooloption", name="year_section_counts",
            field=models.JSONField(default=dict, blank=True),
        )],
    )]
