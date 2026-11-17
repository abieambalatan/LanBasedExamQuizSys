"""Private lecture documents and one replaceable activity file per student."""

import json
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from django.conf import settings
from django.core.exceptions import BadRequest
from django.db import transaction
from django.db.models import Count
from django.http import FileResponse, Http404
from django.utils import timezone

from .http import json_response
from .learning_uploads import delete_files_after_commit
from .models import ActivityFileSubmission, LectureClass, LectureMaterial, Student, Teacher
from .targets import normalize_target_classes
from .views import current_admin_account, current_student_account


FILE_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def _teacher(request):
    account = current_admin_account(request)
    if not account or account["role"] != "teacher":
        return None
    return Teacher.objects.filter(id=request.session["account"]["teacherId"], deleted_at__isnull=True).first()


def _student(request):
    account = current_student_account(request)
    if not account:
        return None
    return Student.objects.filter(pk=account["studentId"], deleted_at__isnull=True).first()


def _student_materials(student):
    return LectureMaterial.objects.filter(
        teacher_id__in=Teacher.objects.filter(deleted_at__isnull=True).values("id"),
        target_classes__department=student.department,
        target_classes__year_level=student.year_level,
        target_classes__section=student.section,
    )


def _upload(request):
    files = [file for values in request.FILES.lists() for file in values[1]]
    if getattr(request, "learning_upload_too_large", False):
        raise BadRequest("Each file must be 25 MB or smaller.")
    if len(files) != 1 or "file" not in request.FILES:
        raise BadRequest("Choose exactly one file to upload.")
    file = request.FILES["file"]
    suffix = Path(file.name).suffix.lower()
    if suffix not in FILE_TYPES:
        raise BadRequest("Choose a PDF, Word (.doc, .docx), PowerPoint (.ppt, .pptx), or Excel (.xls, .xlsx) file.")
    if not file.size or file.size > settings.LEARNING_FILE_MAX_BYTES:
        raise BadRequest("Choose a non-empty file of 25 MB or smaller.")
    # Do not trust a browser's MIME type or an extension alone. Office ZIPs are
    # inspected without extracting or decompressing their document contents.
    header = file.read(8)
    valid = False
    if suffix == ".pdf":
        valid = header.startswith(b"%PDF-")
    elif suffix in (".doc", ".ppt", ".xls"):
        valid = header == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    else:
        part = {".docx": "word/document.xml", ".pptx": "ppt/presentation.xml", ".xlsx": "xl/workbook.xml"}[suffix]
        try:
            file.seek(0)
            with ZipFile(file) as archive:
                names = archive.namelist()
                valid = "[Content_Types].xml" in names and part in names and not any(
                    name.lower().endswith("vbaproject.bin") for name in names
                )
        except (BadZipFile, OSError, ValueError):
            valid = False
    file.seek(0)
    if not valid:
        raise BadRequest("The file contents do not match its document type. Save it as a supported document and try again.")
    # Normalise both Windows and POSIX paths even when the browser sends one.
    file.name = file.name.replace("\\", "/").split("/")[-1]
    return file


def _file_payload(record, kind, role):
    base = f"/api/learning/files/{kind}/{record.pk}?portalRole={role}"
    return {"filename": record.filename, "size": record.size, "openUrl": base, "downloadUrl": base + "&download=1"}


def _submission_payload(submission, role, student=None):
    data = {"id": submission.pk, "submittedAt": submission.submitted_at.isoformat(), **_file_payload(submission, "submission", role)}
    if student:
        data.update(name=student.name, rollNo=student.roll_no, department=student.department, yearLevel=student.year_level, section=student.section)
    return data


def list_materials(request):
    student = _student(request)
    teacher = _teacher(request) if not student else None
    if not student and not teacher:
        return json_response({"error": "Sign in with a teacher or student account."}, status=401)
    materials = (_student_materials(student) if student else LectureMaterial.objects.filter(teacher_id=teacher.pk))
    materials = materials.prefetch_related("target_classes").annotate(submission_count=Count("submissions"))
    submissions = {item.material_id: item for item in ActivityFileSubmission.objects.filter(student_id=student.pk)} if student else {}
    teachers = dict(Teacher.objects.filter(deleted_at__isnull=True).values_list("id", "name"))
    role = "student" if student else "teacher"
    output = []
    for material in materials:
        data = {
            "id": material.pk, "title": material.title, "subject": material.subject,
            "instructions": material.instructions, "requiresSubmission": material.requires_submission,
            "createdAt": material.created_at.isoformat(), "teacherName": teachers.get(material.teacher_id, "Teacher"),
            **_file_payload(material, "material", role),
        }
        if student:
            submission = submissions.get(material.pk)
            data["mySubmission"] = _submission_payload(submission, role) if submission else None
        else:
            data["targetClasses"] = [{"department": item.department, "yearLevel": item.year_level, "section": item.section} for item in material.target_classes.all()]
            data["submissionCount"] = material.submission_count
        output.append(data)
    return json_response(output)


def create_material(request):
    teacher = _teacher(request)
    if not teacher:
        return json_response({"error": "Teacher sign in required."}, status=403)
    file = _upload(request)
    title, subject = (request.POST.get(key, "").strip() for key in ("title", "subject"))
    instructions = request.POST.get("instructions", "").strip()
    if not title or not subject or len(title) > 200 or len(subject) > 200:
        raise BadRequest("Enter a title and subject, each up to 200 characters.")
    if len(instructions) > 10000:
        raise BadRequest("Instructions must be 10,000 characters or fewer.")
    try:
        raw_targets = json.loads(request.POST.get("targetClasses", "[]"))
    except (ValueError, TypeError) as error:
        raise BadRequest("Select valid target classes.") from error
    targets, error = normalize_target_classes({"targetClasses": raw_targets})
    if error:
        raise BadRequest(error)
    material = LectureMaterial(
        teacher_id=teacher.pk, title=title, subject=subject, instructions=instructions,
        requires_submission=request.POST.get("requiresSubmission") == "true",
        filename=file.name, size=file.size,
    )
    try:
        material.file.save(file.name, file, save=False)
        with transaction.atomic():
            material.save()
            LectureClass.objects.bulk_create([LectureClass(material=material, department=item["department"], year_level=item["yearLevel"], section=item["section"]) for item in targets])
    except Exception:
        if material.file.name:
            material.file.delete(save=False)
        raise
    return json_response({"ok": True, "id": material.pk}, status=201)


def delete_material_records(materials):
    """Clean private files only after database deletion commits."""
    records = list(materials)
    files = [(item.file.storage, item.file.name) for item in records]
    files += [(item.file.storage, item.file.name) for item in ActivityFileSubmission.objects.filter(material__in=records)]
    materials.delete()
    delete_files_after_commit(files)


def delete_material(request, material_id):
    teacher = _teacher(request)
    if not teacher:
        return json_response({"error": "Teacher sign in required."}, status=403)
    with transaction.atomic():
        material = LectureMaterial.objects.select_for_update().filter(pk=material_id, teacher_id=teacher.pk).first()
        if not material:
            raise Http404
        delete_material_records(LectureMaterial.objects.filter(pk=material.pk))
    return json_response({"ok": True})


def submit_file(request, material_id):
    student = _student(request)
    if not student:
        return json_response({"error": "Student sign in required."}, status=401)
    # Check recipients before parsing or storing the uploaded document.
    if not _student_materials(student).filter(pk=material_id).exists():
        raise Http404
    file = _upload(request)
    saved = None
    try:
        with transaction.atomic():
            material = LectureMaterial.objects.select_for_update().filter(pk=material_id).first()
            if not material or not material.requires_submission:
                raise BadRequest("This lecture does not accept activity submissions.")
            submission, _ = ActivityFileSubmission.objects.get_or_create(
                material=material, student_id=student.pk, defaults={"filename": file.name, "size": file.size},
            )
            old_name = submission.file.name
            submission.file.save(file.name, file, save=False)
            saved = (submission.file.storage, submission.file.name)
            submission.filename, submission.size = file.name, file.size
            submission.submitted_at = timezone.now()
            submission.save()
            if old_name:
                delete_files_after_commit([(submission.file.storage, old_name)])
    except Exception:
        if saved:
            saved[0].delete(saved[1])
        raise
    return json_response({"ok": True, "submission": _submission_payload(submission, "student")})


def list_submissions(request, material_id):
    teacher = _teacher(request)
    if not teacher:
        return json_response({"error": "Teacher sign in required."}, status=403)
    material = LectureMaterial.objects.filter(pk=material_id, teacher_id=teacher.pk).first()
    if not material:
        raise Http404
    submissions = list(material.submissions.all())
    students = Student.objects.in_bulk([item.student_id for item in submissions])
    return json_response([_submission_payload(item, "teacher", students.get(item.student_id)) for item in submissions])


def serve_file(request, kind, file_id):
    student = _student(request)
    teacher = _teacher(request) if not student else None
    if not student and not teacher:
        return json_response({"error": "Sign in to open this document."}, status=401)
    if kind == "material":
        record = LectureMaterial.objects.filter(pk=file_id).first()
        material = record
    elif kind == "submission":
        record = ActivityFileSubmission.objects.select_related("material").filter(pk=file_id).first()
        material = record.material if record else None
    else:
        raise Http404
    if not material:
        raise Http404
    if teacher and material.teacher_id != teacher.pk:
        raise Http404
    if student and (not _student_materials(student).filter(pk=material.pk).exists() or (kind == "submission" and record.student_id != student.pk)):
        raise Http404
    try:
        handle = record.file.open("rb")
    except (OSError, ValueError) as error:
        raise Http404 from error
    suffix = Path(record.filename).suffix.lower()
    # PDFs can be read in the browser. Office documents open in a local app;
    # no external viewer receives private classroom files.
    response = FileResponse(handle, as_attachment=request.GET.get("download") == "1" or suffix != ".pdf", filename=record.filename, content_type=FILE_TYPES.get(suffix, "application/octet-stream"))
    response["Cache-Control"] = "private, no-store"
    response["Content-Security-Policy"] = "sandbox"
    return response
