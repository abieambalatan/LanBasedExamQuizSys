/* ============================= SHARED HELPERS =============================
  Used by both files/index.html (student) and files/administrator.html (admin).
   Provides: esc(), fmtTime(), apiRequest(), showModal(), closeModal(),
   renderModalHtml().
============================================================================ */

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

/**
 * apiRequest(method, path, body?, extraHeaders?)
 * - GET requests: body is typically omitted.
 * - Non-GET requests: body (if any) is JSON-encoded.
 * - extraHeaders: e.g. { "X-Admin-User": adminUser, "X-Admin-Pass": adminPass }
 * Throws an Error with a human-readable message on failure.
 */
async function apiRequest(method, path, body, extraHeaders) {
  const headers = Object.assign({ "Content-Type": "application/json" }, extraHeaders || {});
  const opts = { method, headers };
  if (body !== undefined) opts.body = JSON.stringify(body);

  let res;
  try {
    res = await fetch(path, opts);
  } catch (err) {
    throw new Error("Could not reach the server. Is app.py still running?");
  }

  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }

  if (!res.ok) {
    const message = (data && data.error) ? data.error : `Request failed (${res.status}).`;
    throw new Error(message);
  }
  return data;
}

/* ============================= MODAL ============================= */
let _modal = null; // { title, message, confirmLabel, cancelLabel, onConfirm }

function showModal(opts) {
  _modal = {
    title: opts.title || "",
    message: opts.message || "",
    confirmLabel: opts.confirmLabel || "OK",
    cancelLabel: opts.cancelLabel || null,
    onConfirm: typeof opts.onConfirm === "function" ? opts.onConfirm : null,
  };
  if (typeof render === "function") render();
}

function closeModal() {
  _modal = null;
  if (typeof render === "function") render();
}

function _modalConfirm() {
  const cb = _modal && _modal.onConfirm;
  _modal = null;
  if (cb) { cb(); }
  else if (typeof render === "function") { render(); }
}

function renderModalHtml() {
  if (!_modal) return "";
  return `
  <div class="modal-backdrop" onclick="if(event.target===this) closeModal()">
    <div class="modal-box">
      ${_modal.title ? `<h3>${esc(_modal.title)}</h3>` : ""}
      ${_modal.message ? `<p>${esc(_modal.message)}</p>` : ""}
      <div class="modal-actions">
        ${_modal.cancelLabel ? `<button class="btn secondary" onclick="closeModal()">${esc(_modal.cancelLabel)}</button>` : ""}
        <button class="btn" onclick="_modalConfirm()">${esc(_modal.confirmLabel)}</button>
      </div>
    </div>
  </div>`;
}
