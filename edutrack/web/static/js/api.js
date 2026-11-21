/**
 * Modul Klien HTTP Aman EduTrack (Cookie HttpOnly + Double-Submit CSRF, tanpa sessionStorage token).
 */

import { toast } from "./state.js?v=20261120-v8.4.2";

const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
let csrfRefreshPromise = null;

export function getCsrfToken() {
  const cookies = document.cookie ? document.cookie.split(";") : [];
  let token = "";
  for (const part of cookies) {
    const idx = part.indexOf("=");
    if (idx === -1) continue;
    const name = part.slice(0, idx).trim();
    if (name === "edutrack_csrf") {
      token = decodeURIComponent(part.slice(idx + 1).trim());
    }
  }
  return token;
}

async function ensureCsrfCookie(forceRefresh = false) {
  if (!csrfRefreshPromise) {
    const url = forceRefresh ? "/api/auth/me?refresh_csrf=1" : "/api/auth/me";
    csrfRefreshPromise = fetch(url, {
      credentials: "same-origin",
      cache: "no-store",
    })
      .then((res) => Boolean(res && res.ok))
      .catch(() => false)
      .finally(() => {
        csrfRefreshPromise = null;
      });
  }
  return csrfRefreshPromise;
}

export async function api(path, options = {}) {
  const { _csrfRetried = false, ...rawOptions } = options;
  const opts = { credentials: "same-origin", ...rawOptions };
  const method = String(opts.method || "GET").toUpperCase();
  const headers = { ...(opts.headers || {}) };
  const isProtectedMutation = MUTATING_METHODS.has(method) && path !== "/api/auth/login";

  // Sertakan X-CSRF-Token pada seluruh request mutasi (termasuk FormData upload)
  if (isProtectedMutation) {
    let csrf = getCsrfToken();
    if (!csrf) {
      await ensureCsrfCookie(false);
      csrf = getCsrfToken();
    }
    if (csrf) {
      headers["X-CSRF-Token"] = csrf;
    }
  }

  if (opts.body && !(opts.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  opts.headers = headers;

  const res = await fetch(path, opts);
  if (!res.ok) {
    let errMsg = `Kesalahan (${res.status})`;
    let data = null;
    try {
      data = await res.json();
      if (data && data.detail) errMsg = data.detail;
    } catch (_) {}

    if (
      res.status === 403 &&
      data?.code === "csrf_failed" &&
      !_csrfRetried &&
      isProtectedMutation
    ) {
      const refreshed = await ensureCsrfCookie(true);
      if (refreshed && getCsrfToken()) {
        return api(path, { ...rawOptions, _csrfRetried: true });
      }
    }

    if (
      res.status === 401 &&
      res.headers.get("X-Session-Expired") === "idle" &&
      typeof window.__handleIdleSessionExpired === "function"
    ) {
      window.__handleIdleSessionExpired(errMsg);
    }
    const err = new Error(errMsg);
    err.status = res.status;
    err.code = data?.code || null;
    throw err;
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  return res;
}

export async function downloadAuthenticatedFile(url, fallbackName) {
  try {
    const res = await fetch(url, { credentials: "same-origin" });
    if (!res.ok) {
      let msg = `Gagal mengunduh berkas (${res.status})`;
      try {
        const d = await res.json();
        if (d.detail) msg = d.detail;
      } catch (_) {}
      return toast(msg, true);
    }
    const blob = await res.blob();
    const disp = res.headers.get("content-disposition") || "";
    const match = disp.match(/filename="?([^"]+)"?/i);
    const filename = match ? match[1] : fallbackName;
    const objUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(objUrl), 2500);
  } catch (err) {
    toast(err.message || "Gagal mengunduh berkas.", true);
  }
}
