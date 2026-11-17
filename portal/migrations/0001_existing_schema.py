"""Adopt existing exam.db tables without recreating them."""

from django.db import migrations


def initialize_schema(apps, schema_editor):
    from portal.db import init_db
    init_db()


class Migration(migrations.Migration):
    initial = True
    atomic = False
    dependencies = []
    operations = [migrations.RunPython(initialize_schema, reverse_code=migrations.RunPython.noop)]
