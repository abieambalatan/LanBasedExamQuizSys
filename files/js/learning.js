/* Lecture materials and activity file submissions, shared by both workspaces. */
const LEARNING_FILE_ACCEPT = ".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx";
function learningFileSize(size) {
   return size >= 1024 * 1024 ? `${(size / (1024 * 1024)).toFixed(1)} MB` : `${Math.max(1, Math.ceil(size / 1024))} KB`;
}
function learningFileLinks(file) {
   return `<div class="learning-file"><span class="activity-icon violet">${uiIcon("file")}</span><div><strong>${esc(file.filename)}</strong><small>${learningFileSize(file.size)}</small></div><div class="learning-file-actions"><a class="btn secondary" href="${esc(file.openUrl)}" target="_blank" rel="noopener">Open</a><a class="linklike" href="${esc(file.downloadUrl)}">Download</a></div></div>`;
}
async function openLearningWorkspace() {
   state.workspaceSection = "materials";
   state.learningError = ""; state.learningNotice = "";
   state.learningSubmissions = null; state.learningSelectedMaterial = null;
   const user = state.currentUser;
   try {
      const materials = await apiRequest("GET", "/api/learning/materials");
      if (state.currentUser !== user) return;
      state.learningMaterials = materials;
   } catch (error) {
      if (state.currentUser !== user) return;
      state.learningMaterials = [];
      state.learningError = error.message;
   }
   state.view = "learningHome";
   render();
}
function learningTargetClasses(form) {
   return Array.from(form.querySelectorAll('[name="lectureClass"]:checked'), checkbox => checkbox.matches(":disabled") ? null : ({department:checkbox.dataset.department, yearLevel:checkbox.dataset.year, section:checkbox.value})).filter(Boolean);
}
function updateLearningClassCount() {
   const form = document.querySelector(".learning-upload form");
   if (!form) return;
   const count = learningTargetClasses(form).length;
   form.querySelector(".learning-class-count").textContent = `${count} ${count === 1 ? "class selected" : "classes selected"}`;
}
function toggleLearningDepartment(index, selected) {
   const group = document.getElementById(`lecture-department-${index}`);
   if (!group) return;
   group.hidden = !selected;
   group.disabled = !selected;
   updateLearningClassCount();
}
function toggleLearningYear(departmentIndex, yearIndex, selected) {
   const group = document.getElementById(`lecture-year-${departmentIndex}-${yearIndex}`);
   if (!group) return;
   group.hidden = !selected;
   group.disabled = !selected;
   updateLearningClassCount();
}
function selectLearningYearSections(departmentIndex, yearIndex, selected) {
   const group = document.getElementById(`lecture-year-${departmentIndex}-${yearIndex}`);
   group?.querySelectorAll('[name="lectureClass"]').forEach(checkbox => { checkbox.checked = selected; });
   updateLearningClassCount();
}
function renderLearningClassPicker() {
   return `<fieldset class="learning-targets"><legend>Share with these classes</legend><p class="help-text">Select every department represented in your class, then choose its year levels and sections. Students in any selected class can view the same material.</p><div class="learning-department-options">${DEPARTMENTS.map((department, index) => `<label class="learning-check"><input type="checkbox" name="lectureDepartment" value="${esc(department)}" onchange="toggleLearningDepartment(${index}, this.checked)"> ${esc(department)}</label>`).join("")}</div><div class="learning-class-groups">${DEPARTMENTS.map((department, departmentIndex) => `<fieldset class="learning-department-group" id="lecture-department-${departmentIndex}" hidden disabled><legend>${esc(department)}</legend><div class="learning-year-options">${YEAR_LEVELS.map((year, yearIndex) => `<label class="learning-check"><input type="checkbox" name="lectureYear" value="${esc(year)}" onchange="toggleLearningYear(${departmentIndex}, ${yearIndex}, this.checked)"> ${esc(year)}</label>`).join("")}</div>${YEAR_LEVELS.map((year, yearIndex) => `<fieldset class="learning-year-sections" id="lecture-year-${departmentIndex}-${yearIndex}" hidden disabled><legend>${esc(department)} &middot; ${esc(year)}</legend><div class="learning-section-actions"><button type="button" class="linklike" onclick="selectLearningYearSections(${departmentIndex}, ${yearIndex}, true)">Select all sections</button><button type="button" class="linklike" onclick="selectLearningYearSections(${departmentIndex}, ${yearIndex}, false)">Clear sections</button></div><div class="learning-section-options">${sectionsForDepartment(department, year).map(section => `<label class="learning-check"><input type="checkbox" name="lectureClass" data-department="${esc(department)}" data-year="${esc(year)}" value="${esc(section)}" onchange="updateLearningClassCount()"> ${esc(department)} ${yearIndex + 1}-${esc(section)}</label>`).join("") || '<span class="help-text">No sections available.</span>'}</div></fieldset>`).join("")}</fieldset>`).join("")}</div><p class="learning-class-count help-text" role="status">0 classes selected</p></fieldset>`;
}
function renderLectureUploadForm() {
   return `<details class="sheet learning-upload"><summary>${uiIcon("plus")} Share lecture material or an activity</summary><form onsubmit="event.preventDefault(); publishLectureMaterial(this)"><fieldset><div class="learning-form-grid"><div class="field"><label for="lectureTitle">Lecture / activity title</label><input id="lectureTitle" name="title" maxlength="200" required></div><div class="field"><label for="lectureSubject">Subject</label><input id="lectureSubject" name="subject" maxlength="200" required></div></div><div class="field"><label for="lectureInstructions">Lecture notes / activity instructions</label><textarea id="lectureInstructions" name="instructions" rows="4" maxlength="10000" placeholder="Describe what students should read or submit."></textarea></div>${renderLearningClassPicker()}<label class="learning-check learning-accept"><input type="checkbox" name="requiresSubmission"> Request a student file submission for this activity</label><div class="field"><label for="lectureFile">Lecture material / activity file</label><input id="lectureFile" name="file" type="file" accept="${LEARNING_FILE_ACCEPT}" required><small class="help-text">PDF, Word, PowerPoint, or Excel. Maximum 25 MB per file. Share additional files as separate materials.</small></div><p class="learning-form-status" role="status"></p><button class="btn" type="submit">${uiIcon("plus")} Share with students</button></fieldset></form></details>`;
}
function renderLearningWorkspace() {
   const teacher = state.currentUser?.role === "teacher";
   const materials = state.learningMaterials || [];
   const cards = materials.map(material => `<article class="sheet learning-card"><div class="section-title-row"><div><span class="eyebrow">${esc(material.subject)}</span><h2>${esc(material.title)}</h2><p class="meta">${esc(material.teacherName)} &middot; ${esc(new Date(material.createdAt).toLocaleString())}</p></div><span class="badge ${material.mySubmission ? "done" : "open"}">${material.requiresSubmission ? material.mySubmission ? "Submitted" : "Activity submission" : "Lecture material"}</span></div>${material.instructions ? `<p class="learning-instructions">${esc(material.instructions)}</p>` : ""}${learningFileLinks(material)}${teacher ? `<p class="help-text">Shared with ${(material.targetClasses || []).map(item => esc(`${item.department} ${item.yearLevel}, Section ${item.section}`)).join("; ")}</p><div class="learning-card-actions">${material.requiresSubmission ? `<button class="btn secondary" onclick="openLearningSubmissions('${material.id}')">${uiIcon("people")} View submissions (${material.submissionCount || 0})</button>` : ""}<button class="linklike danger-link" onclick="deleteLectureMaterial('${material.id}')">Delete material</button></div>` : material.requiresSubmission ? `<div class="learning-submission"><h3>Your activity submission</h3>${material.mySubmission ? `<p class="meta">Submitted ${esc(new Date(material.mySubmission.submittedAt).toLocaleString())}</p>${learningFileLinks(material.mySubmission)}<p class="help-text">Uploading again replaces your previous submission.</p>` : '<p class="help-text">Choose your completed activity file and submit it to your teacher.</p>'}<form onsubmit="event.preventDefault(); submitLearningFile(this, '${material.id}')"><fieldset><label class="sr-only" for="submission-${material.id}">Activity file for ${esc(material.title)}</label><input id="submission-${material.id}" name="file" type="file" accept="${LEARNING_FILE_ACCEPT}" required><small class="help-text">PDF, Word, PowerPoint, or Excel. Maximum 25 MB.</small><p class="learning-form-status" role="status"></p><button class="btn" type="submit">${material.mySubmission ? "Replace submission" : "Submit activity file"}</button></fieldset></form></div>` : ""}</article>`).join("");
   const selected = materials.find(item => item.id === state.learningSelectedMaterial);
   return `<div class="wrap"><div class="wrap-inner wide"><section id="materials"><div class="section-title-row"><div><span class="eyebrow">YOUR CLASSROOM FILES</span><h1>Lecture materials</h1><p>${teacher ? "Share lecture files and collect completed activities from your classes." : "Read your class materials and submit your completed activities here."}</p></div><button class="btn secondary" onclick="openLearningWorkspace()">Refresh</button></div><p class="help-text">PDFs open in your browser. Word, PowerPoint, and Excel files download to open in an installed app.</p>${state.learningError ? `<div class="banner" role="alert">${esc(state.learningError)}</div>` : ""}${state.learningNotice ? `<div class="conn-banner" role="status">${esc(state.learningNotice)}</div>` : ""}${teacher ? renderLectureUploadForm() : ""}${selected && Array.isArray(state.learningSubmissions) ? `<section class="sheet learning-received" aria-label="Activity submissions"><div class="section-title-row"><div><span class="eyebrow">STUDENT SUBMISSIONS</span><h2>${esc(selected.title)}</h2></div><button class="btn secondary" onclick="state.learningSelectedMaterial=null; state.learningSubmissions=null; render()">Close</button></div>${state.learningSubmissions.length ? state.learningSubmissions.map(item => `<article class="learning-received-row" data-submission-id="${esc(item.id)}" tabindex="-1"><h3>${esc(item.name || "Student")} &middot; ${esc(item.rollNo)}</h3><p class="meta">${esc(item.department)} &middot; ${esc(item.yearLevel)}, Section ${esc(item.section)} &middot; ${esc(new Date(item.submittedAt).toLocaleString())}</p>${learningFileLinks(item)}</article>`).join("") : '<div class="empty">No files submitted yet.</div>'}</section>` : ""}<div class="learning-list">${cards || `<div class="empty">${uiIcon("file")}<h2>No lecture materials yet</h2><p>${teacher ? "Share a file above to make it available to your students." : "Materials shared with your class will appear here."}</p></div>`}</div></section></div></div>`;
}
function checkLearningFile(form) {
   const file = form.querySelector('input[type="file"]').files[0];
   if (!file) throw new Error("Choose a file first.");
   if (!file.size || file.size > 25 * 1024 * 1024) throw new Error("Choose a non-empty file of 25 MB or smaller.");
   if (!LEARNING_FILE_ACCEPT.split(",").some(extension => file.name.toLowerCase().endsWith(extension))) throw new Error("Choose a PDF, Word, PowerPoint, or Excel file.");
}
async function sendLearningForm(form, path, data, notice) {
   const status = form.querySelector(".learning-form-status");
   const fieldset = form.querySelector("fieldset");
   const user = state.currentUser;
   let uploaded = false;
   try {
      checkLearningFile(form);
      fieldset.disabled = true; status.textContent = "Uploading file. Please keep this page open…";
      await apiRequest("POST", path, data);
      uploaded = true;
      if (state.currentUser !== user) return;
      const materials = await apiRequest("GET", "/api/learning/materials");
      if (state.currentUser !== user) return;
      state.learningMaterials = materials; state.learningNotice = notice; state.learningError = "";
      state.learningSelectedMaterial = null; state.learningSubmissions = null;
      render();
   } catch (error) { status.textContent = uploaded ? `${notice} Use Refresh to load the latest files. ${error.message}` : error.message; status.setAttribute("role", "alert"); }
   finally { fieldset.disabled = false; }
}
async function publishLectureMaterial(form) {
   const data = new FormData(form);
   const targetClasses = learningTargetClasses(form);
   if (!targetClasses.length || targetClasses.length > 120) { const status = form.querySelector(".learning-form-status"); status.textContent = "Select between 1 and 120 classes, using the department, year level, and section checkboxes."; status.setAttribute("role", "alert"); return; }
   data.set("targetClasses", JSON.stringify(targetClasses));
   data.set("requiresSubmission", String(form.elements.requiresSubmission.checked));
   await sendLearningForm(form, "/api/learning/materials", data, "Material shared with your students.");
}
async function submitLearningFile(form, materialId) {
   await sendLearningForm(form, `/api/learning/materials/${encodeURIComponent(materialId)}/submissions`, new FormData(form), "Your activity file was submitted successfully.");
}
async function openLearningSubmissions(materialId) {
   const user = state.currentUser;
   try {
      const submissions = await apiRequest("GET", `/api/learning/materials/${encodeURIComponent(materialId)}/submissions`);
      if (state.currentUser !== user || state.view !== "learningHome") return;
      state.learningSubmissions = submissions;
      state.learningSelectedMaterial = materialId; state.learningError = "";
      render(); document.querySelector(".learning-received")?.scrollIntoView({behavior:"smooth"});
   } catch (error) { state.learningError = error.message; render(); }
}
function deleteLectureMaterial(materialId) {
   showModal({title:"Delete lecture material?", message:"This removes the shared file and all activity submissions for this material.", confirmLabel:"Delete material", cancelLabel:"Cancel", onConfirm:async () => {
      try { await apiRequest("DELETE", `/api/learning/materials/${encodeURIComponent(materialId)}`); await openLearningWorkspace(); }
      catch (error) { state.learningError = error.message; render(); }
   }});
}

