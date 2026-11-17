# Teacher publishing recovery

The old create-assessment response used the same 403 message for expired sessions and non-teacher accounts. The backend now returns distinct session/role codes. The editor handles these responses with an inline teacher sign-in form, preserving the imported questions and draft details in the current page. A teacher can sign in and retry Publish without re-uploading the TXT file.

- 47 backend tests passed, including a 50-question publish after session expiry, expired edit handling, blocked superadmin publishing, and changed-teacher ownership checks.
- 23 headless Edge tests passed, including preserved 50-question imports for expired sessions, non-teacher sessions, and changed teacher sessions; rejecting superadmin reauthentication; and successful publication after teacher sign-in.
- Teacher credentials remain in the current form only and are not persisted in browser storage.
- The import message stating that 50 items were loaded remains a successful import confirmation.
- Unpublished questions remain in page memory; a page reload still requires importing the file again.
