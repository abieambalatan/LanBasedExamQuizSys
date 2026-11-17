# Shared login and role based access

Open `/login` for student, teacher, or superadmin sign-in. Students enter their student ID (or an existing legacy username); teachers and superadmins enter their username. The server checks the password and active account record to determine the role. Public student registration only creates students. Teacher accounts are provisioned by the superadmin.

| Role | Dashboard | Allowed work |
| --- | --- | --- |
| Student | `/student` | Take assigned assessments, read class lecture materials, upload/replace their own activity files, view their own results |
| Teacher | `/teacher` | Manage their own assessments/materials, share with selected classes, review their students' submissions/results, manage students within their permitted departments |
| Superadmin | `/admin/` | Manage teachers, students, school options, and administrative result review; requires an active Django user with both staff and superuser flags |

`portal/authentication.py` defines the role permission map and fixed dashboard destinations. `POST /api/auth/login` returns the verified account, its role, permission metadata, and dashboard. `GET /api/auth/session` returns the current verified identity. Permission metadata describes the role; API handlers separately enforce role, record ownership, class recipients, and submission ownership. Browser controls and navigation do not grant authorization.

Dashboard HTML is protected before being served. Its bootstrap account is generated from the signed session and current database records, so refreshes retain the correct workspace without saving passwords or roles in browser storage. Student class membership is refreshed from the database. Archived or deleted accounts cannot sign in and lose dashboard/API access. Student requests cannot create materials or assessments, manage accounts, or access teacher/superadmin pages; teacher requests cannot submit as students or use superadmin controls.

Role fields, permission lists, `X-Portal-Role`, and document `portalRole` parameters are not trusted as authorization. The latter two only choose which signed workspace cookie to read. Successful shared sign-in clears the other student, teacher, and native admin cookies, so a previous privileged account does not remain accessible after signing in as a student in the same browser. Native superadmin access uses Django authentication; a portal session claiming `role=admin` is insufficient. Existing role-specific API login endpoints remain compatible with existing clients and teacher reauthentication while preserving unsaved assessments; all public sign-in links use `/login`.

All login/logout writes require CSRF protection. Successful sign-in flushes the target workspace's old session and rotates the CSRF token. Redirect destinations are fixed by the verified role; client `next`/redirect fields do not grant access or redirect to another host. Invalid credentials use a generic error. If the same identifier and password match multiple accounts, sign-in returns `409 ambiguous_credentials` so an administrator can assign distinct identifiers instead of silently selecting the more privileged account.

Validation: run `python -m unittest test_authentication test_app test_learning test_frontend test_database_configuration` using the project virtual environment. Shared-login tests exercise role detection, protected dashboards, bootstrap identity, client role/cookie tampering, privileged API denial, native superadmin checks, inactive accounts, CSRF, ambiguous credentials, and logout. Browser checks cover shared form behavior, failed-entry preservation, fixed role destinations, and dashboard reloads. No database migration is needed; roles use the existing student, teacher, and Django superuser account records.
