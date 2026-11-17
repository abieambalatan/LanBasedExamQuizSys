"""ORM mappings to existing classroom tables; migrations never recreate them."""

import uuid
from django.db import models
from django.utils import timezone
from .constants import DEPARTMENTS, SECTIONS, YEAR_LEVELS


def teacher_id():
    return "tch_" + uuid.uuid4().hex[:10]


def timestamp():
    return timezone.localtime().strftime("%Y-%m-%dT%H:%M:%S")


class Teacher(models.Model):
    id = models.TextField(primary_key=True, default=teacher_id, editable=False)
    name = models.CharField(max_length=255)
    username = models.CharField(max_length=150, unique=True)
    department = models.CharField(max_length=20, choices=[(d, d) for d in DEPARTMENTS])
    password_hash = models.TextField(editable=False)
    created_at = models.TextField(default=timestamp, editable=False)
    deleted_at = models.TextField(null=True, blank=True, editable=False)

    class Meta:
        managed = False
        db_table = "teachers"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Student(models.Model):
    id = models.TextField(primary_key=True, editable=False)
    name = models.TextField()
    first_name = models.CharField(max_length=255, blank=True, default="")
    last_name = models.CharField(max_length=255, blank=True, default="")
    middle_initial = models.CharField(max_length=1, blank=True, default="")
    roll_no = models.TextField(unique=True, verbose_name="Student ID")
    department = models.CharField(max_length=20, choices=[(d, d) for d in DEPARTMENTS])
    username = models.TextField(null=True, blank=True, editable=False)
    password_hash = models.TextField(null=True, blank=True, editable=False)
    teacher_username = models.TextField(blank=True, editable=False)
    section = models.CharField(max_length=1, choices=[(s, s) for s in SECTIONS], blank=True)
    year_level = models.CharField(max_length=20, choices=[(y, y) for y in YEAR_LEVELS], blank=True)
    created_at = models.TextField(editable=False)
    deleted_at = models.TextField(null=True, blank=True, editable=False)

    class Meta:
        managed = False
        db_table = "students"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.roll_no})"


class Exam(models.Model):
    id = models.TextField(primary_key=True)
    title = models.TextField()
    duration = models.IntegerField()
    department = models.TextField()
    created_by = models.TextField()
    year_level = models.TextField()
    subject = models.TextField()
    section_scope = models.TextField()
    activity_type = models.TextField()
    created_at = models.TextField()

    class Meta:
        managed = False
        db_table = "exams"
        verbose_name = "assessment"
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class Result(models.Model):
    id = models.TextField(primary_key=True)
    exam_id = models.TextField()
    exam_title = models.TextField()
    name = models.TextField()
    roll_no = models.TextField(verbose_name="Student ID")
    score = models.IntegerField()
    total = models.IntegerField()
    percent = models.FloatField()
    answers_json = models.TextField()
    submitted_at = models.TextField()
    time_taken_sec = models.IntegerField()
    auto_submitted = models.IntegerField()
    submit_reason = models.TextField()
    teacher_username = models.TextField()
    section = models.TextField()
    department = models.TextField()
    year_level = models.TextField(blank=True, default="")
    submission_key = models.TextField()
    activity_log_json = models.TextField(null=True, blank=True, editable=False)

    class Meta:
        managed = False
        db_table = "results"
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"{self.name}: {self.score} / {self.total}"


class SchoolOption(models.Model):
    DEPARTMENT = "department"
    CATEGORY_CHOICES = [(DEPARTMENT, "Department")]

    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    value = models.CharField(max_length=20)
    position = models.PositiveIntegerField(default=0)
    section_count = models.PositiveSmallIntegerField(default=6)
    year_section_counts = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["category", "position", "value"]
        constraints = [
            models.UniqueConstraint(fields=["category", "value"], name="unique_school_option_value"),
        ]

    def __str__(self):
        return self.value


class SubmissionReturn(models.Model):
    """Keep the original receipt and answers when staff reopen an assessment."""

    id = models.CharField(max_length=40, primary_key=True)
    result_id = models.TextField(unique=True)
    exam_id = models.TextField()
    roll_no = models.TextField()
    snapshot = models.TextField()
    returned_by = models.TextField()
    returned_at = models.TextField(default=timestamp)
    resubmitted_id = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-returned_at", "-id"]
        indexes = [models.Index(fields=["exam_id", "roll_no"], name="returned_exam_student")]
        verbose_name = "returned submission"


def learning_id():
    return uuid.uuid4().hex


def learning_upload_path(instance, filename):
    # Client filenames are metadata only; never use them as storage paths.
    from pathlib import Path
    return f"learning/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


class LectureMaterial(models.Model):
    id = models.CharField(max_length=32, primary_key=True, default=learning_id, editable=False)
    teacher_id = models.TextField(db_index=True)
    title = models.CharField(max_length=200)
    subject = models.CharField(max_length=200)
    instructions = models.TextField(blank=True)
    requires_submission = models.BooleanField(default=False)
    file = models.FileField(upload_to=learning_upload_path, max_length=255)
    filename = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]


class LectureClass(models.Model):
    material = models.ForeignKey(LectureMaterial, related_name="target_classes", on_delete=models.CASCADE)
    department = models.CharField(max_length=20)
    year_level = models.CharField(max_length=20)
    section = models.CharField(max_length=1)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["material", "department", "year_level", "section"], name="unique_lecture_class")]
        indexes = [models.Index(fields=["department", "year_level", "section"], name="lecture_recipient_class")]


class ActivityFileSubmission(models.Model):
    id = models.CharField(max_length=32, primary_key=True, default=learning_id, editable=False)
    material = models.ForeignKey(LectureMaterial, related_name="submissions", on_delete=models.CASCADE)
    student_id = models.TextField(db_index=True)
    file = models.FileField(upload_to=learning_upload_path, max_length=255)
    filename = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    submitted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-submitted_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["material", "student_id"], name="unique_activity_file_student")]


class AssessmentActivity(models.Model):
    id = models.CharField(max_length=32, primary_key=True, default=learning_id, editable=False)
    exam_id = models.TextField(db_index=True)
    student_id = models.TextField(db_index=True)
    submission_key = models.CharField(max_length=128)
    activity_log_json = models.TextField()
    created_at = models.FloatField()
    received_at = models.FloatField()
    page_hidden = models.BooleanField(default=False)
    window_focused = models.BooleanField(default=True)
    result_id = models.TextField(blank=True, default="")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["exam_id", "student_id", "submission_key"], name="unique_assessment_activity")]

