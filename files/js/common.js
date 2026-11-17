/* Shared frontend helpers used by both student and admin pages. */
function esc(str) {
   if (str === null || str === undefined) return "";
   return String(str).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
   }[ch]));
}

function fmtTime(totalSeconds) {
   const s = Math.max(0, Math.floor(totalSeconds || 0));
   const m = Math.floor(s / 60);
   const sec = s % 60;
   return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

function assessmentPoints(activity, question) {
   return activity?.activityType === "quiz" || ["true_false", "matching"].includes(question?.type) ? 1 : 2;
}

function assessmentPointLabel(activity, question) {
   const points = assessmentPoints(activity, question);
   return `${points} ${points === 1 ? "point" : "points"}`;
}

function assessmentScoringLabel(activity) {
   return activity?.activityType === "quiz" ? "1 point per question" : "Multiple Choice and Identification: 2 points each; True/False and Matching Type: 1 point each";
}

function uiIcon(name, className = "") {
   const paths = {
      grid: '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
      book: '<path d="M12 6c-3-2-6-2-9-1v15c3-1 6-1 9 1 3-2 6-2 9-1V5c-3-1-6-1-9 1Z"/><path d="M12 6v15"/>',
      people: '<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M16 5a3 3 0 0 1 0 6M21 21v-3a6 6 0 0 0-4-5"/>',
      plus: '<path d="M12 5v14M5 12h14"/>',
      arrow: '<path d="M5 12h14m-6-6 6 6-6 6"/>',
      check: '<path d="m6 12 4 4 8-8"/><circle cx="12" cy="12" r="10"/>',
      clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
      file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8M8 17h5"/>',
      search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
      logout: '<path d="M9 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4M10 12h11m-4-4 4 4-4 4"/>',
      bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
      spark: '<path d="m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5ZM20 2v4m-2-2h4"/>',
      shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/><path d="m8 12 3 3 5-5"/>',
   };
   return `<svg class="ui-icon ${className}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || paths.book}</svg>`;
}

function userInitials(name) {
   return String(name || "A").trim().split(/\s+/).slice(0, 2).map(word => word[0]).join("").toUpperCase();
}

function answeredQuestionCount(runtime) {
   return runtime.exam.questions.filter(question => {
      const value = runtime.answers[question.id];
      return value !== undefined && value !== null && String(value).trim() !== "";
   }).length;
}

async function openWorkspaceSection(section) {
   if (section === "materials") { await openLearningWorkspace(); return; }
   const student = state.currentUser?.role === "student" || !state.currentUser?.role;
   if (state.currentUser?.role === "teacher" && section === "overview") section = "activities";
   if (state.currentUser?.role === "teacher" && section === "activities") state.selectedTeacherSubject = "";
   state.workspaceSection = section;
   if (student && state.view !== "studentHome") await goStudentHome();
   else if (!student && state.view !== "adminHome") await goAdminHome();
   else render();
   const target = document.getElementById(section);
   if (section === "students") target?.querySelector("details")?.setAttribute("open", "");
   target?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderWorkspace(body, role) {
   const student = role === "student";
   const teacher = role === "teacher";
   const focus = state.view === "takeExam";
   const roleName = student ? "Student" : role === "admin" ? "Administrator" : "Teacher";
   const section = state.workspaceSection || (teacher || student ? "activities" : "overview");
   const title = ({ learningHome: "Lecture materials", studentHome: "My assessments", adminHome: teacher ? (section === "students" ? "Students" : "My assessments") : "Overview", createExam: "Activity builder", adminResults: "Activity results", adminResultReview: "Answer review", studentResult: "Submission receipt", takeExam: "Assessment in progress" })[state.view] || "Workspace";
   const home = student ? "studentHome" : "adminHome";
   const links = [
      ...(role === "admin" ? [{ id: "overview", label: "Overview", icon: "grid" }] : []),
      ...(role === "admin" ? [{ id: "teachers", label: "Teachers", icon: "book" }] : [{ id: "activities", label: "My assessments", icon: "book" }]),
      ...(student || teacher ? [{ id: "materials", label: "Lecture materials", icon: "file" }] : []),
      ...(!student ? [{ id: "students", label: "Students", icon: "people" }] : []),
   ];
   const progress = focus && state.runtime ? `${answeredQuestionCount(state.runtime)} of ${state.runtime.exam.questions.length} answered` : "";
   return `<div class="workspace ${focus ? "workspace-focus" : ""} ${student && state.view === "studentHome" ? "workspace-student-home" : ""}">
      <aside class="sidebar" aria-label="Workspace navigation">
         <div class="sidebar-brand"><span class="brand-logo-frame"><img src="images/wallpapercdk.png" alt="AbieksExamSys logo"></span><div><strong>AbieksExamSys</strong><small>LEARNING, CONNECTED</small></div></div>
         <div class="sidebar-label">${roleName} workspace</div>
         ${focus ? `<div class="focus-note">${uiIcon("shield")}<strong>Assessment in progress</strong><p>Use the question numbers to review your answers.</p><span class="badge open" data-answer-count>${progress}</span></div>` : `<nav class="sidebar-nav">${links.map(link => { const active = link.id === "materials" ? state.view === "learningHome" : state.view === home && section === link.id; return `<button class="nav-item ${active ? "active" : ""}" ${active ? 'aria-current="page"' : ""} onclick="openWorkspaceSection('${link.id}')">${uiIcon(link.icon)}<span>${link.label}</span></button>`; }).join("")}${role === "teacher" ? `<button class="nav-item ${state.view === "createExam" ? "active" : ""}" onclick="startCreateExam()">${uiIcon("plus")}<span>Create activity</span></button>` : ""}</nav>`}
         <div class="sidebar-bottom"><div class="sidebar-note">${uiIcon("shield")}<strong>${student ? "Ready for your next assessment?" : "Your classroom, in one place."}</strong><span>${student ? "Find your assigned exams and quizzes in My assessments." : "Manage assessments, student accounts, and results from your workspace."}</span></div>${!focus ? `<button class="nav-item signout" onclick="logout()">${uiIcon("logout")}<span>Sign out</span></button>` : ""}</div>
      </aside>
      <div class="workspace-main"><header class="workspace-header"><div class="breadcrumb">${roleName} workspace <span>/</span><strong>${title}</strong></div><div class="profile"><div><strong>${esc(state.currentUser.name || roleName)}</strong><small>${roleName}${student && state.currentUser.department ? ` · ${esc(state.currentUser.department)}` : ""}</small></div><span class="avatar">${esc(userInitials(state.currentUser.name))}</span></div></header><main id="mainContent" class="workspace-content">${body}</main><footer class="workspace-footer"><span>AbieksExamSys · Colegio de Kidapawan</span><span>A better space to learn.</span></footer></div>
   </div>`;
}

function renderActivityTools() {
   const type = state.activityFilter || "all";
   return `<div class="activity-toolbar" data-filter="${esc(type)}"><label class="activity-search">${uiIcon("search")}<span class="sr-only">Search assessments</span><input id="activitySearch" type="search" value="${esc(state.activityQuery || "")}" placeholder="Search title or subject" oninput="filterActivityCards()"></label><div class="activity-tabs" role="group" aria-label="Activity type">${[["all", "All activities"], ["exam", "Exams"], ["quiz", "Quizzes"]].map(([value, label]) => `<button class="${type === value ? "active" : ""}" aria-pressed="${type === value}" onclick="setActivityFilter('${value}', this)">${label}</button>`).join("")}</div></div><p id="activitySearchCount" class="search-count" role="status"></p>`;
}

function renderAuthLayout(body, teacher = false) {
   return `<div class="auth-layout"><aside class="auth-story"><a class="story-brand" href="index.html"><span class="brand-logo-frame"><img src="images/wallpapercdk.png" alt="AbieksExamSys logo"></span><span>AbieksExamSys</span></a><div class="auth-story-copy"><span class="story-eyebrow">${teacher ? "FOR THE PEOPLE WHO INSPIRE" : "YOUR SPACE TO GROW"}</span><h1>${teacher ? "Great teaching.<br> Greater possibilities." : "A little focus.<br> A brighter future."}</h1><p>${teacher ? "Create thoughtful assessments, bring your classroom together, and see every student's progress." : "A calm, connected place for your assessments. Show what you know, one question at a time."}</p><div class="story-features"><span>${uiIcon("book")} Every subject, together</span><span>${uiIcon("check")} Progress you can see</span><span>${uiIcon("shield")} Your own learning space</span></div></div><span class="story-footer">COLEGIO DE KIDAPAWAN · AbieksExamSys</span><div class="story-orbit" aria-hidden="true"></div></aside><main class="auth-form-area" id="mainContent">${body}</main></div>`;
}

function navigateToPortal(path) { window.location.assign(path); }

function renderPortalLogin(action = "doPortalLogin", usernameId = "li_username", passwordId = "li_password") {
   return `<div class="wrap auth-wrap"><div class="wrap-inner auth-inner auth-login-inner"><form class="sheet auth-card login-card" onsubmit="event.preventDefault(); submitAuthForm(this, ${action})"><div class="auth-brand"><span class="brand-logo-frame"><img src="images/wallpapercdk.png" alt="AbieksExamSys logo"></span><span>AbieksExamSys</span></div><div class="auth-heading"><span class="eyebrow">Student &amp; teacher sign in</span><h2>Welcome back</h2><div class="meta">Use your teacher username or student ID. Your account opens the right workspace.</div></div>${state.successMsg ? `<div class="banner success">${esc(state.successMsg)}</div>` : ""}${state.errorMsg ? `<div class="banner">${esc(state.errorMsg)}</div>` : ""}<div class="field"><label for="${usernameId}">Username or student ID</label><input id="${usernameId}" type="text" placeholder="Your username or student ID" autocomplete="username" required maxlength="255"></div><div class="field"><label for="${passwordId}">Password</label><input id="${passwordId}" type="password" placeholder="Your password" autocomplete="current-password" required></div><button type="submit" class="btn block auth-submit">Sign in</button><details class="forgot-password-help"><summary>Forgot password?</summary><p>Students can ask their teacher or the school administrator to reset their password after verifying their student ID. Teachers can contact the school administrator.</p></details></form><a class="back-link" href="/?signup=1">Create a student account</a><a class="back-link" href="/">&larr; Back to AbieksExamSys</a></div></div>`;
}

async function doPortalLogin(usernameId = "li_username", passwordId = "li_password") {
   const username = document.getElementById(usernameId).value.trim();
   const password = document.getElementById(passwordId).value;
   if (!username || !password) { state.errorMsg = "Enter your username or student ID and password."; render(); return; }
   try {
      const result = await apiRequest("POST", "/api/auth/login", {username, password});
      const destination = {student:"/student", teacher:"/teacher", admin:"/admin/"}[result.role];
      if (!destination) throw new Error("Your account could not be opened. Contact the school administrator.");
      navigateToPortal(destination);
   } catch (error) { state.errorMsg = error.message || "Could not sign in. Please try again."; render(); }
}

function setActivityFilter(type, button) {
   state.activityFilter = type;
   document.querySelectorAll(".activity-tabs button").forEach(item => { item.classList.toggle("active", item === button); item.setAttribute("aria-pressed", item === button ? "true" : "false"); });
   document.querySelector(".activity-toolbar").dataset.filter = type;
   filterActivityCards();
}

function filterActivityCards() {
   const query = (document.getElementById("activitySearch")?.value || "").trim().toLowerCase();
   state.activityQuery = document.getElementById("activitySearch")?.value || "";
   const type = document.querySelector(".activity-toolbar")?.dataset.filter || "all";
   let visible = 0;
   document.querySelectorAll(".exam-row[data-activity]").forEach(card => {
      const subjectMatches = state.currentUser?.role !== "teacher" || !state.selectedTeacherSubject || card.dataset.subject === state.selectedTeacherSubject;
      card.hidden = !(subjectMatches && card.dataset.search.includes(query) && (type === "all" || card.dataset.activity === type));
      if (!card.hidden) visible++;
   });
   const empty = document.getElementById("activityNoMatches");
   if (empty) empty.hidden = visible > 0;
   const count = document.getElementById("activitySearchCount");
   if (count) count.textContent = `${visible} ${visible === 1 ? "assessment" : "assessments"} shown`;
}

// Preserve entries when validation redraws the same authentication screen.
// Passwords remain only in the current page's memory, never in browser storage.
function captureInterfaceState() {
   const app = document.getElementById("app");
   return {
      view: app.dataset.view,
      focusId: document.activeElement?.id,
      fields: Array.from(app.querySelectorAll(".auth-form-area input[id], .auth-form-area select[id]"), field => ({
         id: field.id, value: field.value,
         selected: field.multiple ? Array.from(field.selectedOptions, option => option.value) : null,
      })),
   };
}

function refreshMultiSelect(select) {
   select.parentElement.querySelector(`[data-select-id="${select.id}"]`)?.remove();
   const label = select.closest(".field")?.querySelector("label");
   if (label && !label.id) label.id = `${select.id}-label`;
   const group = document.createElement("div");
   group.className = "choice-list";
   group.dataset.selectId = select.id;
   group.setAttribute("role", "group");
   if (label) group.setAttribute("aria-labelledby", label.id);
   const options = Array.from(select.options).filter(option => option.value);
   if (!options.length) {
      const message = document.createElement("p");
      message.className = "help-text";
      message.textContent = select.options[0]?.textContent || "No options available.";
      group.append(message);
   }
   for (const option of options) {
      const item = document.createElement("label");
      item.className = "choice-item";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = option.selected;
      checkbox.disabled = select.disabled || option.disabled;
      checkbox.addEventListener("change", () => {
         option.selected = checkbox.checked;
         select.dispatchEvent(new Event("change", { bubbles: true }));
      });
      const text = document.createElement("span");
      text.textContent = option.textContent;
      item.append(checkbox, text);
      group.append(item);
   }
   select.hidden = true;
   select.after(group);
}

function enhanceInterface(previous) {
   const app = document.getElementById("app");
   if (previous?.view === state.view) {
      for (const saved of previous.fields) {
         const field = document.getElementById(saved.id);
         if (!field) continue;
         if (saved.selected) Array.from(field.options).forEach(option => { option.selected = saved.selected.includes(option.value); });
         else field.value = saved.value;
      }
   }
   app.dataset.view = state.view;
   app.querySelectorAll(".field").forEach((field, index) => {
      const control = field.querySelector("input, select, textarea");
      const label = field.querySelector("label");
      if (control && label && !label.contains(control)) {
         if (!control.id) control.id = `field-${index}`;
         label.htmlFor = control.id;
         const hint = field.querySelector(".help-text");
         if (hint) { hint.id = `${control.id}-hint`; control.setAttribute("aria-describedby", hint.id); }
      }
   });
   app.querySelectorAll('input[type="password"]').forEach(input => {
      const wrapper = document.createElement("div");
      wrapper.className = "password-field";
      input.before(wrapper);
      wrapper.append(input);
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "password-toggle";
      toggle.textContent = "Show";
      toggle.setAttribute("aria-controls", input.id);
      toggle.setAttribute("aria-pressed", "false");
      toggle.setAttribute("aria-label", `Show ${input.closest(".field")?.querySelector("label")?.textContent.toLowerCase() || "password"}`);
      toggle.addEventListener("click", () => {
         const show = input.type === "password";
         input.type = show ? "text" : "password";
         toggle.textContent = show ? "Hide" : "Show";
         toggle.setAttribute("aria-pressed", String(show));
         toggle.setAttribute("aria-label", `${show ? "Hide" : "Show"} ${input.closest(".field")?.querySelector("label")?.textContent.toLowerCase() || "password"}`);
      });
      wrapper.append(toggle);
   });
   app.querySelectorAll("select[multiple]").forEach(refreshMultiSelect);
   app.querySelectorAll(".opt-row").forEach(row => {
      const letter = row.querySelector(".opt-label")?.textContent || "";
      row.querySelector('input[type="text"]')?.setAttribute("aria-label", `Option ${letter}`);
      row.querySelector('input[type="radio"]')?.setAttribute("aria-label", `Mark option ${letter} as correct`);
   });
   app.querySelectorAll(".banner, .conn-banner").forEach(banner => {
      banner.setAttribute("role", banner.classList.contains("success") ? "status" : "alert");
   });
   app.querySelectorAll("th").forEach(header => { header.scope = "col"; });
   app.querySelectorAll(".teacher-table-wrap, .table-scroll").forEach(wrapper => {
      wrapper.tabIndex = 0;
      wrapper.setAttribute("role", "region");
      wrapper.setAttribute("aria-label", "Directory table. Scroll horizontally to see all columns.");
   });
   if (document.getElementById("activitySearch")) filterActivityCards();
   const modal = app.querySelector('[role="dialog"]');
   document.body.classList.toggle("modal-open", !!modal);
   if (modal) modal.querySelector("button")?.focus();
   else if (state.errorMsg) {
      const alert = app.querySelector('[role="alert"]');
      if (alert) { alert.tabIndex = -1; alert.focus(); }
   } else if (previous?.view === state.view && previous.focusId) document.getElementById(previous.focusId)?.focus({ preventScroll: true });
}

function renderDirectoryTools(id, placeholder) {
   return `<div class="table-tools"><label class="activity-search">${uiIcon("search")}<span class="sr-only">${esc(placeholder)}</span><input type="search" placeholder="${esc(placeholder)}" oninput="filterDirectory(this, '${id}')"></label><p id="${id}-status" class="search-count" role="status"></p><p class="table-scroll-hint">Scroll sideways to see all columns.</p></div>`;
}

function filterDirectory(input, directoryId) {
   const directory = document.getElementById(directoryId);
   if (!directory) return;
   const query = input.value.trim().toLowerCase();
   let count = 0;
   directory.querySelectorAll("tbody tr").forEach(row => {
      row.hidden = !row.textContent.toLowerCase().includes(query);
      if (!row.hidden) count++;
   });
   const status = document.getElementById(`${directoryId}-status`);
   if (status) status.textContent = count ? `${count} ${count === 1 ? "record" : "records"} shown` : "No matching records. Try another name or ID.";
}

async function submitAuthForm(form, action) {
   if (form.getAttribute("aria-busy") === "true") return;
   form.setAttribute("aria-busy", "true");
   const button = form.querySelector('button[type="submit"]');
   const label = button.textContent;
   button.disabled = true;
   button.textContent = "Please wait...";
   try { await action(); }
   finally {
      form.removeAttribute("aria-busy");
      button.disabled = false;
      button.textContent = label;
   }
}

document.addEventListener("keydown", event => {
   const modal = document.querySelector('[role="dialog"]');
   if (!modal) return;
   if (event.key === "Escape") { event.preventDefault(); closeModal(); }
   if (event.key === "Tab") {
      const buttons = Array.from(modal.querySelectorAll("button:not(:disabled)"));
      const first = buttons[0], last = buttons[buttons.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
   }
});

let _csrfToken = null;
let _csrfLoading = null;

function portalRequestRole(path) {
   if (path === "/api/auth/login") return "public";
   if (window.ARALHUB_ROLE) return window.ARALHUB_ROLE;
   if (path.startsWith("/api/admin/") || path.startsWith("/api/teachers")) return "teacher";
   if (typeof state !== "undefined" && state.currentUser?.role === "teacher") return "teacher";
   return "student";
}

async function getCsrfToken() {
   if (_csrfToken) return _csrfToken;
   if (!_csrfLoading) {
      _csrfLoading = (async () => {
         try {
            const response = await fetch("/api/csrf", { credentials: "same-origin", cache: "no-store", headers:{"X-Portal-Role":portalRequestRole("/api/csrf")} });
            const data = await response.json();
            if (!response.ok || typeof data.csrfToken !== "string") throw new Error("Could not initialize a secure request. Refresh the page and try again.");
            _csrfToken = data.csrfToken;
            return _csrfToken;
         } catch (error) {
            if (error instanceof TypeError) throw new Error("Could not reach the server. Check your connection and try again.");
            throw error;
         } finally { _csrfLoading = null; }
      })();
   }
   return _csrfLoading;
}

async function apiRequest(method, path, body, extraHeaders, requestOptions) {
   const headers = Object.assign({ "Content-Type": "application/json", "X-Portal-Role":portalRequestRole(path) }, extraHeaders || {});
   const multipart = body instanceof FormData;
   if (multipart) delete headers["Content-Type"];
   if (!["GET", "HEAD", "OPTIONS"].includes(method)) headers["X-CSRFToken"] = await getCsrfToken();
   const opts = { method, headers, credentials: "same-origin", cache: "no-store" };
   if (requestOptions?.keepalive) opts.keepalive = true;
   if (requestOptions?.signal) opts.signal = requestOptions.signal;
   if (body !== undefined) opts.body = multipart ? body : JSON.stringify(body);

   // Only keyed submissions are safe to resend after a lost response.
   const attempts = method === "POST" && path === "/api/results" && body?.submissionId ? 4 : 1;
   let csrfRetried = false;
   for (let attempt = 0; attempt < attempts; attempt++) {
      try {
         const res = await fetch(path, opts);
         let data = null;
         try { data = await res.json(); } catch (e) { data = null; }
         if (res.ok && data !== null) {
            if (path.endsWith("/login") || path === "/api/logout") _csrfToken = null;
            return data;
         }
         if (res.status === 403) _csrfToken = null;
         if (res.status === 403 && data?.code === "csrf_failed" && !csrfRetried && !["GET", "HEAD", "OPTIONS"].includes(method)) {
            // CSRF rejects the request before its handler runs, so this one
            // retry cannot duplicate a publish, submission, or teacher return.
            csrfRetried = true;
            headers["X-CSRFToken"] = await getCsrfToken();
            attempt--;
            continue;
         }
         const error = new Error((data && data.error) || `Request failed (${res.status}).`);
         error.status = res.status;
         error.code = data && data.code;
         error.retryable = [502, 503, 504].includes(res.status) || (res.ok && data === null);
         throw error;
      } catch (err) {
         const retryable = err instanceof TypeError || err.retryable;
         if (!retryable || attempt === attempts - 1) {
            if (err instanceof TypeError) throw new Error("Could not reach the server. Check your connection and try again.");
            throw err;
         }
         await new Promise(resolve => setTimeout(resolve, 1000 * (2 ** attempt) + Math.random() * 500));
      }
   }
}

let _modal = null;

function showModal(opts) {
   _modal = {
      title: opts.title || "",
      message: opts.message || "",
      confirmLabel: opts.confirmLabel || "OK",
      cancelLabel: opts.cancelLabel || null,
      onConfirm: typeof opts.onConfirm === "function" ? opts.onConfirm : null,
      inputLabel: opts.inputLabel || null,
      inputExpected: opts.inputExpected || null,
      inputRequiredMessage: opts.inputRequiredMessage || "Enter the student's ID number to continue.",
      inputValue: "",
      inputError: "",
   };
   if (typeof render === "function") render();
}

function closeModal() {
   _modal = null;
   if (typeof render === "function") render();
}

function _modalConfirm() {
   if (_modal?.inputLabel && (!_modal.inputValue.trim() || (_modal.inputExpected && _modal.inputValue.trim() !== _modal.inputExpected))) {
      _modal.inputError = _modal.inputRequiredMessage;
      if (typeof render === "function") render();
      document.getElementById("dialogInput")?.focus();
      return;
   }
   const cb = _modal && _modal.onConfirm;
   const value = _modal?.inputLabel ? _modal.inputValue.trim() : undefined;
   _modal = null;
   if (cb) cb(value);
   else if (typeof render === "function") render();
}

function renderModalHtml() {
   if (!_modal) return "";
   return `
   <div class="modal-backdrop" onclick="if(event.target===this) closeModal()">
      <div class="modal-box" role="dialog" aria-modal="true" ${_modal.title ? 'aria-labelledby="dialogTitle"' : 'aria-label="Notification"'}>
         ${_modal.title ? `<h3 id="dialogTitle">${esc(_modal.title)}</h3>` : ""}
         ${_modal.message ? `<p>${esc(_modal.message)}</p>` : ""}
         ${_modal.inputLabel ? `<label for="dialogInput">${esc(_modal.inputLabel)}</label><input id="dialogInput" type="text" value="${esc(_modal.inputValue)}" autocomplete="off" required aria-invalid="${!!_modal.inputError}" ${_modal.inputError ? 'aria-describedby="dialogInputError"' : ''} oninput="_modal.inputValue=this.value" onkeydown="if(event.key==='Enter'){event.preventDefault();_modalConfirm();}">${_modal.inputError ? `<p id="dialogInputError" role="alert">${esc(_modal.inputError)}</p>` : ""}` : ""}
         <div class="modal-actions">
            ${_modal.cancelLabel ? `<button class="btn secondary" onclick="closeModal()">${esc(_modal.cancelLabel)}</button>` : ""}
            <button class="btn" onclick="_modalConfirm()">${esc(_modal.confirmLabel)}</button>
         </div>
      </div>
   </div>`;
}
