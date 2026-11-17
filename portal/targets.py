"""Exact assessment recipients, with compatibility for earlier assessments."""

from .models import SchoolOption
from .constants import YEAR_LEVELS
from .school_options import option_values
from .school_options import sections_for_department


def ensure_target_class_schema(conn):
    from .db import _column_exists

    conn.execute("""CREATE TABLE IF NOT EXISTS exam_target_classes (
        exam_id TEXT NOT NULL,
        department TEXT NOT NULL,
        year_level TEXT NOT NULL,
        section TEXT NOT NULL,
        PRIMARY KEY (exam_id, department, year_level, section)
    )""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_exam_targets_class
        ON exam_target_classes (department, year_level, section, exam_id)""")
    if not _column_exists(conn, "results", "year_level"):
        conn.execute("ALTER TABLE results ADD COLUMN year_level TEXT NOT NULL DEFAULT ''")
        conn.execute("""UPDATE results SET year_level=COALESCE(
            (SELECT year_level FROM exams WHERE exams.id=results.exam_id), '')""")
    conn.execute("""CREATE INDEX IF NOT EXISTS idx_results_class
        ON results (exam_id, department, year_level, section)""")


def normalize_target_classes(data):
    """Read new class rows or expand the old department/year/section payload."""
    available_departments = option_values(SchoolOption.DEPARTMENT)
    years = YEAR_LEVELS
    if "targetClasses" in data:
        raw = data["targetClasses"]
        if not isinstance(raw, list) or not 1 <= len(raw) <= 120:
            return [], "Add between 1 and 120 target classes."
    else:
        departments = data.get("departments") or [data.get("department")]
        if not isinstance(departments, list) or not departments:
            return [], "Select at least one valid exam department."
        if any(department not in available_departments for department in departments):
            return [], "Select at least one valid exam department."
        year = data.get("yearLevel")
        section = data.get("sectionScope") or "ALL"
        if not isinstance(section, str):
            return [], "Select all sections or a valid section."
        raw = [
            {"department": department, "yearLevel": year, "section": value}
            for department in departments
            for value in (sections_for_department(department, year)
                          if section.strip().upper() == "ALL"
                          else [section])
        ]
    targets = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            return [], "Each target class needs a department, year level, and section."
        department, year, section = (item.get(key) for key in ("department", "yearLevel", "section"))
        if not all(isinstance(value, str) for value in (department, year, section)):
            return [], "Each target class needs a department, year level, and section."
        department, year, section = department.strip().upper(), year.strip(), section.strip().upper()
        if (
            department not in available_departments
            or year not in years
            or section not in sections_for_department(department, year)
        ):
            return [], "Select a valid department, year level, and section for every target class."
        key = (department, year, section)
        if key not in seen:
            seen.add(key)
            targets.append({"department": department, "yearLevel": year, "section": section})
    if not targets:
        return [], "Add at least one target class."
    return targets, None


def target_classes(conn, exam):
    rows = conn.execute("""SELECT department, year_level, section FROM exam_target_classes
        WHERE exam_id=? ORDER BY department, year_level, section""", (exam["id"],)).fetchall()
    if rows:
        return [{"department": row["department"], "yearLevel": row["year_level"], "section": row["section"]}
                for row in rows]
    # Existing assessments retain exactly their earlier department/year/section scope.
    departments = conn.execute("SELECT department FROM exam_departments WHERE exam_id=? ORDER BY department", (exam["id"],)).fetchall()
    years = [exam["year_level"]] if exam["year_level"] else YEAR_LEVELS
    return [
        {"department": row["department"], "yearLevel": year, "section": section}
        for row in departments
        for year in years
        for section in (sections_for_department(row["department"], year)
                        if exam["section_scope"] in ("", "ALL")
                        else [exam["section_scope"]])
    ]


def target_summary(targets):
    departments = list(dict.fromkeys(item["department"] for item in targets))
    years = {item["yearLevel"] for item in targets}
    sections = {item["section"] for item in targets}
    return departments, next(iter(years)) if len(years) == 1 else "", next(iter(sections)) if len(sections) == 1 else "ALL"


def save_target_classes(conn, exam_id, targets):
    conn.execute("DELETE FROM exam_target_classes WHERE exam_id=?", (exam_id,))
    conn.executemany("""INSERT INTO exam_target_classes (exam_id, department, year_level, section)
        VALUES (?,?,?,?)""", [(exam_id, item["department"], item["yearLevel"], item["section"]) for item in targets])


def student_scope_sql():
    """Correlated against exams; values are always department, year, section twice."""
    return """(
        EXISTS (SELECT 1 FROM exam_target_classes tc WHERE tc.exam_id=exams.id
            AND tc.department=? AND tc.year_level=? AND tc.section=?)
        OR (NOT EXISTS (SELECT 1 FROM exam_target_classes tc WHERE tc.exam_id=exams.id)
            AND EXISTS (SELECT 1 FROM exam_departments ed WHERE ed.exam_id=exams.id AND ed.department=?)
            AND (exams.year_level='' OR exams.year_level=?)
            AND (exams.section_scope IN ('', 'ALL') OR exams.section_scope=?))
    )"""


def class_can_access(conn, exam_id, department, year, section):
    return conn.execute("SELECT 1 FROM exams WHERE id=? AND " + student_scope_sql(),
                        (exam_id, department, year, section, department, year, section)).fetchone() is not None
