"""Database connections and the shared assessment schema."""

from contextvars import ContextVar
import re
import sqlite3

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from .constants import DEPARTMENTS, RETIRED_ACCOUNT_PREFIX


request_connections = ContextVar("portal_database_connections", default=None)


class PostgresConnection:
    def __init__(self, connection):
        self._connection = connection

    @staticmethod
    def _prepare_sql(sql):
        sql = sql.strip()
        if sql.upper() == "BEGIN IMMEDIATE":
            return "BEGIN"
        ignore_insert = re.match(r"INSERT\s+OR\s+IGNORE\s+INTO\b", sql, flags=re.IGNORECASE)
        if ignore_insert:
            sql = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", sql, count=1, flags=re.IGNORECASE)
            sql = sql.rstrip().removesuffix(";") + " ON CONFLICT DO NOTHING"
        return sql.replace("?", "%s")

    def execute(self, sql, parameters=()):
        return self._connection.execute(self._prepare_sql(sql), parameters)

    def executemany(self, sql, parameters):
        return self._connection.cursor().executemany(self._prepare_sql(sql), parameters)

    def executescript(self, script):
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()


def get_db():
    database = settings.DATABASES["default"]
    if database["ENGINE"] == "django.db.backends.postgresql":
        import psycopg
        from psycopg.rows import dict_row

        connection = PostgresConnection(psycopg.connect(
            dbname=database["NAME"],
            user=database["USER"],
            password=database["PASSWORD"],
            host=database["HOST"],
            port=database["PORT"],
            connect_timeout=database["OPTIONS"]["connect_timeout"],
            row_factory=dict_row,
        ))
    elif database["ENGINE"] == "django.db.backends.sqlite3" and getattr(settings, "PORTAL_SQLITE_TESTS", False):
        connection = sqlite3.connect(database["NAME"], timeout=30)
        connection.row_factory = sqlite3.Row
    else:
        raise ImproperlyConfigured("The portal requires PostgreSQL; SQLite is limited to isolated test fixtures.")
    connections = request_connections.get()
    if connections is not None:
        connections.append(connection)
    return connection


def _column_exists(conn, table, column):
    if settings.DATABASES["default"]["ENGINE"] == "django.db.backends.postgresql":
        cols = [
            row["column_name"]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = ?",
                (table,),
            ).fetchall()
        ]
    else:
        cols = [row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    return column in cols


def ensure_student_name_columns(conn):
    # Existing full names stay intact; do not guess how to split legacy names.
    for column in ("first_name", "last_name", "middle_initial"):
        if not _column_exists(conn, "students", column):
            conn.execute(f"ALTER TABLE students ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")


def ensure_student_archive_column(conn):
    if not _column_exists(conn, "students", "deleted_at"):
        conn.execute("ALTER TABLE students ADD COLUMN deleted_at TEXT")


def ensure_result_activity_column(conn):
    if not _column_exists(conn, "results", "activity_log_json"):
        conn.execute("ALTER TABLE results ADD COLUMN activity_log_json TEXT")


def init_db():
    conn = get_db()
    if settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS students (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            roll_no TEXT NOT NULL UNIQUE,
            department TEXT NOT NULL,
            username TEXT,
            password_hash TEXT,
            teacher_username TEXT NOT NULL DEFAULT '',
            section TEXT NOT NULL DEFAULT '',
            year_level TEXT NOT NULL DEFAULT '',
            deleted_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS teachers (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            username TEXT NOT NULL UNIQUE,
            department TEXT NOT NULL DEFAULT 'ALL',
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            deleted_at TEXT
        );
        CREATE TABLE IF NOT EXISTS teacher_departments (
            teacher_username TEXT NOT NULL,
            department TEXT NOT NULL,
            PRIMARY KEY (teacher_username, department)
        );
        CREATE TABLE IF NOT EXISTS exams (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            duration INTEGER NOT NULL,
            department TEXT NOT NULL DEFAULT 'ALL',
            created_by TEXT NOT NULL DEFAULT '',
            year_level TEXT NOT NULL DEFAULT '',
            subject TEXT NOT NULL DEFAULT '',
            section_scope TEXT NOT NULL DEFAULT 'ALL',
            activity_type TEXT NOT NULL DEFAULT 'exam',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS exam_departments (
            exam_id TEXT NOT NULL,
            department TEXT NOT NULL,
            PRIMARY KEY (exam_id, department)
        );
        CREATE TABLE IF NOT EXISTS questions (
            id TEXT PRIMARY KEY,
            exam_id TEXT NOT NULL,
            position INTEGER NOT NULL,
            part INTEGER NOT NULL DEFAULT 1,
            type TEXT NOT NULL DEFAULT 'multiple_choice',
            text TEXT NOT NULL,
            option_a TEXT NOT NULL DEFAULT '',
            option_b TEXT NOT NULL DEFAULT '',
            option_c TEXT NOT NULL DEFAULT '',
            option_d TEXT NOT NULL DEFAULT '',
            correct INTEGER NOT NULL DEFAULT 0,
            answer_text TEXT NOT NULL DEFAULT '',
            alternatives_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS results (
            id TEXT PRIMARY KEY,
            exam_id TEXT NOT NULL,
            exam_title TEXT NOT NULL,
            name TEXT NOT NULL,
            roll_no TEXT NOT NULL,
            score INTEGER NOT NULL,
            total INTEGER NOT NULL,
            percent REAL NOT NULL,
            answers_json TEXT NOT NULL,
            submitted_at TEXT NOT NULL,
            time_taken_sec INTEGER NOT NULL,
            auto_submitted INTEGER NOT NULL,
            submit_reason TEXT NOT NULL DEFAULT 'manual',
            teacher_username TEXT NOT NULL DEFAULT '',
            section TEXT NOT NULL DEFAULT ''
        );
        """
    )
    # ---- migrations for databases created by earlier versions of this app ----
    ensure_student_name_columns(conn)
    ensure_student_archive_column(conn)
    ensure_result_activity_column(conn)
    if not _column_exists(conn, "results", "department"):
        conn.execute("ALTER TABLE results ADD COLUMN department TEXT NOT NULL DEFAULT ''")
    if not _column_exists(conn, "results", "teacher_username"):
        conn.execute("ALTER TABLE results ADD COLUMN teacher_username TEXT NOT NULL DEFAULT ''")
    if not _column_exists(conn, "results", "section"):
        conn.execute("ALTER TABLE results ADD COLUMN section TEXT NOT NULL DEFAULT ''")
    if not _column_exists(conn, "results", "submit_reason"):
        conn.execute("ALTER TABLE results ADD COLUMN submit_reason TEXT NOT NULL DEFAULT 'manual'")
    if not _column_exists(conn, "results", "submission_key"):
        conn.execute("ALTER TABLE results ADD COLUMN submission_key TEXT NOT NULL DEFAULT ''")
    if not _column_exists(conn, "exams", "department"):
        conn.execute("ALTER TABLE exams ADD COLUMN department TEXT NOT NULL DEFAULT 'ALL'")
    if not _column_exists(conn, "exams", "created_by"):
        conn.execute("ALTER TABLE exams ADD COLUMN created_by TEXT NOT NULL DEFAULT ''")
    if not _column_exists(conn, "exams", "year_level"):
        conn.execute("ALTER TABLE exams ADD COLUMN year_level TEXT NOT NULL DEFAULT ''")
    if not _column_exists(conn, "exams", "subject"):
        conn.execute("ALTER TABLE exams ADD COLUMN subject TEXT NOT NULL DEFAULT ''")
    if not _column_exists(conn, "exams", "section_scope"):
        conn.execute("ALTER TABLE exams ADD COLUMN section_scope TEXT NOT NULL DEFAULT 'ALL'")
    if not _column_exists(conn, "exams", "activity_type"):
        conn.execute("ALTER TABLE exams ADD COLUMN activity_type TEXT NOT NULL DEFAULT 'exam'")
    if not _column_exists(conn, "teachers", "department"):
        conn.execute("ALTER TABLE teachers ADD COLUMN department TEXT NOT NULL DEFAULT 'ALL'")
    if not _column_exists(conn, "teachers", "deleted_at"):
        conn.execute("ALTER TABLE teachers ADD COLUMN deleted_at TEXT")
    for exam_row in conn.execute("SELECT id, department FROM exams").fetchall():
        if conn.execute("SELECT 1 FROM exam_departments WHERE exam_id=? LIMIT 1", (exam_row["id"],)).fetchone():
            continue
        legacy_departments = DEPARTMENTS if exam_row["department"] in ("ALL", "") else [exam_row["department"]]
        conn.executemany(
            "INSERT OR IGNORE INTO exam_departments (exam_id, department) VALUES (?,?)",
            [(exam_row["id"], department) for department in legacy_departments if department in DEPARTMENTS],
        )
    conn.execute(
        """INSERT OR IGNORE INTO teacher_departments (teacher_username, department)
           SELECT username, department FROM teachers WHERE department IN ({})""".format(
               ",".join("?" for _ in DEPARTMENTS)
           ),
        DEPARTMENTS,
    )
    if not _column_exists(conn, "students", "username"):
        conn.execute("ALTER TABLE students ADD COLUMN username TEXT")
    if not _column_exists(conn, "students", "password_hash"):
        conn.execute("ALTER TABLE students ADD COLUMN password_hash TEXT")
    if not _column_exists(conn, "students", "teacher_username"):
        conn.execute("ALTER TABLE students ADD COLUMN teacher_username TEXT NOT NULL DEFAULT ''")
    if not _column_exists(conn, "students", "section"):
        conn.execute("ALTER TABLE students ADD COLUMN section TEXT NOT NULL DEFAULT ''")
    if not _column_exists(conn, "students", "year_level"):
        conn.execute("ALTER TABLE students ADD COLUMN year_level TEXT NOT NULL DEFAULT ''")
    if not _column_exists(conn, "questions", "part"):
        conn.execute("ALTER TABLE questions ADD COLUMN part INTEGER NOT NULL DEFAULT 1")
    if not _column_exists(conn, "questions", "type"):
        conn.execute("ALTER TABLE questions ADD COLUMN type TEXT NOT NULL DEFAULT 'multiple_choice'")
    if not _column_exists(conn, "questions", "answer_text"):
        conn.execute("ALTER TABLE questions ADD COLUMN answer_text TEXT NOT NULL DEFAULT ''")
    if not _column_exists(conn, "questions", "alternatives_json"):
        conn.execute("ALTER TABLE questions ADD COLUMN alternatives_json TEXT NOT NULL DEFAULT '[]'")
    if not _column_exists(conn, "questions", "options_json"):
        conn.execute("ALTER TABLE questions ADD COLUMN options_json TEXT NOT NULL DEFAULT '[]'")

    conn.execute(
        """DELETE FROM results WHERE id IN (
               SELECT earlier.id FROM results earlier
               JOIN results later ON later.exam_id=earlier.exam_id AND later.roll_no=earlier.roll_no
               WHERE later.submitted_at > earlier.submitted_at
                  OR (later.submitted_at=earlier.submitted_at AND later.id > earlier.id)
           )"""
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_results_exam_student ON results (exam_id, roll_no)"
    )
    from .targets import ensure_target_class_schema
    ensure_target_class_schema(conn)
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_questions_exam_position ON questions (exam_id, position);
        CREATE INDEX IF NOT EXISTS idx_students_username ON students (username);
        CREATE INDEX IF NOT EXISTS idx_results_student ON results (roll_no);
        CREATE INDEX IF NOT EXISTS idx_results_teacher ON results (teacher_username);
        CREATE INDEX IF NOT EXISTS idx_exams_teacher ON exams (created_by);
    """)

    # Remove exams left behind by teacher accounts deleted in older versions.
    orphan_exam_ids = conn.execute(
        """SELECT e.id FROM exams e
           WHERE e.created_by <> ''
             AND SUBSTR(e.created_by,1,?) <> ?
             AND NOT EXISTS (
                 SELECT 1 FROM teachers t WHERE t.username = e.created_by
             )""", (len(RETIRED_ACCOUNT_PREFIX), RETIRED_ACCOUNT_PREFIX)
    ).fetchall()
    for row in orphan_exam_ids:
        conn.execute("DELETE FROM questions WHERE exam_id=?", (row["id"],))
        conn.execute("DELETE FROM results WHERE exam_id=?", (row["id"],))
        conn.execute("DELETE FROM exam_departments WHERE exam_id=?", (row["id"],))
        conn.execute("DELETE FROM exam_target_classes WHERE exam_id=?", (row["id"],))
        conn.execute("DELETE FROM exams WHERE id=?", (row["id"],))
    conn.commit()
    conn.close()
