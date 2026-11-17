"""Classroom values shared by schema setup and API validation."""

DEPARTMENTS = ["BSIT", "BSCRIM", "BEED", "BSHM", "BSN"]
EXAM_DEPARTMENTS = ["ALL"] + DEPARTMENTS
SECTIONS = ["A", "B", "C", "D", "E", "F"]
YEAR_LEVELS = ["1st Year", "2nd Year", "3rd Year", "4th Year"]
DEFAULT_SCHOOL_OPTIONS = {"department": ("BSIT", "BSCRIM", "BEED", "BSHM", "BSN")}
MAX_SECTIONS_PER_DEPARTMENT = 26
RETIRED_ACCOUNT_PREFIX = "__deleted_account__:"


def points_per_question(activity_type="exam", question_type=None):
    return 1 if activity_type == "quiz" or question_type in ("true_false", "matching") else 2


def question_point_values(activity_type="exam"):
    return {kind: points_per_question(activity_type, kind) for kind in
            ("multiple_choice", "identification", "true_false", "matching")}
