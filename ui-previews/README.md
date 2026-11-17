# ExamHub interface previews

These screenshots use synthetic sample data and the actual application templates, scripts and styles. They do not read student records or connect to the live portal.

- [Teacher workspace](teacher-1440.png)
- [Teacher submission notifications](notifications-1440.png)
- [Notifications on a phone](notifications-320.png)
- [Teacher lecture uploads](teacher-materials-1440.png)
- [Student lecture materials and submissions](student-materials-390.png)
- [Super admin dashboard](superadmin-1440.png)
- [Super admin on a phone](superadmin-390.png)
- [Assessment focus warning](focus-warning-390.png)
- [Student workspace](student-1440.png)
- [Student workspace on a phone](student-390.png)
- [Public landing page](landing-1440.png)
- [Sign in](login-1440.png)
- [Assessment builder](builder-1440.png)
- [Teacher results](results-1440.png)
- [Administrator directory](admin-1440.png)
- [Assessment on a phone](assessment-390.png)
- [Teacher registration on a phone](staff-signup-390.png)
- [Results on a phone](results-390.png)
- [Teacher answer review](review-1440.png)
- [Student submission receipt](receipt-390.png)

The shared interface uses larger text, stronger contrast, a purple and lavender palette, clear dashboard headings, and larger touch targets. Mobile navigation displays every workspace action, including the teacher's unread submission badge. Fonts and icons load locally, including when the LAN has no internet connection.

Students and teachers use the same sign-in page at `/login`. The server determines their role from the verified account and opens `/student` or `/teacher`; superadmins open `/admin/`. The form supports Enter, show/hide password controls, and prevents duplicate submissions. Validation preserves entered details within the current screen. Department and class selection uses checkboxes. Directory searches match student names, IDs, departments, and teacher names or usernames. Assessment filters survive page redraws, and identification answers update progress immediately. Dialogs support Escape and keep keyboard focus inside the dialog. The `login-*` and `staff-login-*` previews now show the same shared sign-in screen.

Restart using the existing server launcher to apply the returned-submission archive migration, then press **Ctrl+F5** in each browser to reload the interface.

To regenerate the previews, install the optional `requirements-dev.txt` dependencies and run `python preview_ui.py` using the project virtual environment. Microsoft Edge must be installed. The script checks desktop, tablet, and mobile layouts, including 320px and 390px phones, a 768px tablet, a 1024px builder, and 1440px desktops. `layout-checks.json` records horizontal page overflow. Use `python preview_ui.py --screens superadmin teacher focus-warning` to capture the latest dashboard and warning screens; those checks are saved separately in `live-workflows-layout-checks.json`. Preview HTML files are static snapshots with sample data.

Teacher dashboards and results refresh every three seconds; student workspaces detect teacher returns every five seconds. A returned assessment preserves the original submission and restores the student's answers with a fresh time allowance. Leaving an active exam or quiz shows a ten-second warning before automatic submission. The native super admin dashboard also refreshes every five seconds. Previews use temporary databases and synthetic records.
