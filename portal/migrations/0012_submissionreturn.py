from django.db import migrations, models
import portal.models


def ensure_return_archive(apps, schema_editor):
    model = portal.models.SubmissionReturn
    if model._meta.db_table not in schema_editor.connection.introspection.table_names():
        schema_editor.create_model(model)


class Migration(migrations.Migration):
    dependencies = [("portal", "0011_correct_two_point_scores")]
    operations = [migrations.SeparateDatabaseAndState(
        database_operations=[migrations.RunPython(ensure_return_archive, migrations.RunPython.noop)],
        state_operations=[
        migrations.CreateModel(
            name="SubmissionReturn",
            fields=[
                ("id", models.CharField(max_length=40, primary_key=True, serialize=False)),
                ("result_id", models.TextField(unique=True)),
                ("exam_id", models.TextField()),
                ("roll_no", models.TextField()),
                ("snapshot", models.TextField()),
                ("returned_by", models.TextField()),
                ("returned_at", models.TextField(default=portal.models.timestamp)),
                ("resubmitted_id", models.TextField(blank=True, default="")),
            ],
            options={
                "ordering": ["-returned_at", "-id"],
                "verbose_name": "returned submission",
                "indexes": [models.Index(fields=["exam_id", "roll_no"], name="returned_exam_student")],
            },
        ),
    ])]
