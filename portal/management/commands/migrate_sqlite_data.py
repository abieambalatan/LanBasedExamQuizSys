"""Copy application and Django data from SQLite into PostgreSQL."""

from pathlib import Path
import json
import sqlite3

from django.apps import apps
from django.conf import settings
from django.core.management.color import no_style
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from portal.db import get_db
from portal.constants import DEFAULT_SCHOOL_OPTIONS


TABLE_ORDER = (
    "django_content_type",
    "portal_schooloption",
    "auth_permission",
    "auth_group",
    "auth_group_permissions",
    "auth_user",
    "auth_user_groups",
    "auth_user_user_permissions",
    "django_admin_log",
    "students",
    "teachers",
    "teacher_departments",
    "exams",
    "exam_departments",
    "exam_target_classes",
    "questions",
    "results",
    "django_session",
)
PRESERVED_TARGET_TABLES = {"django_migrations"}
RETIRED_TABLES = {"student_teachers"}
BATCH_SIZE = 1000


def source_columns(source, table):
    return [
        row["name"]
        for row in source.execute(
            f"PRAGMA table_info({quote_identifier(table)})"
        ).fetchall()
    ]


def ordered_source_tables(source):
    source_tables = {
        row["name"]
        for row in source.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        if row["name"] not in PRESERVED_TARGET_TABLES | RETIRED_TABLES
    }
    return [
        *[table for table in TABLE_ORDER if table in source_tables],
        *sorted(source_tables.difference(TABLE_ORDER)),
    ]


def quote_identifier(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def table_rows_match(source, target, table, columns):
    quoted_table = quote_identifier(table)
    quoted_columns = ", ".join(quote_identifier(column) for column in columns)
    source_rows = {
        tuple(row)
        for row in source.execute(f"SELECT {quoted_columns} FROM {quoted_table}").fetchall()
    }
    target_rows = {
        tuple(row[column] for column in columns)
        for row in target.execute(f"SELECT {quoted_columns} FROM {quoted_table}").fetchall()
    }
    return source_rows == target_rows


def target_has_seeded_school_options(target):
    expected = []
    index = 1
    for category, values in DEFAULT_SCHOOL_OPTIONS.items():
        for position, value in enumerate(values):
            expected.append((index, category, value, position, 6))
            index += 1
    columns = {
        row["name"]
        for row in target.execute("PRAGMA table_info(portal_schooloption)").fetchall()
    }
    if "year_section_counts" in columns:
        for row in target.execute("SELECT year_section_counts FROM portal_schooloption").fetchall():
            counts = row["year_section_counts"]
            if (json.loads(counts) if isinstance(counts, str) else counts):
                return False
    if "section_count" in columns:
        actual = [
            (row["id"], row["category"], row["value"], row["position"], row["section_count"])
            for row in target.execute(
                "SELECT id, category, value, position, section_count FROM portal_schooloption ORDER BY id"
            ).fetchall()
        ]
    else:
        expected = [row[:4] for row in expected]
        actual = [
            (row["id"], row["category"], row["value"], row["position"])
            for row in target.execute(
                "SELECT id, category, value, position FROM portal_schooloption ORDER BY id"
            ).fetchall()
        ]
    return actual == expected


def adapt_row(row, columns, postgres_types):
    def adapt(value, column):
        if value is not None and postgres_types[column] in ("json", "jsonb"):
            from psycopg.types.json import Jsonb
            return Jsonb(json.loads(value) if isinstance(value, str) else value)
        return bool(value) if value is not None and postgres_types[column] == "boolean" else value

    return tuple(
        adapt(value, column)
        for column, value in zip(columns, row)
    )


class Command(BaseCommand):
    help = "Copy all application and Django data from SQLite into PostgreSQL, safely resuming identical prior copies."

    def add_arguments(self, parser):
        parser.add_argument(
            "sqlite_path",
            nargs="?",
            type=Path,
            default=Path(settings.BASE_DIR) / "exam.db",
            help="Source SQLite database (default: project exam.db)",
        )

    def handle(self, *args, **options):
        if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
            raise CommandError("Set EXAM_PORTAL_DB_ENGINE=postgresql and PostgreSQL connection settings first.")

        source_path = options["sqlite_path"].resolve()
        if not source_path.is_file():
            raise CommandError(f"SQLite source database not found: {source_path}")

        source_uri = source_path.as_uri() + "?mode=ro"
        source = sqlite3.connect(source_uri, uri=True)
        source.row_factory = sqlite3.Row
        target = None
        try:
            target = get_db()
            integrity = source.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise CommandError(f"SQLite integrity check failed: {integrity}")

            tables = ordered_source_tables(source)
            if not tables:
                raise CommandError("SQLite source has no application tables to copy.")

            target.execute("SET CONSTRAINTS ALL DEFERRED")
            columns_by_table = {}
            column_types_by_table = {}
            for table in tables:
                columns = source_columns(source, table)
                if not columns:
                    raise CommandError(f"SQLite source table has no columns: {table}")
                target_column_types = {
                    row["column_name"]: row["data_type"]
                    for row in target.execute(
                        "SELECT column_name, data_type FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = ?",
                        (table,),
                    ).fetchall()
                }
                if set(columns) != set(target_column_types):
                    raise CommandError(
                        f"Table {table} has a different schema in SQLite and PostgreSQL. "
                        "Start the SQLite app once to apply pending schema updates, then retry."
                    )
                columns_by_table[table] = columns
                column_types_by_table[table] = target_column_types

            already_initialized = set()
            for table in tables:
                quoted_table = quote_identifier(table)
                target_count = target.execute(
                    f"SELECT COUNT(*) AS count FROM {quoted_table}"
                ).fetchone()["count"]
                if not target_count:
                    continue
                if table_rows_match(source, target, table, columns_by_table[table]):
                    already_initialized.add(table)
                    continue
                if table == "portal_schooloption" and target_has_seeded_school_options(target):
                    target.execute("DELETE FROM portal_schooloption")
                    continue
                raise CommandError(
                    f"PostgreSQL table {table} contains data that differs from SQLite. "
                    "No data was copied. Preserve both databases and investigate before retrying."
                )

            for table in tables:
                if table in already_initialized:
                    self.stdout.write(f"{table}: already initialized; source data verified")
                    continue
                source_columns_for_table = columns_by_table[table]
                quoted_table = quote_identifier(table)
                columns = ", ".join(quote_identifier(column) for column in source_columns_for_table)
                placeholders = ", ".join("?" for _ in source_columns_for_table)
                insert = f"INSERT INTO {quoted_table} ({columns}) VALUES ({placeholders})"
                cursor = source.execute(f"SELECT {columns} FROM {quoted_table}")
                copied = 0
                while True:
                    batch = cursor.fetchmany(BATCH_SIZE)
                    if not batch:
                        break
                    target.executemany(
                        insert,
                        [
                            adapt_row(row, source_columns_for_table, column_types_by_table[table])
                            for row in batch
                        ],
                    )
                    copied += len(batch)
                self.stdout.write(f"{table}: copied {copied} rows")

            for statement in connections["default"].ops.sequence_reset_sql(
                no_style(), apps.get_models()
            ):
                target.execute(statement)
            target.commit()
        except Exception:
            if target is not None:
                target.rollback()
            raise
        finally:
            source.close()
            if target is not None:
                target.close()

        self.stdout.write(self.style.SUCCESS("SQLite assessment data copied to PostgreSQL."))
