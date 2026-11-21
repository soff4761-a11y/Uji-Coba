/**
 * EduTrack Entry Point (ES Module v7):
 * - Autentikasi berbasis Cookie HttpOnly + Double-Submit CSRF (tanpa sessionStorage token)
 * - Mendukung peran admin, teacher, dan student
 * - Registrasi Service Worker PWA, sidebar dinamis, dan timeout idle 60 menit (CSRF-safe)
 */

import { api } from "./js/api.js?v=20261120-v8.4.2";
import { applyTheme, onById, showView, state, toast, toggleTheme } from "./js/state.js?v=20261120-v8.4.2";
import { bindStudentListeners, initStudentPortal, registerStudentGlobals, resetStudentModalSessionState } from "./js/student.js?v=20261120-v8.4.2";
import { bindTeacherListeners, clearUserOfflineReadCache, initTeacherPortal } from "./js/teacher.js?v=20261120-v8.4.2";

registerStudentGlobals();

async function bootSession(showError = false) {
  try {
    const res = await api("/api/auth/me");
    state.user = res.user;
  } catch (err) {
    if (showError && err && err.message) {
      toast(err.message, true);
    }
    showView("view-login");
    return;
  }

  if (state.user.must_change_password) {
    showView("view-force-password");
    return;
  }

  if (state.user.role === "teacher" || state.user.role === "admin") {
    showView("view-teacher");
    try {
      await initTeacherPortal();
    } catch (err) {
      toast(err?.message || "Gagal memuat dashboard guru. Silakan muat ulang.", true);
    }
  } else {
    showView("view-student");
    try {
      await initStudentPortal();
    } catch (err) {
      toast(err?.message || "Gagal memuat dashboard peserta didik. Silakan muat ulang.", true);
    }
  }
}

async function logoutAllDevicesFlow() {
  if (!confirm("Keluar dari SEMUA perangkat (termasuk perangkat ini)? Anda harus login ulang.")) return;
  try {
    await api("/api/auth/logout-all", { method: "POST", body: { keep_current: false } });
  } catch (_) {}
  resetStudentModalSessionState();
  clearUserOfflineReadCache();
  state.user = null;
  showView("view-login");
  toast("Seluruh sesi pada semua perangkat telah diakhiri.");
}

function initDynamicNavigation() {
  const teacherLayout = document.getElementById("view-teacher");
  const btnCollapse = document.getElementById("btn-collapse-sidebar");
  const btnToggle = document.getElementById("btn-toggle-sidebar");
  const backdrop = document.getElementById("sidebar-backdrop");
  const teacherNav = document.getElementById("teacher-nav");
  const studentLayout = document.getElementById("view-student");
  const btnCollapseStudent = document.getElementById("btn-collapse-student-sidebar");
  const btnStudentMenu = document.getElementById("btn-toggle-student-menu");
  const studentBackdrop = document.getElementById("student-sidebar-backdrop");

  const isMobile = () => window.matchMedia("(max-width: 960px)").matches;

  function setDesktopCollapsed(collapsed) {
    if (!teacherLayout) return;
    teacherLayout.classList.toggle("sidebar-collapsed", collapsed);
    if (btnCollapse) btnCollapse.setAttribute("aria-expanded", String(!collapsed));
    try { localStorage.setItem("edutrack_sidebar_collapsed", collapsed ? "1" : "0"); } catch (_) {}
  }

  function setMobileDrawer(open) {
    if (!teacherLayout) return;
    teacherLayout.classList.toggle("drawer-open", open);
    if (btnToggle) btnToggle.setAttribute("aria-expanded", String(open));
  }

  function handleTeacherToggle() {
    if (!teacherLayout) return;
    if (isMobile()) setMobileDrawer(!teacherLayout.classList.contains("drawer-open"));
    else setDesktopCollapsed(!teacherLayout.classList.contains("sidebar-collapsed"));
  }

  function setStudentDesktopCollapsed(collapsed) {
    if (!studentLayout) return;
    studentLayout.classList.toggle("sidebar-collapsed", collapsed);
    if (btnCollapseStudent) btnCollapseStudent.setAttribute("aria-expanded", String(!collapsed));
    if (btnStudentMenu) btnStudentMenu.setAttribute("aria-expanded", String(!collapsed));
    try { localStorage.setItem("edutrack_student_sidebar_collapsed", collapsed ? "1" : "0"); } catch (_) {}
  }

  function setStudentMobileDrawer(open) {
    if (!studentLayout) return;
    studentLayout.classList.toggle("drawer-open", open);
    if (btnStudentMenu) btnStudentMenu.setAttribute("aria-expanded", String(open));
  }

  function handleStudentToggle() {
    if (!studentLayout) return;
    if (isMobile()) setStudentMobileDrawer(!studentLayout.classList.contains("drawer-open"));
    else setStudentDesktopCollapsed(!studentLayout.classList.contains("sidebar-collapsed"));
  }

  try {
    if (localStorage.getItem("edutrack_sidebar_collapsed") === "1") setDesktopCollapsed(true);
    if (localStorage.getItem("edutrack_student_sidebar_collapsed") === "1") setStudentDesktopCollapsed(true);
  } catch (_) {}

  if (btnCollapse) btnCollapse.addEventListener("click", handleTeacherToggle);
  if (btnToggle) btnToggle.addEventListener("click", handleTeacherToggle);
  if (backdrop) backdrop.addEventListener("click", () => setMobileDrawer(false));
  if (teacherNav) {
    teacherNav.addEventListener("click", (e) => {
      if (e.target.closest(".nav-item") && isMobile()) setMobileDrawer(false);
    });
  }

  if (btnCollapseStudent) btnCollapseStudent.addEventListener("click", handleStudentToggle);
  if (btnStudentMenu) btnStudentMenu.addEventListener("click", handleStudentToggle);
  if (studentBackdrop) studentBackdrop.addEventListener("click", () => setStudentMobileDrawer(false));

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      setMobileDrawer(false);
      setStudentMobileDrawer(false);
    }
  });
}

function initIdleSessionTimeout() {
  const IDLE_LIMIT_MS = 60 * 60 * 1000;
  const WARN_BEFORE_MS = 5 * 60 * 1000;
  let lastActivityAt = Date.now();
  let lastPingAt = Date.now();
  let expiredHandled = false;

  const isLoggedIn = () => Boolean(state.user);

  function hideWarningBanner() {
    const b = document.getElementById("idle-warning-banner");
    if (b) b.classList.add("hidden");
  }

  function recordActivity(sendPing = false) {
    if (!isLoggedIn()) return;
    lastActivityAt = Date.now();
    expiredHandled = false;
    hideWarningBanner();
    if (sendPing || Date.now() - lastPingAt > 5 * 60 * 1000) {
      lastPingAt = Date.now();
      api("/api/auth/ping", { method: "POST" }).catch(() => {});
    }
  }

  async function expireSessionNow(customMsg) {
    if (expiredHandled) return;
    expiredHandled = true;
    hideWarningBanner();
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch (_) {}
    resetStudentModalSessionState();
    clearUserOfflineReadCache();
    state.user = null;
    showView("view-login");
    const notice = document.getElementById("login-session-notice");
    const msg =
      customMsg ||
      "Sesi Anda telah berakhir otomatis karena tidak ada aktivitas selama 60 menit. Silakan login kembali.";
    if (notice) {
      notice.textContent = msg;
      notice.classList.remove("hidden");
    }
    toast(msg, true);
  }

  window.__handleIdleSessionExpired = expireSessionNow;

  ["click", "keydown", "input", "change", "submit", "touchstart"].forEach((ev) => {
    document.addEventListener(ev, () => recordActivity(false), { passive: true });
  });
  onById("btn-extend-session", "click", () => {
    recordActivity(true);
    toast("Sesi diperpanjang.");
  });

  setInterval(() => {
    if (!isLoggedIn()) return;
    const idleMs = Date.now() - lastActivityAt;
    if (idleMs >= IDLE_LIMIT_MS) {
      expireSessionNow();
      return;
    }
    const remainingMs = IDLE_LIMIT_MS - idleMs;
    if (remainingMs <= WARN_BEFORE_MS) {
      const minsLeft = Math.max(1, Math.ceil(remainingMs / 60000));
      const b = document.getElementById("idle-warning-banner");
      const t = document.getElementById("idle-warning-text");
      if (t) t.textContent = `Sesi Anda akan berakhir otomatis dalam ${minsLeft} menit karena tidak ada aktivitas.`;
      if (b) b.classList.remove("hidden");
    }
  }, 15000);
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
  });
}

document.addEventListener("DOMContentLoaded", () => {
  applyTheme(localStorage.getItem("edutrack_theme") || "dark");
  ["btn-theme-login", "btn-theme-teacher", "btn-theme-student"].forEach((id) => {
    onById(id, "click", toggleTheme);
  });

  onById("form-login", "submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/auth/login", {
        method: "POST",
        body: {
          username: document.getElementById("login-username").value,
          password: document.getElementById("login-password").value,
        },
      });
      const notice = document.getElementById("login-session-notice");
      if (notice) notice.classList.add("hidden");
      toast("Login berhasil.");
      await bootSession(true);
    } catch (err) {
      toast(err.message, true);
    }
  });

  onById("form-force-password", "submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/auth/change-password", {
        method: "POST",
        body: {
          current_password: document.getElementById("fp-current").value,
          new_password: document.getElementById("fp-new").value,
        },
      });
      toast("Akun aktif dan kata sandi pribadi tersimpan.");
      await bootSession(true);
    } catch (err) {
      toast(err.message, true);
    }
  });

  const doLogout = async () => {
    resetStudentModalSessionState();
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch (_) {}
    clearUserOfflineReadCache();
    state.user = null;
    showView("view-login");
    toast("Anda telah keluar.");
  };
  onById("btn-logout-teacher", "click", doLogout);
  onById("btn-logout-student", "click", doLogout);
  onById("btn-logout-all-teacher", "click", logoutAllDevicesFlow);
  onById("btn-logout-all-student", "click", logoutAllDevicesFlow);

  bindTeacherListeners();
  bindStudentListeners();
  initDynamicNavigation();
  initIdleSessionTimeout();
  bootSession(false);
});
