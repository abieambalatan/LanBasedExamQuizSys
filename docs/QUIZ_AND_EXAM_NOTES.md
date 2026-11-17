# Quiz and Exam Notes

## Question types

The system supports four question types for both quizzes and exams:

1. **Part 1 - Multiple Choice:** Choose the correct answer from four choices.
2. **Part 2 - Identification:** Type the correct answer. Accepted alternative answers may be configured.
3. **Part 3 - True or False:** Decide whether the statement is true or false.
4. **Part 4 - Matching Type:** Match each prompt to the correct choice. Each prompt counts as one question.

Parts may contain different numbers of questions. Unused parts may be omitted.

## Scoring

| Question type | Quiz | Exam |
|---|---:|---:|
| Multiple Choice | 1 point | 2 points |
| Identification | 1 point | 2 points |
| True or False | 1 point | 1 point |
| Matching Type | 1 point per prompt | 1 point per prompt |

- Correct answers earn the points listed above.
- Incorrect answers earn 0 points.
- The total possible score is the sum of all question points.
- The earned score is the sum of points awarded for correct answers.
- The percentage calculation is: (earned points / total possible points) x 100.
- Although the server calculates percentages, results pages and reports display scores without percentage ratings. Students receive a score-only submission receipt.

## Example

For an assessment with 10 questions of each type:

- **Quiz:** 10 + 10 + 10 + 10 = **40 possible points**.
- **Exam:** 20 + 20 + 10 + 10 = **60 possible points**.

## References

- Question types and TXT format: `files/js/exam-format.js` and `docs/TXT_EXAM_FORMAT.md`.
- Scoring rules: `portal/constants.py`.
- Scoring and result display documentation: `docs/DJANGO_BACKEND.md` and `docs/TXT_EXAM_FORMAT.md`.
