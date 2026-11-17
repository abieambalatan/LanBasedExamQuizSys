# AralHub entity relationship diagram

Based on the current application schema through migration `0019_assessment_activity_monitor` (12 November 2026). This documents the schema defined in source; it does not verify the migration state of a running database.

## Reading the diagram

- `PK`: primary key; multiple PK fields in one table form a composite primary key.
- `UK`: a single-column unique constraint. Composite unique constraints are described in field comments and below.
- `FK`: a database-enforced foreign key. Only the two `material_id` fields have declared foreign keys in the application schema.
- Solid lines show declared foreign keys; dotted lines show logical references maintained by application code. This line style is a documentation convention, not a claim about identifying relationships.
- `||` means one, `|o` means zero or one, and `o{` means zero or many. Logical cardinalities describe intended application associations; missing or historical records can leave those references unresolved.
- Actual database table names are used. Types reflect PostgreSQL storage broadly; varchar lengths, defaults, nullability, and check constraints are not exhaustively displayed.

## Diagram

```mermaid
erDiagram
    direction LR

    teachers |o..o{ students : "legacy teacher_username"
    teachers |o..o{ exams : "username = created_by"
    teachers ||..o{ teacher_departments : "username = teacher_username"
    teachers |o..o{ results : "username = teacher_username"
    teachers ||..o{ portal_lecturematerial : "id = teacher_id"
    exams ||..o{ questions : "id = exam_id"
    exams ||..o{ exam_departments : "id = exam_id"
    exams ||..o{ exam_target_classes : "id = exam_id"
    exams ||..o{ results : "id = exam_id"
    students ||..o{ results : "roll_no = roll_no"
    students ||..o{ portal_activityfilesubmission : "id = student_id"
    portal_lecturematerial ||--o{ portal_lectureclass : "id = material_id FK"
    portal_lecturematerial ||--o{ portal_activityfilesubmission : "id = material_id FK"
    exams ||..o{ portal_assessmentactivity : "id = exam_id"
    students ||..o{ portal_assessmentactivity : "id = student_id"
    results |o..o{ portal_assessmentactivity : "id = result_id when present"
    exams ||..o{ portal_submissionreturn : "id = exam_id"
    students ||..o{ portal_submissionreturn : "roll_no = roll_no"
    results |o..o{ portal_submissionreturn : "id = resubmitted_id when present"

    teachers {
        text id PK
        text name
        text username UK
        text department
        text password_hash
        text created_at
        text deleted_at "nullable"
    }
    students {
        text id PK
        text name
        text first_name
        text last_name
        text middle_initial
        text roll_no UK
        text department
        text username "nullable"
        text password_hash "nullable"
        text teacher_username "legacy logical reference"
        text section
        text year_level
        text created_at
        text deleted_at "nullable"
    }
    teacher_departments {
        text teacher_username PK "composite PK; logical reference"
        text department PK "composite PK"
    }
    exams {
        text id PK
        text title
        integer duration
        text department
        text created_by "logical reference to teachers.username"
        text year_level
        text subject
        text section_scope
        text activity_type
        text created_at
    }
    exam_departments {
        text exam_id PK "composite PK; logical reference"
        text department PK "composite PK"
    }
    exam_target_classes {
        text exam_id PK "composite PK; logical reference"
        text department PK "composite PK"
        text year_level PK "composite PK"
        text section PK "composite PK"
    }
    questions {
        text id PK
        text exam_id "logical reference"
        integer position
        integer part
        text type
        text text
        text option_a
        text option_b
        text option_c
        text option_d
        integer correct
        text answer_text
        text alternatives_json "JSON encoded text"
        text options_json "JSON encoded text"
    }
    results {
        text id PK
        text exam_id "logical reference; composite unique with roll_no"
        text exam_title "snapshot"
        text name "snapshot"
        text roll_no "logical reference; composite unique with exam_id"
        integer score
        integer total
        real percent
        text answers_json "JSON encoded text"
        text submitted_at
        integer time_taken_sec
        integer auto_submitted
        text submit_reason
        text teacher_username "logical reference"
        text section "snapshot"
        text department "snapshot"
        text year_level "snapshot"
        text submission_key
        text activity_log_json "nullable JSON encoded text"
    }
    portal_schooloption {
        bigint id PK
        varchar category "composite unique with value"
        varchar value "composite unique with category"
        integer position
        smallint section_count
        jsonb year_section_counts
    }
    portal_submissionreturn {
        varchar id PK
        text result_id UK "historical ID; original result is deleted"
        text exam_id "logical reference"
        text roll_no "logical reference"
        text snapshot "JSON encoded original result"
        text returned_by "staff username"
        text returned_at
        text resubmitted_id "logical reference; empty until resubmitted"
    }
    portal_lecturematerial {
        varchar id PK
        text teacher_id "logical reference"
        varchar title
        varchar subject
        text instructions
        boolean requires_submission
        varchar file "stored file path"
        varchar filename
        bigint size
        timestamptz created_at
    }
    portal_lectureclass {
        bigint id PK
        varchar material_id FK "composite unique with department year_level section"
        varchar department
        varchar year_level
        varchar section
    }
    portal_activityfilesubmission {
        varchar id PK
        varchar material_id FK "composite unique with student_id"
        text student_id "logical reference"
        varchar file "stored file path"
        varchar filename
        bigint size
        timestamptz submitted_at
    }
    portal_assessmentactivity {
        varchar id PK
        text exam_id "logical reference; composite unique"
        text student_id "logical reference; composite unique"
        varchar submission_key "composite unique with exam_id student_id"
        text activity_log_json "JSON encoded text"
        float created_at
        float received_at
        boolean page_hidden
        boolean window_focused
        text result_id "logical reference; empty before submission"
    }
```

## Constraints and implementation notes

| Table | Composite unique columns |
| --- | --- |
| `results` | `exam_id`, `roll_no` |
| `portal_schooloption` | `category`, `value` |
| `portal_lectureclass` | `material_id`, `department`, `year_level`, `section` |
| `portal_activityfilesubmission` | `material_id`, `student_id` |
| `portal_assessmentactivity` | `exam_id`, `student_id`, `submission_key` |

- `teachers.username` identifies assessment creators and teacher department assignments. Lecture materials instead reference `teachers.id`.
- Results reference students by the unique `students.roll_no`; file submissions and assessment monitoring reference `students.id`.
- Returning a submission copies its original result into `portal_submissionreturn.snapshot`, records the original `result_id`, and deletes the original row from `results`. For that reason, the historical `result_id` is not drawn as a live relationship. `resubmitted_id` can later identify a replacement result.
- `returned_by` records a staff username. Staff can include administrators, so it is not presented as a mandatory teacher relationship.
- Assessment and lecture access use matching `department`, `year_level`, and `section` values. There is no independent class entity or class foreign key. `students.teacher_username` is a legacy field, not the current enrollment mechanism.
- `portal_schooloption` stores configurable department values and section counts. These values are used by application validation, without a declared foreign key from department columns. Legacy scope fields can also contain `ALL` or an empty value, so this table is intentionally shown independently.
- Answers, question alternatives, return snapshots, and activity logs stored in text columns contain JSON; they are not separate relational tables. Uploaded files are stored outside the database; their paths and metadata are stored here.
- Framework tables for Django authentication, permissions, sessions, content types, admin logs, and migration history are outside this application ERD. Removed tables `student_teachers` and `portal_activitysubmissionnotification` are excluded.

## Sources

- [Core schema and compatibility additions](../portal/db.py)
- [Assessment target class schema](../portal/targets.py)
- [Current Django models](../portal/models.py)
- [Schema migrations](../portal/migrations/)
- [Submission return lifecycle](../portal/submissions.py)

Editable Mermaid source: [ERD.mmd](ERD.mmd).
