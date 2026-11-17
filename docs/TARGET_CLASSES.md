# Shared assessments across classes

Teachers create one assessment for a subject and add its recipients under **Target classes**. Each department row can select multiple year levels and sections; every selected year is combined with every selected section. For example, a BSIT row selecting 2nd Year and 3rd Year plus sections A and B targets those four class combinations.

- Add a department row, then select multiple year levels and sections in that row. Every selected year is combined with every selected section (for example, 2 years and 3 sections targets 6 classes). Teachers can target any department configured by the superadmin.
- The superadmin sets each department's section count in **School options**; the allowed sections are A through that letter. Year levels are shared and fixed at 1st–4th Year.
- Students see the assessment in their own year and section. The server checks the complete combination when listing, opening, and submitting an assessment.
- Each student submits independently. The existing one-submission rule, safe submission retries, and teacher-approved reopening still apply.
- **View results** includes class submission counts. **View scores** selects that exact department, year, and section. **Refresh results** reloads submissions and student rosters. “Awaiting submission” means a student has no saved submission; it does not claim whether that student has started the activity.
- Department, year, and section filters also apply to Excel and PDF exports. Exports group records by the student's class.
- Submitted results store the student's department, year, and section at submission time. Editing targets or promoting a student does not relabel previous submissions.

Existing assessments retain their original recipients. Migration `0004_exam_target_classes` adds the target-class table and fills the year of older results from the assessment's existing year. Unknown historical years remain blank. The migration does not remove student accounts, assessments, questions, or results.

The existing server launchers apply pending migrations before starting. Restart the portal after updating its Python code, then reload browsers with Ctrl+F5.

## API

`POST /api/exams` and `PUT /api/exams/{id}` accept `targetClasses` alongside the title, subject, duration, activity type, and questions:

```json
{
  "targetClasses": [
    {"department": "BSIT", "yearLevel": "2nd Year", "section": "A"},
    {"department": "BSCRIM", "yearLevel": "1st Year", "section": "B"}
  ]
}
```

An explicitly empty or invalid target list is rejected. The teacher interface expands each department's selected year/section combinations to exact class recipients before saving. A teacher can create or edit target classes in any department configured by the superadmin; department assignments on the teacher account do not limit exam recipients. Sections must exist in that department and year levels are fixed at 1st–4th Year. Duplicate combinations are rejected, and up to 120 class combinations are supported. Older clients can still submit the previous `departments`, `yearLevel`, and `sectionScope` fields; these are expanded into complete class combinations. When `targetClasses` is present, it defines the recipients.

Teacher assessment responses include `targetClasses`. `GET /api/results` supports `department`, `yearLevel`, and `section` together. Teacher ownership checks apply to editing, submissions, results, and answer reviews.
