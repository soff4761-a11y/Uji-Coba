/**
 * Modul State & Utilitas DOM bersama untuk EduTrack (ES Module v7).
 */

export const state = {
  user: null,
  periods: [],
  classes: [],
  materials: [],
  announcements: [],
  selectedPeriodId: null,
  selectedClassId: null,
  selectedAssessmentId: null,
  selectedSessionId: null,
  gradebook: null,
  studentDashboard: null,
  studentSelectedMaterialId: null,
  attentionStudents: [],
  compareMaterials: [],
};

export function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function setHtml(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

export function onById(id, evt, handler) {
  const el = document.getElementById(id);
  if (el) el.addEventListener(evt, handler);
}

export function toast(message, isError = false) {
  const container = document.getElementById("toast-container");
  if (!container) return;
  const el = document.createElement("div");
  el.className = `toast ${isError ? "error" : ""}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

export function showView(viewId) {
  for (const id of ["view-login", "view-force-password", "view-teacher", "view-student"]) {
    const el = document.getElementById(id);
    if (el) el.classList.toggle("hidden", id !== viewId);
  }
}

export function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem("edutrack_theme", theme);
  } catch (_) {}
}

export function toggleTheme() {
  const cur = document.documentElement.getAttribute("data-theme") || "dark";
  applyTheme(cur === "light" ? "dark" : "light");
}
