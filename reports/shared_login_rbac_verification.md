# Shared login and RBAC verification

Verified on 2026-11-11 (Asia/Singapore).

Students and teachers now use `/login`. The server verifies username/student ID and password, then sends the verified role to `/student` or `/teacher`. Native Django superadmins can use the same form to reach `/admin/`. The form has no role selector. `/administrator`, `/administrator.html`, and Django's login URL redirect to the shared page.

Roles and permissions derive from current account records. Protected dashboard HTML receives only the verified public account profile. Existing API checks enforce teacher ownership, student class recipients, submission ownership, and superadmin privileges. Successful shared sign-in removes the browser's previous teacher/student/admin cookies. A student signing in after a teacher or superadmin cannot continue using the earlier privileged workspace. Student class changes and archived/deleted accounts take effect on the next server check.

| Validation | Result |
| --- | --- |
| `test_app`, `test_authentication`, `test_learning`, `test_database_configuration` | 86 passed |
| Browser regression cases | 34 verified using Edge DevTools and targeted reruns |
| Shared login at 320, 390, 768, and 1440 px, including old staff-login preview aliases | Six layouts passed; no horizontal overflow |
| Real PostgreSQL login, dashboard/API role boundaries, lecture files, submissions, replacement concurrency, and cleanup | Passed in a disposable schema |
| Django system check and migration consistency | Passed; no model migration needed |
| Live LAN server after scheduled-task restart | Shared login and protected routes verified |

Authentication checks include automatic role detection, ignored client role/permission fields, a student cookie placed in the teacher-cookie slot, blocked teacher/admin actions for students, blocked admin actions for teachers, native superuser requirements, expired/archived accounts, CSRF rotation and logout, ambiguous credentials, class refresh, and replacement of previously privileged browser sessions. Browser checks include login error preservation, fixed role destinations, dashboard bootstrap after navigation, signup completion, expired-session return, and existing classroom features.

The **AralHub LAN** scheduled task was restarted after validating its launcher path. Live HTTP checks verified `/login`, legacy redirects, unsigned `/student` and `/teacher` redirects, unsigned session responses, rejected login without CSRF, and generic invalid-credential handling. No real user's password was used or changed. The PostgreSQL verification used synthetic accounts in a temporary schema and removed its schema/files afterwards.

The updated HTML requests a versioned shared script to avoid mixing the new login page with an older cached helper. Users with an already-open page can reload with **Ctrl+F5**. Full role and usage documentation is in `docs/RBAC.md`.
