"""Recover the separate SQLite assessment records without replacing PostgreSQL data.

Read-only by default. The PowerShell wrapper supplies the stored database login.
An apply run backs up both databases and aborts on conflicting assessment rows.
"""

import argparse
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess

import psycopg
from psycopg import sql
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parent.parent
TABLE_KEYS = {
    "students": ("id",),
    "teacher_departments": ("teacher_username", "department"),
    "exams": ("id",),
    "exam_departments": ("exam_id", "department"),
    "exam_target_classes": ("exam_id", "department", "year_level", "section"),
    "questions": ("id",),
    "results": ("id",),
    "portal_submissionreturn": ("id",),
}


def fingerprint(rows):
    encoded = [json.dumps(row, sort_keys=True, default=str) for row in rows]
    return hashlib.sha256("\n".join(sorted(encoded)).encode()).hexdigest()


def sqlite_rows(source, table):
    # Table names come only from the fixed table list in this script.
    return [dict(row) for row in source.execute(f'SELECT * FROM "{table}"')]


def postgres_rows(target, table):
    return target.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(table))).fetchall()


def row_key(row, columns):
    return tuple(row[column] for column in columns)


def records_match(table, expected, actual):
    if expected == actual:
        return True
    if table != "results" or expected.keys() != actual.keys():
        return False
    # PostgreSQL's existing REAL column stores percentages at float32 precision.
    # Answers, integer points, identities, and every other field must match exactly.
    return all(
        math.isclose(value, actual[column], rel_tol=1e-7, abs_tol=1e-7)
        if column == "percent" else value == actual[column]
        for column, value in expected.items()
    )


def plan_rows(table, source_rows, target_rows):
    existing = {row_key(row, TABLE_KEYS[table]): row for row in target_rows}
    additions = []
    for row in source_rows:
        key = row_key(row, TABLE_KEYS[table])
        if key not in existing:
            additions.append(row)
        elif not records_match(table, row, existing[key]):
            raise ValueError(f"Conflicting {table} record; no existing record will be replaced.")
    # Detect secondary unique-key conflicts before attempting the import.
    for columns in {
        "students": [("roll_no",)],
        "results": [("exam_id", "roll_no")],
        "portal_submissionreturn": [("result_id",)],
    }.get(table, []):
        occupied = {row_key(row, columns) for row in target_rows}
        for row in additions:
            key = row_key(row, columns)
            if key in occupied:
                raise ValueError(f"Conflicting {table} unique key; recovery stopped.")
            occupied.add(key)
    return additions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    connection_options = {
        key: os.environ[f"ARALHUB_AUDIT_DB_{env}"]
        for key, env in {
            "dbname": "NAME", "user": "USER", "password": "PASSWORD",
            "host": "HOST", "port": "PORT",
        }.items()
    }
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    report = {"mode": "apply" if args.apply else "dry_run", "tables": {}}
    source_path = ROOT / "exam.db"
    with sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True) as source:
        source.row_factory = sqlite3.Row
        if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed.")
        source.execute("BEGIN")
        data = {table: sqlite_rows(source, table) for table in TABLE_KEYS}
        source_teachers = sqlite_rows(source, "teachers")
        source_options = sqlite_rows(source, "portal_schooloption")
        for row in source_options:
            row["year_section_counts"] = json.loads(row["year_section_counts"])

        if args.apply:
            backup_dir = ROOT / "backups"
            backup_dir.mkdir(exist_ok=True)
            sqlite_backup = backup_dir / f"before_sqlite_recovery_{stamp}.db"
            with sqlite3.connect(sqlite_backup) as destination:
                source.backup(destination)
            pg_backup = backup_dir / f"before_sqlite_recovery_{stamp}.dump"
            pg_env = {**os.environ, "PGPASSWORD": connection_options["password"]}
            subprocess.run([
                r"C:\Program Files\PostgreSQL\18\bin\pg_dump.exe",
                "-h", connection_options["host"], "-p", connection_options["port"],
                "-U", connection_options["user"], "-d", connection_options["dbname"],
                "-Fc", "-f", str(pg_backup),
            ], env=pg_env, check=True, capture_output=True, timeout=60)
            subprocess.run([
                r"C:\Program Files\PostgreSQL\18\bin\pg_restore.exe", "--list", str(pg_backup),
            ], check=True, capture_output=True, timeout=10)
            if not pg_backup.stat().st_size:
                raise ValueError("PostgreSQL backup is empty.")
            report["backups"] = {"sqlite": str(sqlite_backup), "postgresql": str(pg_backup)}

        options = "-c lock_timeout=5000 -c statement_timeout=30000"
        if not args.apply:
            options += " -c default_transaction_read_only=on"
        with psycopg.connect(**connection_options, connect_timeout=5, row_factory=dict_row,
                             options=options) as target:
            if args.apply:
                # Reads stay available; prevent writes during the short import transaction.
                target.execute(sql.SQL("LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE").format(
                    sql.SQL(", ").join(sql.Identifier(table) for table in
                                      [*TABLE_KEYS, "teachers", "portal_schooloption"])))
            before = {table: postgres_rows(target, table) for table in TABLE_KEYS}
            source_columns = {
                table: set(row["name"] for row in source.execute(f'PRAGMA table_info("{table}")'))
                for table in TABLE_KEYS
            }
            for table in TABLE_KEYS:
                target_columns = {row["column_name"] for row in target.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema=current_schema() AND table_name=%s", [table])}
                if target_columns != source_columns[table]:
                    raise ValueError(f"Schema differs for {table}.")
            teachers = {row["username"]: row for row in postgres_rows(target, "teachers")}
            for teacher in source_teachers:
                current = teachers.get(teacher["username"])
                if not current or current["name"] != teacher["name"] or current["deleted_at"]:
                    raise ValueError("Assessment owner is missing, changed, or inactive.")
            if fingerprint(source_options) != fingerprint(postgres_rows(target, "portal_schooloption")):
                raise ValueError("School settings differ; review departments and sections first.")
            plans = {table: plan_rows(table, data[table], before[table]) for table in TABLE_KEYS}
            known_exams = {row["id"] for row in before["exams"] + plans["exams"]}
            known_students = {row["roll_no"] for row in before["students"] + plans["students"]}
            for table in ("exams", "results"):
                owner_field = "created_by" if table == "exams" else "teacher_username"
                if any(row[owner_field] not in teachers for row in data[table]):
                    raise ValueError(f"An assessment owner is missing for {table}.")
            for table in ("exam_departments", "exam_target_classes", "questions", "results",
                          "portal_submissionreturn"):
                if any(row["exam_id"] not in known_exams for row in data[table]):
                    raise ValueError(f"Missing assessment for {table}.")
            if any(row["roll_no"] not in known_students for row in data["results"]):
                raise ValueError("A recovered result has no student account.")

            for table, additions in plans.items():
                report["tables"][table] = {"before": len(before[table]), "source": len(data[table]),
                                          "add": len(additions),
                                          "source_sha256": fingerprint(data[table]),
                                          "existing_sha256": fingerprint(before[table])}
                if args.apply and additions:
                    columns = list(additions[0])
                    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                        sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns)),
                        sql.SQL(", ").join(sql.Placeholder() for _ in columns))
                    with target.cursor() as cursor:
                        cursor.executemany(query, [tuple(row[column] for column in columns)
                                                   for row in additions])
            if args.apply:
                for table in TABLE_KEYS:
                    after = postgres_rows(target, table)
                    expected = before[table] + plans[table]
                    actual_by_key = {row_key(row, TABLE_KEYS[table]): row for row in after}
                    if len(after) != len(expected) or any(
                        row_key(row, TABLE_KEYS[table]) not in actual_by_key
                        or not records_match(table, row, actual_by_key[row_key(row, TABLE_KEYS[table])])
                        for row in expected
                    ):
                        raise ValueError(f"Verification failed for {table}; transaction rolled back.")
                    original_after = [actual_by_key[row_key(row, TABLE_KEYS[table])]
                                      for row in before[table]]
                    if fingerprint(original_after) != fingerprint(before[table]):
                        raise ValueError(f"Existing {table} data changed; transaction rolled back.")
                    report["tables"][table]["after"] = len(after)
                    report["tables"][table]["after_sha256"] = fingerprint(after)
                    if table == "results":
                        report["percentage_storage_rounding"] = sum(
                            row["percent"] != actual_by_key[row_key(row, TABLE_KEYS[table])]["percent"]
                            for row in plans[table])
                # Existing login credentials and account identities are deliberately retained.
                report["existing_records_preserved"] = True
                report["all_recovered_rows_verified"] = True
                target.commit()
                report_path = ROOT / "reports" / f"sqlite_recovery_{stamp}.json"
                report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
                report["report"] = str(report_path)
            else:
                target.rollback()
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
