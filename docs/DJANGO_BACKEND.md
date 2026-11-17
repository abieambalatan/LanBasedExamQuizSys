# Django backend

The portal runs Django 5.2 LTS with Waitress and PostgreSQL. Normal server startup does not support SQLite. Students, teachers, and superadmins share the sign-in page at `/login`; the server sends each verified account to its permitted dashboard.

## Django Superadmin

`/admin/` is the native Django Superadmin panel. Everyone signs in at `/login` using a teacher/superadmin username or student ID and a password. `POST /api/auth/login` verifies the credentials and derives the role from the stored account, then redirects students to `/student`, teachers to `/teacher`, and Django superadmins to `/admin/`. No role selector or submitted role grants access. The previous `/administrator` and `/administrator.html` addresses and `/admin/login/` redirect to `/login`. Sign-out and completed student registration return to the same shared login page. See `docs/RBAC.md` for the permission boundaries.

The panel supports creating and editing teacher accounts, assigning their departments and passwords, resetting teacher/student passwords, archiving/restoring teachers and student accounts, inspecting assessment records, reviewing answers, and returning selected submissions after confirmation. To create an account, open **Teachers** in `/admin/` and select **Add teacher**; set the teacher's username, password, and departments there. Public teacher self-signup is disabled. **School options** manages departments and each department's section count; sections are generated as A through the selected letter. Year levels are fixed at 1st–4th Year and are shared across departments. Reducing a department's section count is blocked when students, exams, target classes, or results still use a section that would be removed. Renaming a department updates existing records, and deletion is available only when it is unused and another department remains. Student accounts marked **Delete duplicate** are archived, not erased; their saved results remain, they cannot sign in, and only the superadmin or a teacher assigned to that department can view and restore them. The Django **Students** page also has archive/restore actions for the superadmin. Archiving teachers keeps assessments and results. Teacher usernames remain fixed after creation so assessment ownership stays linked.

Student signup uses separate `firstName`, `lastName`, and optional `middleInitial` fields, along with student ID, program/department, year level, section, and password. Students do not choose teachers. Published exams and quizzes are available to students matching the teacher's selected programs/departments, year, and section, regardless of any older teacher enrollment. The server enforces those scopes when listing, opening, and submitting assessments. Teachers manage student accounts within their assigned programs. Existing full names and passwords are preserved; the student-name migration adds fields for new accounts without guessing how to split older names.

Only active Django users with both `is_staff` and `is_superuser` may access this panel. An ordinary staff account or a legacy portal `account.role=admin` session does not grant access. Django handles superadmin passwords, permissions, session validation, and the management audit log.

The initial superuser is created once from the existing configured administrator username/password by `manage.py bootstrap_superadmin`, which the launcher runs after migrations. It never resets an existing user's password or promotes an existing non-superuser. To create an additional superadmin, use `manage.py createsuperuser`. To change a Django user's password, use the Django Users page or `manage.py changepassword USERNAME`. Updating the old administrator environment password after provisioning does not reset a Django account.

The application serves Django's bundled admin CSS/JavaScript locally under `/static/admin/`, including with `DEBUG=False` and no internet connection.

## Lecture materials and activity file submissions

Student activity-file uploads and replacements are available to teachers in **Lecture materials** under **View submissions**. Uploads are stored as submissions without creating teacher notifications.

The shared interface uses a purple/lavender palette for login, landing, student/teacher workspaces, assessments, and the Django administration console. Success, warning, and error indicators retain distinct colors. Fonts and icons remain local to the LAN server.

Teachers can open **Lecture materials** in the sidebar and expand **Share lecture material or an activity**. Enter a title, subject, and optional instructions. Under **Share with these classes**, check every department/course represented in the class, then choose each department's year levels and exact sections. One material can be shared across multiple departments and years (for example BSIT 1-A and BSCRIM 2-B). Only students in those selected classes can view the material and submit their work. Department/year toggles preserve the selected file and entered text; unchecking a department or year excludes its classes from publication. Select **Request a student file submission for this activity** to collect completed work. Upload one material per entry; share more entries for additional attachments.

Students open **Lecture materials** from their dashboard or sidebar. They can open/download files assigned to their exact class and upload a completed activity file when requested. Uploading again replaces their previous file. Teachers use **View submissions** on the material to open/download each student's work with their name, ID, class, and submission time.

Supported formats are PDF, Word (`.doc`, `.docx`), PowerPoint (`.ppt`, `.pptx`), and Excel (`.xls`, `.xlsx`), with a 25 MB limit per file. PDFs open in a browser tab; Office documents download to open in a locally installed application. No internet or external document viewer is needed. Failed uploads leave the selected file and form entries available for retry. File extension and basic format validation run on the server, and all writes require CSRF protection.

Migration `0015_lecture_materials` adds separate material, class-recipient, and file-submission tables. Migration `0017_remove_activity_submission_notifications` removes the teacher notification table. The normal launcher applies migrations automatically on the next start. File contents live in the private `uploads/` directory, outside the frontend file tree; metadata lives in PostgreSQL. `EXAM_PORTAL_UPLOAD_ROOT` can set another absolute storage directory. Back up both the database and this directory. File URLs verify the signed workspace session, material ownership, class assignment, and submission owner. Deleted/archived teachers' materials are hidden from students. Deleting a material removes its submissions and files; permanent account deletion also cleans associated files after the database commits. Department renames and section-reduction protection include lecture recipients.

When changing Python routes or adding migrations, restart the running **AralHub LAN** task/server, then refresh the browser. Waitress does not reload Python modules automatically. An old process can serve updated frontend files while still returning `Not found` for new API GETs and `Method not allowed` for their POSTs through the old frontend catch-all route.

Run the backend and browser checks with:

```powershell
.\.venv\Scripts\python.exe -m unittest test_app test_database_configuration test_learning test_frontend
.\.venv\Scripts\python.exe preview_ui.py --screens teacher-materials student-materials
```

## Start the LAN server

Install dependencies into the project virtual environment, then use the existing launcher:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\start_aralhub.bat
```

The launcher uses `app.py`, applies Django migrations, and starts Waitress on port 5000. Run one instance. Students open `http://SERVER-IP:5000`.

Both `start_aralhub.bat` and the **AralHub LAN** scheduled task use `start_aralhub_postgresql.ps1` and the stored PostgreSQL credentials. Missing credentials stop startup; there is no SQLite fallback. `EXAM_PORTAL_DB_ENGINE=sqlite` and `EXAM_PORTAL_DB_PATH` are rejected by production settings. Direct Python, WSGI, ASGI, and management commands require the PostgreSQL environment settings listed below.

## Project structure

| Location | Purpose |
| --- | --- |
| `exam_portal/settings.py` | PostgreSQL-only production database settings |
| `exam_portal/base_settings.py` | Shared hosts, cookies, middleware, and timezone |
| `exam_portal/test_settings.py` | Isolated legacy test fixtures restricted to the OS temporary directory |
| `exam_portal/wsgi.py` | Django application served by Waitress |
| `portal/urls.py` | Frontend URLs and API method dispatch |
| `portal/views.py` | Accounts, assessments, grading, results, and frontend files |
| `portal/admin.py` | Native Django teacher/student management and result review |
| `portal/models.py` | ORM mappings to classroom records and managed school options |
| `portal/db.py` | Assessment schema and request-scoped PostgreSQL connections |
| `portal/migrations/0001_existing_schema.py` | Adopts existing tables without recreating them |
| `portal/migrations/0005_school_options.py` | Creates and seeds configurable departments, year levels, and sections |
| `portal/migrations/0006_department_section_counts.py` | Keeps year levels fixed and configures sections per department |
| `portal/migrations/0007_student_archive.py` | Adds reversible student-account archiving without deleting results |
| `portal/migrations/0008_remove_legacy_student_teachers.py` | Drops the retired student-to-teacher enrollment table |
| `portal/migrations/0009_department_year_sections.py` | Adds section-count overrides for each department's year levels |
| `portal/security.py` | Django password hashing and legacy hash verification |
| `portal/middleware.py` | Connection cleanup, database error responses, and API cache protection |
| `app.py` | Production startup and Waitress settings |
| `manage.py` | Standard Django management commands |

Business APIs use parameterized SQL and PostgreSQL transactions. Django Admin uses unmanaged ORM models mapped to those same tables, so it does not duplicate or rebuild the existing records. Native Django authentication, content types, permissions, sessions, and admin audit tables are added by migrations.

Migration `0008_remove_legacy_student_teachers` removes `student_teachers`, which belonged to the retired student enrollment flow. Assessment access uses departments, year levels, and sections; teacher access uses `teacher_departments`. Schema initialization no longer creates or fills the retired table, and PostgreSQL imports skip it in older SQLite sources. Take a database backup before applying this migration; its deleted enrollment rows can only be recovered from that backup. Django framework tables, including empty authentication/group/session tables, remain managed by Django.

School options now supports section counts for each year level. Open a department in **Superadmin → School options** and set **1st Year sections**, **2nd Year sections**, and so on. For example, BSIT can have 3 sections (A–C) in 1st Year and 4 sections (A–D) in 2nd Year. Blank overrides use the department's default section count. The migration preserves existing counts. Reductions are blocked only when the affected year has students, results, or assessment recipients in a section that would be removed; records with an unknown year are protected for all years. The activity builder presents separate year groups with explicit class labels such as **BSIT 1-A** and **BSIT 2-D**, and preserves each year's section selections when editing. Student signup and teacher student-directory filters also use the selected department and year.

## Existing data and credentials

The live database is PostgreSQL, configured through `.secrets/postgres.json` and the encrypted credential file. Student and teacher IDs, questions, answer keys, results, and passwords remain in PostgreSQL. Existing Werkzeug scrypt/PBKDF2 hashes can still authenticate. New and reset passwords use Django hashing. SQLite files are retired and are never used by the normal server.

Users sign in again after the switch because Django uses its own signed session cookie. The private `.django_secret_key` keeps those sessions valid across server restarts. Keep that file private and retain it with the server configuration. `EXAM_PORTAL_SECRET_KEY` overrides it when explicitly configured.

The pre-migration source archive and database snapshot are in `backups/`. `../backups/native_admin_migration_report.json` records row counts and hashes before and after adopting the actual database.

## LAN configuration

Existing `EXAM_PORTAL_HOST`, `EXAM_PORTAL_PORT`, `EXAM_PORTAL_THREADS`, `EXAM_PORTAL_ADMIN_USERNAME`, and `EXAM_PORTAL_ADMIN_PASSWORD` settings still work.

Django accepts localhost and the server's detected hostname/IP addresses by default. Set `EXAM_PORTAL_ALLOWED_HOSTS` to a comma-separated list when using a custom LAN hostname or IP. Include the hostname/IP only, without a scheme or port. Production settings reject `EXAM_PORTAL_DB_PATH`; all database configuration uses PostgreSQL connection settings.

If an HTTPS reverse proxy is configured, `EXAM_PORTAL_HTTPS=1` marks session and CSRF cookies as secure. `EXAM_PORTAL_CSRF_TRUSTED_ORIGINS` accepts comma-separated origins for an explicitly configured proxy deployment. Direct classroom HTTP access uses the default settings.

## PostgreSQL backend

PostgreSQL is required. The local installation uses PostgreSQL on `127.0.0.1:5432`, database `aralhub`, and role `aralhub_app`. Normal startup applies Django migrations to that database and does not create backups or copy SQLite data. The old `migrate_postgresql.ps1` filename is retained as a compatibility entry point to the same PostgreSQL launcher; its former SQLite backup and import steps have been removed.

The launcher decrypts the existing Windows credential and supplies these variables to the server. For manual management commands in a configured PowerShell session:

```powershell
$env:EXAM_PORTAL_DB_ENGINE = "postgresql"
$env:EXAM_PORTAL_DB_NAME = "aralhub"
$env:EXAM_PORTAL_DB_USER = "aralhub_app"
$env:EXAM_PORTAL_DB_PASSWORD = Read-Host "PostgreSQL application password"
$env:EXAM_PORTAL_DB_HOST = "127.0.0.1"
$env:EXAM_PORTAL_DB_PORT = "5432"
.\.venv\Scripts\python.exe manage.py check
```

Do not publish or log the database password. Student computers connect to Waitress on port 5000, not to PostgreSQL directly.

To configure manual PostgreSQL startup through Task Scheduler, first stop any manually running AralHub server. Open an elevated PowerShell window in the project folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_lan_server.ps1
```

The setup prompts for the PostgreSQL database, application role, and PostgreSQL password, but does not require a Windows password. It verifies the PostgreSQL login and Django configuration before registering the `AralHub LAN` task for the current Windows account, with no boot or sign-in triggers. Rerunning setup replaces the old automatic startup configuration. The PostgreSQL password is stored in a Windows DPAPI-encrypted credential file under `.secrets/`, protected for the current Windows account and SYSTEM; this file is ignored by Git. Non-secret connection settings are stored alongside it with the same file permissions. The task runs only while that same Windows account is signed in, allowing Windows to decrypt the credential without saving the Windows password.

After signing in, open Task Scheduler > Task Scheduler Library, select `AralHub LAN`, and click **Run**. PowerShell stays hidden. When started, the task waits for PostgreSQL, checks for port conflicts, applies Django migrations, verifies the superadmin, runs the system check, and starts Waitress. Clients can then open `http://SERVER-IP:5000`. Startup logs are written under `logs/`. Use **End** in Task Scheduler to stop the server. After restarting the PC, run the task again to make the portal available. Do not start a second server manually while the task is running.

For an already installed task, run `powershell -ExecutionPolicy Bypass -File .\set_manual_startup.ps1` in administrator PowerShell to apply this behavior without repeating database setup or stopping a running server. It backs up the previous task XML under `backups/` and preserves the task's Windows account.

## Browser/API protection

All POST, PUT, and DELETE requests use Django CSRF protection, including sign-in and registration. The shared browser helper fetches `/api/csrf`, sends its `csrfToken` as `X-CSRFToken`, and refreshes it after login/logout. Read-only requests do not need a token. Direct API clients must preserve both the CSRF cookie and session cookie. Role-scoped clients must send X-Portal-Role: student or teacher on every API request; legacy clients without the header keep the original single-session behavior. A confirmed csrf_failed response is retried once with a fresh token because Django rejected it before executing the action; ordinary permission errors and unauthenticated sessions are not retried as writes.

Questions remain shuffled within each part. Students can review their own submitted exam or quiz answers, correct answers, and awarded points. Reviews require a saved submission and enforce student ownership; active assessment payloads and submission receipts omit answer keys. Teachers can review results belonging to their assessments. Submission retries preserve the same attempt key to prevent duplicate results.

Publishing distinguishes an expired staff session (`401`, `staff_session_expired`) from a browser currently signed in with a non-teacher account (`403`, `teacher_required`) or a different teacher (`teacher_account_changed`). The activity builder offers **Sign in to publish** inside the editor, preserving imported questions and assessment details in the current page. After teacher sign-in, select Publish again. Sign-in as a superadmin does not bypass teacher ownership. Student and teacher pages now send an X-Portal-Role header and use independent signed cookies (aralhub_session_student and aralhub_session_teacher); native Django superadmin keeps aralhub_session. Signing into or out of one role does not replace the other role's session. Existing matching student/teacher cookies migrate once into their role cookie and the legacy cookie is retired so logout cannot restore it. Questions in an unpublished editor remain in page memory and are not saved across a page refresh.

Teacher activity results update automatically every three seconds while the results page is visible. Class rosters refresh periodically alongside submissions. Updates preserve department/year/section filters, collapsed class progress, and scroll position. Hidden tabs, confirmation dialogs, and other workspace screens pause polling; connection failures retain the displayed scores and retry automatically. **Refresh now** remains available for an immediate check. Late responses cannot navigate a teacher back to a results page they have left.

The student exam workspace fits the viewport with the timer, question-number navigator, and Previous/Next/Submit controls kept visible. Question numbers use pages sized for the available screen, with arrows to reach later numbers. Long questions and answer choices scroll inside the question panel, leaving navigation accessible. Resizing keeps the current question and answers.

## Verification

### Live assessments and teacher returns

Scoring follows activity and question type: **exam Multiple Choice and Identification questions award 2 points each; True/False and Matching Type award 1 point each. All quiz questions award 1 point each.** The server calculates weighted totals and percentages. Student instructions, receipts, reviews, the teacher builder, and exports display this policy. Migration `0014_question_type_points` corrects saved original two-point exam results and returned snapshots when their answers still match the assessment question IDs. It preserves answers and skips already corrected totals. Historical assessments whose question IDs changed are left untouched because their original grading cannot safely be reconstructed. No backup is created by this migration.

The teacher's My assessments dashboard updates assessment attempt counts every three seconds. Recent submissions are not displayed on the dashboard. Open an assessment's results to review student answers; **Return exam** and **Return quiz** preserve the original receipt and answers in the new `portal_submissionreturn` archive before reopening the assessment. Only the assessment owner or a Django superadmin can return a submission. Staff must manually enter the matching student ID before each return; the API verifies `studentId` against the saved submission inside the return transaction and rejects missing or mismatched IDs without changing the result. The native super admin action requires a matching ID for every selected submission before returning any of them. A fresh submission closes the pending return, and retries with an archived attempt key cannot overwrite the teacher's return.

Student home pages and submission receipts check for changes every five seconds while visible. Returned assessments are labeled **Returned by teacher**. Continuing restores the submitted answers and starts a fresh assessment time allowance. Reloading an already continued attempt preserves subsequent edits, its timer, and submission key. The original return history is available under **Superadmin > Returned submissions**.

Both exams and quizzes monitor window focus and page visibility. Leaving the tab, minimizing, or switching apps displays a ten-second warning in the assessment page. Returning and choosing **Continue assessment** before it expires resumes the attempt. Otherwise the current answers are automatically submitted with the `tab_switch` reason. The warning deadline and pending submission are saved locally across reloads. Automatic submissions retry after connection failures with the same attempt key; answers remain locked while awaiting submission. Browsers cannot prevent operating-system shortcuts or display an in-page popup over another application, and suspended background tabs may delay submission until the browser resumes. This is browser monitoring, not an operating-system kiosk lock.

The native super admin has a responsive dashboard, campus totals, and five-second refreshes. Recent submission lists are not displayed on either dashboard; individual assessment results and reviews remain available. All assets are local, and existing Django permissions and CSRF protection remain in force.

Exam and quiz attempts record browser activity locally alongside saved answers and send updates to the server during the attempt. Event updates are batched for 150 milliseconds, with immediate delivery on visibility changes and a five-second heartbeat. Failed requests time out after ten seconds and retry while the page is active or reconnects; the local log is preserved. The teacher's **Results > Live exam monitoring** panel polls every three seconds and shows separate counts for window focus losses, page hides and warnings, the last reported browser state, and server receipt time. **Activity log** opens a timeline that also refreshes while the Results page is visible. After thirty seconds without a heartbeat, the status becomes **No recent update** instead of implying a current browser state. The final **Browser activity** results column and **Review** also retain these counts and the full timeline. Focus losses and page hides can overlap during one departure and must not be added together. These observations cannot distinguish Alt+Tab from minimize, tab switching, or interaction with browser controls, and do not prove cheating. Event timestamps come from the student's device; the receipt timestamp comes from the server. This addition preserves the existing ten-second warning and automatic submission behavior.

Migration `0018_result_activity_log` adds a nullable result activity column; `0019_assessment_activity_monitor` adds the per-student, per-assessment, per-attempt server log. Both preserve existing records and support recovery of migration history. Older submissions display **Not recorded** rather than zero departures. Resuming an older draft produces a partial log. Monitoring writes use the authenticated student identity and class assignment; reads require the assessment owner or superadmin. Student locks serialize recording and submission; repeated or older updates cannot erase accepted events, and submission retains already received server evidence even if the browser sends an older copy. Returning a submission retains the original log and closes that attempt to further updates; a fresh attempt gets a separate record. Permanent student deletion removes its monitor records. Only the first 2,000 events are retained, with an explicit limit notice. Closing the browser retains already delivered events on the server and unsent events on the device; time while the browser is closed is not monitored. Deploy through the configured PostgreSQL launcher so both migrations run before the updated backend starts, and load the updated student page before starting an attempt. The student page displays whether its latest activity has been confirmed by the server or is waiting to sync.

Migration `0012_submissionreturn` adds the return archive without changing existing submissions. Start or restart through the existing configured launcher to apply it before serving the updated frontend. Keep the configured PostgreSQL launcher for a PostgreSQL installation.

```powershell
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe -m unittest -v test_database_configuration test_app test_frontend
.\.venv\Scripts\python.exe -m unittest -v test_live_monitoring
.\.venv\Scripts\python.exe load_test.py --users 200 --output reports\load_test_django_results.json
```

Configuration checks create no databases. Legacy application tests and the isolated load test explicitly select `exam_portal.test_settings`; their synthetic SQLite fixtures are restricted to the OS temporary directory outside the project and are removed after the tests. The production launcher refuses test settings. Tests use synthetic accounts. The load test uses actual Django/Waitress HTTP requests, password verification, CSRF tokens, cookies, and simultaneous submissions. Its report separates the loopback server workload from physical LAN/Wi-Fi capacity.

Student workspace refreshes stop on an expired login and display the student sign-in form with a session-expired message. Saved answers remain on the device. Temporary network/server failures retain displayed assessments and retry with a longer delay; permanent permission failures show the actual error and a Try again action. Teacher Return exam/quiz does not ask for fresh credentials while the independent teacher session is valid.


Teacher deletion of a student account is recoverable: it disables sign-in and keeps assessment records. Only the super admin can retrieve teacher-deleted students. Teacher deletion still requires typing `DELETE` and is restricted to assigned programs.

Super admin deletion of either a teacher or student account is **permanent**, including individual buttons, bulk actions, and delete API calls. Confirmations require `DELETE` and explicitly state that the account cannot be retrieved. Permanent deletion removes the account row and password hash; teacher deletion also removes their program memberships. Permanently deleting a student also deletes all their exam results and returned-submission records. Teacher-deleted student accounts remain recoverable and retain their results. Teacher account deletion keeps historical assessments and results with retired ownership references, so reused student IDs or teacher usernames cannot inherit them. Returned-attempt snapshots use the same retired references. Retired references are reserved and retained during legacy orphan cleanup. Signed cookies are rejected once their account ID no longer exists; replacement accounts receive new IDs. Teacher sessions bind to the teacher's account ID; teacher sessions issued before this security update require a one-time sign-in. Previously disabled accounts are not automatically purged; the super admin can either retrieve or permanently delete them. The status filter identifies disabled accounts, and inactivity alone does not automatically delete an account.


The native super admin no longer includes Results or Returned submissions. Their registered admin pages, navigation links, submission statistics, and return action are removed. The dashboard now contains only active students, active teachers, and assessments. Submission records remain available to the appropriate teacher and student through their existing workspaces; no database records are deleted by this interface change.
