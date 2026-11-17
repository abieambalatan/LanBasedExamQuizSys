# Live assessment workflow verification

Implemented teacher dashboard submission updates (3 seconds), existing live assessment results, student return notifications (5 seconds), original submission archiving, answer restoration, focus warnings, automatic submission retries, and a responsive native super admin dashboard (5 seconds).

Validation completed:

- Django system check: no issues.
- Migration state check: no ungenerated model changes.
- Backend suite: 44 tests passed, including ownership restrictions, preserved original answers, returned assessment access, stale attempt rejection, one-result retries, super admin permissions, and migration replay.
- Headless Edge suite: 21 tests passed, including live teacher updates, stale response handling, student return sync, continued returned answers across reload, ten-second warnings for exams and quizzes, offline automatic submission recovery, and existing assessment workflows.
- Seven desktop/tablet/mobile preview checks passed without horizontal overflow. Super admin header controls remain within the header. See `ui-previews/live-workflows-layout-checks.json` and the generated screenshots.
- Real HTTP load test: 200 synthetic students passed each of login, dashboard/open, simultaneous automatic submission, and submission replay. Exactly 200 correct results were saved, database integrity was `ok`, and the protected database file was unchanged. See `reports/live_workflows_load_test.json`.

The load test uses a temporary SQLite database and a separate Waitress process on loopback. It does not certify physical LAN/Wi-Fi capacity or a running PostgreSQL deployment. No production migration or server restart was performed.

Activation: restart with the existing configured server launcher, which applies migration `0012_submissionreturn`, then reload the student and teacher pages with Ctrl+F5. Keep the existing PostgreSQL launcher when using PostgreSQL.

The assessment guard detects browser focus and visibility changes. It cannot block operating-system shortcuts, show its popup over another application, or guarantee execution while the browser is suspended. The saved warning deadline is enforced when execution resumes.
