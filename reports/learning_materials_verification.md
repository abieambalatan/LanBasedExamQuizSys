# Lecture materials and activity file submissions

Verified on 2026-11-11 (Asia/Singapore).

Teachers can share a PDF, PowerPoint, Word, or Excel document with selected classes, include instructions, request a student file submission, review student files, and delete a material. Students can open/download their class materials, submit an activity document, and replace their previous submission. Files are limited to 25 MB and served through authenticated endpoints outside the public frontend directory.

| Check | Result |
| --- | --- |
| Backend regression suite: `test_app`, `test_database_configuration`, `test_learning` | 73 passed |
| Browser regression suite: `test_frontend` | 32 passed through Edge DevTools |
| Real PostgreSQL workflow in a disposable schema | Passed |
| Four simultaneous student submission replacements | One submission record and one current submission file |
| Teacher/student materials screens at 1440, 768, 390, and 320 px | All eight layouts passed; no horizontal overflow |
| Django system check and migration consistency | Passed; no pending model changes |

The standard browser runner intermittently encountered native Edge access-violation exits (`3221225477`). The same 32 browser test scripts and assertions passed when executed through an Edge DevTools connection. No product assertion was bypassed. The new upload checks cover multipart requests, CSRF renewal, teacher publication and submission review, student submission/replacement, and preservation of the chosen file after an upload error.

Backend checks cover all seven document extensions, exact class recipients, authenticated file links with independent student/teacher cookies, submission privacy, archived accounts, rejected files and upload limits, CSRF, replacement and deletion cleanup, database rollback, locked-file cleanup failures, department renaming, and migration replay without losing records or files.

`reports/verify_learning_postgres.py` used only a uniquely named disposable PostgreSQL schema and temporary upload directory. It checked migration, login, material creation/opening, concurrent student replacements, teacher review/download, and deletion. Its schema and temporary files were removed. Live classroom records were not changed.

The existing launcher applied `0015_lecture_materials` during the server restart described below. PDF opens in the browser; Word, PowerPoint, and Excel download to open in an installed application. Back up `uploads/` (or `EXAM_PORTAL_UPLOAD_ROOT`) with the PostgreSQL database. File cleanup runs after commit; a file locked by an active download may remain on disk and is logged without invalidating the replacement submission.

Implementation details and usage are documented in `docs/DJANGO_BACKEND.md`. Screenshots and layout results are in `ui-previews/*-materials-*` and `ui-previews/learning-materials-layout-checks.json`.

## Live route fix and mixed-course classes

The running Waitress process was started before the new Python routes were implemented. It served the updated frontend from disk but still dispatched `/api/learning/materials` through its old frontend catch-all: GET returned `404 Not found` and non-GET requests returned `405 Method not allowed` with `Allow: GET`.

The **AralHub LAN** scheduled task was restarted after checking that it points to this workspace. The updated server is listening on port 5000. Live HTTP probes now reach the material handlers: an unsigned GET returns the intended `401` sign-in response, and a POST with a valid CSRF token reaches the upload handler and returns the intended teacher-sign-in response instead of `405`. The live server also serves the new multi-department class picker.

The lecture form now supports selecting multiple departments and multiple year levels, with separate section selections for each. No class is selected automatically. Unchecking a department/year excludes its classes while preserving the selected file, text, and other class selections. A material shared with BSIT 1-A, BSCRIM 2-B, and BSN 3-C is visible to all three classes, and each student can submit their own file; other department/year/section combinations remain excluded.

Follow-up validation: 14 backend material tests and 3 feature browser checks passed. The updated browser checks also verified department/year exclusion, preserved selections after an upload error, and unchanged file/title during class changes. All eight desktop/tablet/mobile previews passed again with multiple departments selected, and Django's system check passed. Refresh an already-open browser with **Ctrl+F5** to load the updated screen.
