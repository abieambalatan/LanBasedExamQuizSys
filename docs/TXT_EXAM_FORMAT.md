# Upload exam questions from a TXT file

In the teacher workspace, choose **Create activity** or **Edit activity**, open **Upload questions from TXT**, and select a `.txt` file. The upload replaces the draft's question list. Review the questions and click **Publish exam** or **Save changes**.

Use [exam_template.txt](files/exam_template.txt) as a starting point. The same template is available through **Download TXT template** in the editor. Delete sample questions and add your own; the number of items comes from your file. Parts can have different numbers of items, and you may omit unused parts.

Use these section headings:

1. `Part 1 - Multiple Choice`: `Question:`, four choices labeled `A.` through `D.`, then `Answer: B` (the correct letter).
2. `Part 2 - Identification`: `Question:` and `Answer:` with the accepted text. An optional `Alternatives:` line accepts comma-separated answers.
3. `Part 3 - True or False`: `Question:` with the statement, followed by `Answer: True` or `Answer: False`.
4. `Part 4 - Matching Type`: a `Choices:` list labeled `A.`, `B.`, etc., followed by each `Question:` prompt and its `Answer:` letter. Each prompt counts as one item. A matching list can contain 2-26 choices; it does not have to contain four choices. For a different list in the same part, add another `Choices:` heading. Choices may also be listed directly under individual questions.

Separate questions with blank lines for readability. `1. Question text` can be used instead of `Question: Question text`. Files may use Windows line endings. Save as UTF-8; UTF-16 files with a byte order mark are also accepted. Maximum file size is 1 MB.

Malformed files show a line number and an error. The existing draft is retained until the entire uploaded file is valid. Missing answer keys, invalid True/False answers and references to nonexistent matching choices are rejected.

The teacher results pages, teacher directory, PDF reports and Excel reports show scores and activity counts without percentage ratings. Students receive a score-only submission receipt. After submission they cannot reopen the question paper or access answer reviews, including through API requests. Assigned teachers and administrators retain review access.

Restart the server with `start_aralhub.bat` to load the backend changes, then reload the browser page. Existing multiple-choice and identification exams remain supported. The additional question-choice storage is created automatically at server startup.
