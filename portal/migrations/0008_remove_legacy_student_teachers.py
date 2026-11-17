"""Remove enrollments retired by program/year/section assessment access."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("portal", "0007_student_archive")]

    operations = [
        migrations.RunSQL("DROP TABLE IF EXISTS student_teachers"),
    ]
