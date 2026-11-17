from django.db import migrations, models

def seed_school_options(apps, schema_editor):
    from portal.models import SchoolOption

    default_school_options = {
        "department": ("BSIT", "BSCRIM", "BEED", "BSHM", "BSN"),
        "year_level": ("1st Year", "2nd Year", "3rd Year", "4th Year"),
        "section": ("A", "B", "C", "D", "E", "F"),
    }
    table_name = SchoolOption._meta.db_table
    if table_name not in schema_editor.connection.introspection.table_names():
        schema_editor.create_model(SchoolOption)
    for category, values in default_school_options.items():
        SchoolOption.objects.bulk_create([
            SchoolOption(category=category, value=value, position=position)
            for position, value in enumerate(values)
        ], ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [("portal", "0004_exam_target_classes")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(seed_school_options, migrations.RunPython.noop),
            ],
            state_operations=[
                migrations.CreateModel(
                    name="SchoolOption",
                    fields=[
                        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                        ("category", models.CharField(choices=[("department", "Department"), ("year_level", "Year level"), ("section", "Section")], max_length=20)),
                        ("value", models.CharField(max_length=20)),
                        ("position", models.PositiveIntegerField(default=0)),
                    ],
                    options={
                        "ordering": ["category", "position", "value"],
                        "constraints": [
                            models.UniqueConstraint(fields=("category", "value"), name="unique_school_option_value"),
                        ],
                    },
                ),
            ],
        ),
    ]
