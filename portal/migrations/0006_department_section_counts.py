from django.db import migrations, models


def move_sections_to_departments(apps, schema_editor):
    connection = schema_editor.connection
    table = connection.ops.quote_name("portal_schooloption")
    with connection.cursor() as introspection_cursor:
        columns = {
            column.name
            for column in connection.introspection.get_table_description(
                introspection_cursor, "portal_schooloption"
            )
        }
    if "section_count" not in columns:
        schema_editor.execute(
            f"ALTER TABLE {table} ADD COLUMN "
            f"{connection.ops.quote_name('section_count')} smallint DEFAULT 6 NOT NULL"
        )
    with connection.cursor() as cursor:
        cursor.execute("SELECT value FROM portal_schooloption WHERE category=%s", ["section"])
        section_values = [row[0] for row in cursor.fetchall()]
    legacy_count = max(
        (ord(value.upper()) - ord("A") + 1 for value in section_values if len(value) == 1 and value.upper().isalpha()),
        default=6,
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE portal_schooloption SET section_count=%s WHERE category=%s",
            [max(1, min(26, legacy_count)), "department"],
        )
        cursor.execute("DELETE FROM portal_schooloption WHERE category<>%s", ["department"])


class Migration(migrations.Migration):
    dependencies = [("portal", "0005_school_options")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(move_sections_to_departments, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="schooloption",
                    name="section_count",
                    field=models.PositiveSmallIntegerField(default=6),
                ),
                migrations.AlterField(
                    model_name="schooloption",
                    name="category",
                    field=models.CharField(
                        choices=[("department", "Department")],
                        max_length=20,
                    ),
                ),
            ],
        ),
    ]
