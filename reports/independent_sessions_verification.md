# Student workspace and teacher return session verification

The running server log showed repeated unauthorized assessment requests and a rejected CSRF token when returning a submission. Student and teacher sign-ins previously overwrote the same session cookie.

Changes:

- Student, teacher, and native superadmin logins use independent signed session cookies. The role header selects the cookie; server-side account validation and ownership checks still apply.
- Existing matching teacher/student logins migrate to the role cookie. Retiring the matching legacy cookie prevents a signed-out session from returning through migration.
- A CSRF-rejected action refreshes its security token and retries once. Permission denials are not retried or bypassed.
- Student workspace authentication failures stop polling and show sign-in instructions. Temporary failures preserve displayed data and retry; permission failures display their actual message.
- A teacher with a valid session can return a student's exam without another login, including after student sign-in and student logout in the same browser.

Verification: 49 backend tests and 25 headless Edge tests passed (74 total). Django system check passed. Tests include independent cookies with enforced CSRF, same-browser student submission and teacher return, superadmin coexistence, legacy migration/logout, forged role-cookie rejection, automatic return-token refresh, and student reconnect/session handling. Tests use temporary databases and synthetic accounts.

Reload both student and teacher pages with Ctrl+F5 to load the role-specific request headers. If a previous login had already been overwritten, sign in once to establish that role's cookie.
