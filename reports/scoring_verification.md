# Exam and quiz scoring verification

- Exams: 2 points for each correct answer.
- Quizzes: 1 point for each correct answer.
- Incorrect or unanswered questions: 0 points.
- Updated student question values, receipts, teacher builder type switching, answer reviews, and Excel/PDF point labels.
- Backend tests: 46 passed. Browser tests: 22 passed. Django system and migration-state checks passed.
- Applied migrations 0012 and 0013 to the configured PostgreSQL database after creating and verifying a backup.
- Corrected 31 saved quiz submissions among 32 results. Exam scores, percentages, answers, question records, and submission count were verified unchanged.
- Migration audit and backup location: `reports/quiz_one_point_migration.json`.
- The server was stopped during migration and was left stopped, preserving manual startup.
