from .constants import MAX_SECTIONS_PER_DEPARTMENT, YEAR_LEVELS
from .db import get_db
from .models import SchoolOption


def option_values(category):
    return list(
        SchoolOption.objects.filter(category=category)
        .order_by("position", "value")
        .values_list("value", flat=True)
    )


def _letters(count):
    return [chr(ord("A") + index) for index in range(min(count, MAX_SECTIONS_PER_DEPARTMENT))]


def sections_for_department(department, year_level=None):
    option = SchoolOption.objects.filter(
        category=SchoolOption.DEPARTMENT,
        value=department,
    ).only("section_count", "year_section_counts").first()
    if option is None:
        return []
    if year_level is not None and year_level not in YEAR_LEVELS:
        return []
    counts = [option.year_section_counts.get(year, option.section_count) for year in YEAR_LEVELS]
    return _letters(option.year_section_counts.get(year_level, option.section_count) if year_level else max(counts))


def sections_for_all_departments():
    maximum = max((option.year_section_counts.get(year, option.section_count)
                   for option in SchoolOption.objects.filter(category=SchoolOption.DEPARTMENT)
                   for year in YEAR_LEVELS), default=0)
    return _letters(maximum)


def sections_in_use(department, sections, year_level=None):
    if not sections:
        return []
    placeholders = ",".join(["?"] * len(sections))
    found = set()
    year_filter = " AND (year_level=? OR year_level='')" if year_level else ""
    year_params = [year_level] if year_level else []
    references = [
        (f"SELECT section FROM {table} WHERE department=? AND section IN ({placeholders})" + year_filter, [department, *sections, *year_params])
        for table in ("students", "results", "exam_target_classes", "portal_lectureclass")
    ] + [
        (
            f"""SELECT e.section_scope AS section FROM exams e
                LEFT JOIN exam_departments ed ON ed.exam_id=e.id
                WHERE (e.department=? OR ed.department=?)
                    AND e.section_scope IN ({placeholders})
                    AND NOT EXISTS (SELECT 1 FROM exam_target_classes tc WHERE tc.exam_id=e.id)""" + (" AND (e.year_level=? OR e.year_level='')" if year_level else ""),
            [department, department, *sections, *year_params],
        ),
    ]
    conn = get_db()
    try:
        for query, params in references:
            found.update(row["section"] for row in conn.execute(query, params).fetchall())
    finally:
        conn.close()
    return [section for section in sections if section in found]


def school_options_payload():
    options = list(SchoolOption.objects.filter(category=SchoolOption.DEPARTMENT).order_by("position", "value"))
    departments = [option.value for option in options]
    by_year = {option.value: {year: _letters(option.year_section_counts.get(year, option.section_count)) for year in YEAR_LEVELS} for option in options}
    sections_by_department = {department: _letters(max(map(len, years.values()))) for department, years in by_year.items()}
    return {
        "departments": departments,
        "year_level": YEAR_LEVELS,
        "sections_by_department": sections_by_department,
        "sections_by_department_and_year": by_year,
        "section": sections_for_all_departments(),
    }
