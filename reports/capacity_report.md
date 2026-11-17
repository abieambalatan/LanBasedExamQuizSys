# Django 200-student capacity check

Test date: October 19, 2026 (Asia/Singapore).

**PASS:** All 200 synthetic students completed every phase using the Django/Waitress backend.

| Workflow | Passed | Time for all 200 | 95th percentile |
| --- | ---: | ---: | ---: |
| Sign in with Django password verification and CSRF | 200/200 | 23.33 s | 22.71 s |
| Load dashboard, results, and the 50-question paper | 200/200 | 1.15 s | 1.12 s |
| Submit all students together | 200/200 | 2.33 s | 1.89 s |
| Retry already-saved submissions | 200/200 | 0.83 s | 0.43 s |

The test saved exactly 200 results with 200 correct scores, returned the same result IDs on retries, and passed SQLite integrity checks. The real exam.db checksum remained unchanged throughout this test.

Environment: Windows, Python 3.14.7, Django 5.2.18, Waitress 3.0.2, 8 logical CPU cores, 16 Waitress workers, SQLite WAL, and 50 questions across all four supported types.

Password verification used Django's pbkdf2_sha256 hasher with its installed defaults. Login is the slowest phase: a simultaneous 200-student sign-in took about 23.3 seconds. Password checks were not bypassed. CSRF token exchanges and signed session cookies were included. Submission bursts completed in about 2.3 seconds.

The measurement uses real loopback HTTP connections, temporary synthetic records, and a separate Waitress process. It establishes local server behavior for this workload; it does not measure physical Wi-Fi/LAN capacity or 200 browser rendering sessions.

Validation also includes 17 backend tests and seven headless browser tests. They cover legacy passwords, Django CSRF rotation and origin checks, database preservation, account permissions, four-part grading, student review restrictions, submission retries, interface controls, and TXT uploads.

The production database was backed up before migration. A row-by-row digest comparison in ../backups/native_admin_migration_report.json confirms that the migration retained all business records. The conversion adds Django migration metadata. Firewall and Task Scheduler configuration were not changed.

See load_test_django_results.json for the current measurements, ../docs/DJANGO_BACKEND.md for the Django structure, and ../docs/deployment_steps.txt for startup. load_test_results.json retains the earlier Flask measurements and is not the current Django report.
