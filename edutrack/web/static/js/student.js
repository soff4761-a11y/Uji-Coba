/**
 * Modul Portal Peserta Didik (ES Module v7):
 * - Sapaan dinamis & jam real-time
 * - Filter Materi Pembelajaran + 3 Diagram Donat Seragam
 * - Papan Pengumuman Kelas (Read-Only)
 * - Riwayat Kehadiran, Permintaan Koreksi (+ Hapus)
 * - Ubah Username Siswa, Ganti Sandi, & Manajemen Sesi Aktif
 */

import { api, downloadAuthenticatedFile } from "./api.js?v=20261120-v8.4.2";
import { DOUGHNUT_PALETTE, renderDoughnutChart, renderLineChart } from "./charts.js?v=20261120-v8.4.2";
import { escapeHtml, onById, showView, state, toast } from "./state.js?v=20261120-v8.4.2";

let _studentClockTimer = null;
let studentEwsKeyHandler = null;
let studentEwsPrevFocus = null;
let studentEwsShownInSession = false;
let studentRevealKeyHandler = null;
let studentRevealPrevFocus = null;
let queuedRevealItems = [];

function getIndonesianGreeting(hour) {
  if (hour >= 4 && hour < 11) return "Selamat Pagi";
  if (hour >= 11 && hour < 15) return "Selamat Siang";
  if (hour >= 15 && hour < 18) return "Selamat Sore";
  return "Selamat Malam";
}

export function dismissStudentEwsPopup() {
  if (studentEwsKeyHandler && typeof document.removeEventListener === "function") {
    document.removeEventListener("keydown", studentEwsKeyHandler);
    studentEwsKeyHandler = null;
  }
  const existing = document.getElementById("student-ews-popup");
  if (existing) existing.remove();
  if (document.body && document.body.style) {
    document.body.style.overflow = "";
  }
  if (studentEwsPrevFocus && typeof studentEwsPrevFocus.focus === "function") {
    try { studentEwsPrevFocus.focus(); } catch (_) {}
  }
  studentEwsPrevFocus = null;
  if (queuedRevealItems.length > 0 && state.user && state.user.role === "student") {
    const nextQueue = queuedRevealItems;
    queuedRevealItems = [];
    showStudentRevealPopup(nextQueue);
  }
}

export function dismissStudentRevealPopup() {
  if (studentRevealKeyHandler && typeof document.removeEventListener === "function") {
    document.removeEventListener("keydown", studentRevealKeyHandler);
    studentRevealKeyHandler = null;
  }
  const existing = document.getElementById("student-reveal-popup");
  if (existing) existing.remove();
  if (document.body && document.body.style && !document.getElementById("student-ews-popup")) {
    document.body.style.overflow = "";
  }
  if (studentRevealPrevFocus && typeof studentRevealPrevFocus.focus === "function") {
    try { studentRevealPrevFocus.focus(); } catch (_) {}
  }
  studentRevealPrevFocus = null;
}

export function resetStudentModalSessionState() {
  queuedRevealItems = [];
  studentEwsShownInSession = false;
  dismissStudentRevealPopup();
  dismissStudentEwsPopup();
}

function applyRevealedScoreToLocalState(assessmentId, revealedAt) {
  const dash = state.studentDashboard;
  if (!dash) return;
  const mark = (arr) => {
    for (const item of (arr || [])) {
      if (Number(item.assessment_id) === Number(assessmentId)) {
        item.needs_reveal = false;
        item.revealed_at = revealedAt;
      }
    }
  };
  mark(dash.grade_timeline);
  mark(dash.all_grade_timeline);
  dash.pending_reveals = (dash.pending_reveals || []).filter(
    (item) => Number(item.assessment_id) !== Number(assessmentId)
  );
  renderStudentGradesAndCharts(dash);
}

export function showStudentRevealPopup(items) {
  const queue = Array.isArray(items) ? items.filter((i) => i && i.needs_reveal) : [];
  if (!queue.length) return null;
  dismissStudentRevealPopup();

  studentRevealPrevFocus = typeof document !== "undefined" ? document.activeElement || null : null;
  let currentIdx = 0;

  const el = document.createElement("div");
  el.id = "student-reveal-popup";
  el.className = "reveal-modal-backdrop";

  const renderStep = (revealedPayload = null) => {
    const item = queue[currentIdx];
    if (!item) {
      dismissStudentRevealPopup();
      return;
    }
    const stepText = queue.length > 1 ? `Nilai ${currentIdx + 1} dari ${queue.length}` : "Nilai Baru Tersedia";
    const isRevealed = Boolean(revealedPayload);
    const bodyHtml = isRevealed
      ? `<div class="reveal-score-box">
          <div class="reveal-score-label">Nilai Anda</div>
          <div class="reveal-score-value">${escapeHtml(revealedPayload.normalized_score ?? "-")}</div>
          <div class="reveal-score-sub">Skor: ${escapeHtml(revealedPayload.raw_score)} / ${escapeHtml(revealedPayload.max_score)}</div>
        </div>`
      : `<div class="reveal-score-box">
          <div class="reveal-score-label">Nilai Tersembunyi</div>
          <div class="reveal-score-value">?</div>
          <div class="reveal-score-sub">Klik tombol Lihat untuk membuka nilai ${escapeHtml(item.category)} ini.</div>
        </div>`;
    const primaryLabel = isRevealed
      ? (currentIdx + 1 < queue.length ? "Nilai Berikutnya" : "Selesai")
      : "Lihat";

    el.innerHTML = `
      <div class="reveal-modal-dialog" role="dialog" aria-modal="true" aria-labelledby="reveal-modal-title">
        <div class="reveal-head">
          <div>
            <span class="badge badge-reveal-accent">${escapeHtml(item.category)} &middot; ${escapeHtml(stepText)}</span>
            <h2 id="reveal-modal-title" class="reveal-title">${escapeHtml(item.title)}</h2>
          </div>
          <button type="button" id="btn-reveal-close" class="reveal-close" aria-label="Tutup jendela nilai">×</button>
        </div>
        <p class="reveal-meta">${escapeHtml(item.material_title || "Umum")} (${escapeHtml(item.date || "")})</p>
        ${bodyHtml}
        <div class="reveal-actions">
          <button type="button" id="btn-reveal-action" class="reveal-btn-primary">${primaryLabel}</button>
        </div>
      </div>
    `;

    const closeBtn = typeof el.querySelector === "function" ? el.querySelector("#btn-reveal-close") : document.getElementById("btn-reveal-close");
    const actionBtn = typeof el.querySelector === "function" ? el.querySelector("#btn-reveal-action") : document.getElementById("btn-reveal-action");
    if (closeBtn) closeBtn.addEventListener("click", () => dismissStudentRevealPopup());
    if (actionBtn) {
      actionBtn.addEventListener("click", async () => {
        if (!isRevealed) {
          actionBtn.disabled = true;
          actionBtn.textContent = "Membuka...";
          try {
            const res = await api(`/api/student/grades/${item.assessment_id}/reveal`, { method: "POST" });
            applyRevealedScoreToLocalState(item.assessment_id, res.revealed_at);
            renderStep(res);
          } catch (err) {
            toast(err.message || "Gagal membuka nilai.", true);
            actionBtn.disabled = false;
            actionBtn.textContent = "Lihat";
          }
        } else {
          currentIdx += 1;
          if (currentIdx < queue.length) {
            renderStep(null);
          } else {
            dismissStudentRevealPopup();
          }
        }
      });
      try { actionBtn.focus(); } catch (_) {}
    }
  };

  if (document.body) {
    document.body.appendChild(el);
    if (document.body.style) document.body.style.overflow = "hidden";
  }
  renderStep(null);

  if (typeof document.addEventListener === "function") {
    studentRevealKeyHandler = (evt) => {
      if (evt.key === "Escape") {
        dismissStudentRevealPopup();
        return;
      }
      if (evt.key === "Tab") {
        const closeBtn = el.querySelector("#btn-reveal-close");
        const actionBtn = el.querySelector("#btn-reveal-action");
        if (closeBtn && actionBtn) {
          const focusables = [closeBtn, actionBtn];
          const idx = focusables.indexOf(document.activeElement);
          if (evt.shiftKey && idx <= 0) {
            if (typeof evt.preventDefault === "function") evt.preventDefault();
            actionBtn.focus();
          } else if (!evt.shiftKey && idx === focusables.length - 1) {
            if (typeof evt.preventDefault === "function") evt.preventDefault();
            closeBtn.focus();
          }
        }
      }
    };
    document.addEventListener("keydown", studentRevealKeyHandler);
  }
  return el;
}

function renderStudentMaterialComparison(data) {
  const leftSel = document.getElementById("s-compare-mat-left");
  const rightSel = document.getElementById("s-compare-mat-right");
  const source = (data.all_grade_timeline || data.grade_timeline || []).filter(
    (p) => !p.needs_reveal && p.normalized_score !== null && p.normalized_score !== undefined
  );

  const filterPoints = (matVal) => {
    const filtered = matVal
      ? source.filter((p) => String(p.material_id ?? "") === String(matVal))
      : source;
    if (!filtered.length) return [];
    const label = matVal
      ? (data.materials || []).find((m) => String(m.id) === String(matVal))?.title || "Materi"
      : "Semua Materi";
    return [
      {
        name: label,
        points: filtered.map((p) => ({ label: p.title, value: p.normalized_score })),
      },
    ];
  };

  const leftVal = leftSel ? leftSel.value : "";
  const rightVal = rightSel ? rightSel.value : "";
  renderLineChart("chart-s-compare-left", filterPoints(leftVal));
  renderLineChart("chart-s-compare-right", filterPoints(rightVal));
}

function renderStudentGradesAndCharts(data) {
  const gs = data.grade_summary;
  const att = data.attendance_summary;

  // 1. Perkembangan Nilai Pribadi (sembunyikan nilai kejutan yg belum dibuka)
  const publishedTrend = (data.grade_timeline || []).filter(
    (p) => !p.needs_reveal && p.normalized_score !== null && p.normalized_score !== undefined
  );
  let trendBadge = "";
  const trendRaw = String(gs.trend_indicator || "").toLowerCase();
  if (trendRaw && trendRaw !== "belum_cukup_data" && trendRaw !== "data belum cukup") {
    const deltaVal = gs.trend_delta != null ? (gs.trend_delta > 0 ? `+${gs.trend_delta}` : `${gs.trend_delta}`) : "";
    const labelMap = { meningkat: "Meningkat", menurun: "Menurun", stabil: "Stabil" };
    trendBadge = `${deltaVal} ${labelMap[trendRaw] || gs.trend_indicator}`.trim();
  } else if (publishedTrend.length === 1) {
    trendBadge = "1 Penilaian";
  }
  renderDoughnutChart("chart-s-trend", {
    centerValue: gs.final_score !== null && gs.final_score !== undefined ? gs.final_score : "-",
    centerLabel: "Nilai Akhir",
    centerBadge: trendBadge,
    segments: publishedTrend.map((p, idx) => ({
      label: `${p.title}${p.date ? " (" + p.date + ")" : ""}`,
      value: Math.max(Number(p.normalized_score), 0.01),
      displayValue: `${p.normalized_score}`,
      color: DOUGHNUT_PALETTE[idx % DOUGHNUT_PALETTE.length],
    })),
    emptyMessage: state.studentSelectedMaterialId ? "Belum ada penilaian pada materi ini" : "Belum ada data penilaian",
  });

  // 2. Capaian per Kategori
  const catItems = (data.category_comparison || []).filter((c) => c.average !== null && c.average !== undefined);
  const catOverallAvg = catItems.length
    ? Math.round((catItems.reduce((acc, c) => acc + Number(c.average), 0) / catItems.length) * 10) / 10
    : "-";
  renderDoughnutChart("chart-s-category", {
    centerValue: catOverallAvg,
    centerLabel: "Rata-Rata Kategori",
    centerBadge: catItems.length ? `${catItems.length} Kategori` : "",
    segments: catItems.map((c, idx) => ({
      label: c.category,
      value: Math.max(Number(c.average), 0.01),
      displayValue: `${c.average}`,
      color: DOUGHNUT_PALETTE[idx % DOUGHNUT_PALETTE.length],
    })),
    emptyMessage: state.studentSelectedMaterialId ? "Belum ada penilaian pada materi ini" : "Belum ada data penilaian",
  });

  // 3. Ringkasan Kehadiran Pribadi
  renderDoughnutChart("chart-s-attendance", {
    centerValue: att.attendance_percentage != null ? `${att.attendance_percentage}%` : "-",
    centerLabel: "Kehadiran",
    centerBadge: att.total_recorded ? `${att.total_recorded} Pertemuan` : "",
    segments: [
      { label: "Hadir", value: att.hadir || 0, displayValue: `${att.hadir || 0}x`, color: "#34d399" },
      { label: "Sakit", value: att.sakit || 0, displayValue: `${att.sakit || 0}x`, color: "#fbbf24" },
      { label: "Izin", value: att.izin || 0, displayValue: `${att.izin || 0}x`, color: "#38bdf8" },
      { label: "Alpa", value: att.alpa || 0, displayValue: `${att.alpa || 0}x`, color: "#f87171" },
    ],
    emptyMessage: "Belum ada data kehadiran",
  });

  // 4. Perbandingan Tren Antarmateri (Kiri vs Kanan)
  renderStudentMaterialComparison(data);

  // 5. Tabel Nilai Bernilai (dengan tombol Lihat untuk Ujian/Asesmen Sumatif yg belum dibuka)
  const gradesBody = document.getElementById("s-grades-tbody");
  if (gradesBody) {
    gradesBody.innerHTML = data.grade_timeline.length
      ? data.grade_timeline
          .map((g) => {
            const scoreCell = g.needs_reveal
              ? `<button type="button" class="btn-reveal-inline" data-reveal-id="${g.assessment_id}">Lihat</button>`
              : g.raw_score === null
              ? "<span class='muted'>Belum dinilai</span>"
              : `${g.raw_score} / ${g.max_score}`;
            const normCell = g.needs_reveal
              ? `<span class="badge badge-surprise">Terkunci</span>`
              : `<strong>${g.normalized_score ?? "-"}</strong>`;
            return `<tr>
              <td>${escapeHtml(g.date)}</td>
              <td><span class="badge">${escapeHtml(g.material_title || "Belum Dikelompokkan")}</span></td>
              <td><strong>${escapeHtml(g.title)}</strong><div class="small muted">${escapeHtml(g.description)}</div></td>
              <td><span class="badge badge-blue">${escapeHtml(g.category)}</span></td>
              <td>${scoreCell}</td>
              <td>${normCell}</td>
              <td>${escapeHtml(g.feedback || "-")}</td>
            </tr>`;
          })
          .join("")
      : `<tr><td colspan="7" class="muted">Belum ada penilaian yang dipublikasikan pada pilihan materi ini.</td></tr>`;
  }
}

export function showStudentEwsPopup(ews, _legacyDurationMs = 0) {
  if (!ews || !ews.is_triggered) return null;
  dismissStudentEwsPopup();

  studentEwsPrevFocus = typeof document !== "undefined" ? document.activeElement || null : null;
  const severityClass =
    ews.severity === "kritis" ? "ews-popup--kritis" : "ews-popup--perhatian";
  const titleText =
    ews.title || (ews.severity === "kritis" ? "Peringatan Kritis (EWS)" : "Peringatan Dini (EWS)");
  const reasons = Array.isArray(ews.reasons) ? ews.reasons : [];

  const el = document.createElement("div");
  el.id = "student-ews-popup";
  el.className = `ews-popup ews-modal-backdrop ${severityClass}`;

  const listHtml = reasons.length
    ? `<ul class="ews-popup-list">${reasons.map((r) => `<li>${escapeHtml(r)}</li>`).join("")}</ul>`
    : `<p class="ews-popup-msg">${escapeHtml(ews.message || "Status akademik Anda melewati batas peringatan dini.")}</p>`;

  const warnIconSvg = `<svg class="ews-popup-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;

  const sevBadgeClass = ews.severity === "kritis" ? "badge-ews-kritis" : "badge-ews-perhatian";
  const sevBadgeLabel = ews.severity === "kritis" ? "Peringatan Kritis" : "Peringatan Dini";

  el.innerHTML = `
    <div class="ews-modal-dialog" role="dialog" aria-modal="true" aria-labelledby="ews-modal-title">
      <div class="ews-popup-head">
        <div>
          <span class="badge ${sevBadgeClass}">${sevBadgeLabel}</span>
          <div class="ews-popup-title-wrap">
            ${warnIconSvg}
            <h2 id="ews-modal-title" class="ews-popup-title">${escapeHtml(titleText)}</h2>
          </div>
        </div>
        <button type="button" id="btn-ews-close" class="ews-popup-close" aria-label="Tutup peringatan">×</button>
      </div>
      <p class="ews-popup-lead">Status belajar Anda memerlukan tindak lanjut berdasarkan indikator berikut:</p>
      <div class="ews-popup-box">
        ${listHtml}
      </div>
      <div class="ews-popup-actions">
        <button type="button" id="btn-ews-ack" class="ews-popup-ack">Mengerti</button>
      </div>
    </div>
  `;

  if (document.body) {
    document.body.appendChild(el);
    if (document.body.style) {
      document.body.style.overflow = "hidden";
    }
  }

  const ackBtn = typeof el.querySelector === "function" ? el.querySelector("#btn-ews-ack") : document.getElementById("btn-ews-ack");
  const closeBtn = typeof el.querySelector === "function" ? el.querySelector("#btn-ews-close") : document.getElementById("btn-ews-close");
  if (ackBtn && typeof ackBtn.addEventListener === "function") {
    ackBtn.addEventListener("click", () => dismissStudentEwsPopup());
  }
  if (closeBtn && typeof closeBtn.addEventListener === "function") {
    closeBtn.addEventListener("click", () => dismissStudentEwsPopup());
  }
  if (ackBtn && typeof ackBtn.focus === "function") {
    try { ackBtn.focus(); } catch (_) {}
  }

  if (typeof document.addEventListener === "function") {
    studentEwsKeyHandler = (evt) => {
      if (evt.key === "Escape") {
        dismissStudentEwsPopup();
        return;
      }
      if (evt.key === "Tab" && closeBtn && ackBtn) {
        const focusables = [closeBtn, ackBtn];
        const idx = focusables.indexOf(document.activeElement);
        if (evt.shiftKey) {
          if (idx <= 0) {
            if (typeof evt.preventDefault === "function") evt.preventDefault();
            if (typeof ackBtn.focus === "function") ackBtn.focus();
          }
        } else if (idx === focusables.length - 1) {
          if (typeof evt.preventDefault === "function") evt.preventDefault();
          if (typeof closeBtn.focus === "function") closeBtn.focus();
        }
      }
    };
    document.addEventListener("keydown", studentEwsKeyHandler);
  }
  return el;
}

export function startStudentRealtimeClock(fullName) {
  const firstName = String(fullName || "").trim().split(/\s+/)[0] || "Peserta Didik";
  const updateClock = () => {
    const now = new Date();
    const welcomeEl = document.getElementById("st-welcome");
    const clockTextEl = document.getElementById("st-clock-text");
    if (welcomeEl) {
      welcomeEl.textContent = `Halo, ${getIndonesianGreeting(now.getHours())}, ${firstName}!`;
    }
    if (clockTextEl) {
      const dateStr = now.toLocaleDateString("id-ID", {
        weekday: "long",
        day: "numeric",
        month: "long",
        year: "numeric",
      });
      const timeStr = now
        .toLocaleTimeString("id-ID", {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        })
        .replace(/\./g, ":");
      clockTextEl.textContent = `${dateStr} • ${timeStr}`;
    }
  };
  updateClock();
  if (_studentClockTimer) clearInterval(_studentClockTimer);
  _studentClockTimer = setInterval(updateClock, 1000);
}

export function renderStudentAnnouncements(items) {
  const box = document.getElementById("s-announcements-list");
  if (!box) return;
  if (!items || !items.length) {
    box.innerHTML = `<p class="muted small">Belum ada pengumuman untuk kelas ini.</p>`;
    return;
  }
  box.innerHTML = items
    .map(
      (a) => `<article class="announcement-card ${a.is_pinned ? "pinned" : ""}">
        <div class="announcement-head">
          <div>
            <strong>${escapeHtml(a.title)}</strong>
            <div class="small muted">${escapeHtml((a.updated_at || a.created_at || "").slice(0, 16).replace("T", " "))}</div>
          </div>
          <div class="row gap-sm">
            ${a.is_pinned ? `<span class="badge badge-blue">Disematkan</span>` : ""}
            <span class="badge">${escapeHtml(a.category)}</span>
          </div>
        </div>
        <div class="announcement-body">${escapeHtml(a.content)}</div>
      </article>`
    )
    .join("");
}

export function renderStudentAttendanceRows(records) {
  const tbody = document.getElementById("s-att-tbody");
  if (!tbody) return;
  tbody.innerHTML = records.length
    ? records
        .map((r) => {
          const badge =
            r.status === "hadir" ? "badge-green" : r.status === "alpa" ? "badge-red" : "badge-amber";
          return `<tr>
            <td>${escapeHtml(r.session_date)}</td>
            <td>Pertemuan #${r.meeting_number}</td>
            <td>${escapeHtml(r.topic || "-")}</td>
            <td>${escapeHtml(r.class_name)}</td>
            <td><span class="badge ${badge}">${escapeHtml(r.status.toUpperCase())}</span></td>
            <td>${escapeHtml(r.note || "-")}</td>
          </tr>`;
        })
        .join("")
    : `<tr><td colspan="6" class="muted">Belum ada catatan kehadiran pada periode ini.</td></tr>`;
}

export function populateStudentCorrectionTargets() {
  if (!state.studentDashboard) return;
  const type = document.getElementById("sc-type")?.value;
  const sel = document.getElementById("sc-target");
  if (!sel) return;
  if (type === "grade") {
    const gradedOpts = (state.studentDashboard.grade_timeline || []).map(
      (g) => `<option value="${g.assessment_id}">${escapeHtml(g.date)} - ${escapeHtml(g.title)}</option>`
    );
    const checklistOpts = (state.studentDashboard.checklist_tasks || []).map(
      (c) => `<option value="${c.assessment_id}">${escapeHtml(c.date)} - [Checklist] ${escapeHtml(c.title)}</option>`
    );
    sel.innerHTML = [...gradedOpts, ...checklistOpts].join("");
  } else {
    sel.innerHTML = state.studentDashboard.attendance_records
      .map((r) => `<option value="${r.id}">${escapeHtml(r.session_date)} — Pertemuan #${r.meeting_number} (${r.status})</option>`)
      .join("");
  }
}

export async function loadStudentCorrections() {
  const res = await api("/api/student/corrections");
  const tbody = document.getElementById("s-corrections-tbody");
  if (!tbody) return;
  tbody.innerHTML = res.corrections.length
    ? res.corrections
        .map(
          (c) => `<tr>
            <td>${escapeHtml(c.target_type)} #${c.target_id}</td>
            <td>${escapeHtml(c.message)}</td>
            <td><span class="badge ${c.status === "pending" ? "badge-amber" : "badge-green"}">${escapeHtml(c.status)}</span></td>
            <td>${escapeHtml(c.teacher_response || "-")}</td>
            <td><button class="btn btn-danger btn-pill btn-sm" type="button" onclick="deleteStudentCorrection(${c.id}, '${escapeHtml(c.status)}')">Hapus</button></td>
          </tr>`
        )
        .join("")
    : `<tr><td colspan="5" class="muted">Belum ada riwayat permintaan koreksi.</td></tr>`;
}

export async function loadActiveSessions(tbodyId) {
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;
  try {
    const res = await api("/api/auth/sessions");
    const list = res.sessions || [];
    tbody.innerHTML = list.length
      ? list
          .map(
            (s) => `<tr>
              <td><strong>${escapeHtml(s.device_label || "Perangkat")}</strong></td>
              <td class="small">${escapeHtml(s.ip_address || "-")}</td>
              <td class="small">${escapeHtml((s.created_at || "").slice(0, 16).replace("T", " "))}</td>
              <td class="small">${escapeHtml((s.last_activity_at || "").slice(0, 16).replace("T", " "))}</td>
              <td>${s.is_current ? `<span class="badge badge-green">Perangkat Ini</span>` : `<span class="badge badge-blue">Aktif</span>`}</td>
              <td><button class="btn btn-danger btn-pill btn-sm" type="button" onclick="revokeUserSession(${s.id}, '${tbodyId}')">${s.is_current ? "Keluar" : "Cabut"}</button></td>
            </tr>`
          )
          .join("")
      : `<tr><td colspan="6" class="muted">Tidak ada sesi aktif tercatat.</td></tr>`;
  } catch (_) {
    tbody.innerHTML = `<tr><td colspan="6" class="muted">Gagal memuat sesi aktif.</td></tr>`;
  }
}

export async function initStudentPortal(materialId = null) {
  const hasMat = materialId !== null && materialId !== undefined && materialId !== "";
  const qs = hasMat ? `?material_id=${encodeURIComponent(materialId)}` : "";
  const data = await api(`/api/student/dashboard${qs}`);
  if (!state.user || state.user.role !== "student") return;
  state.studentSelectedMaterialId = hasMat ? Number(materialId) : null;
  state.studentDashboard = data;

  const matSel = document.getElementById("s-filter-material");
  if (matSel) {
    const mats = data.materials || [];
    matSel.innerHTML =
      `<option value="">Semua Materi</option>` +
      mats
        .map((m) => `<option value="${m.id}" ${Number(materialId) === m.id ? "selected" : ""}>${escapeHtml(m.title)}</option>`)
        .join("");
  }

  const nameEl = document.getElementById("st-header-name");
  const classEl = document.getElementById("st-header-class");
  const userEl = document.getElementById("student-user-label");
  const unameInput = document.getElementById("su-new-username");
  if (nameEl) nameEl.textContent = data.student.full_name;
  if (classEl) {
    classEl.textContent = `NIS ${data.student.student_code} • Kelas ${data.classroom.name} (${data.classroom.education_level})`;
  }
  if (userEl) userEl.textContent = `@${data.student.username}`;
  if (unameInput) unameInput.value = data.student.username || "";
  startStudentRealtimeClock(data.student.full_name);

  const dlBox = document.getElementById("st-download-box");
  if (dlBox) dlBox.classList.toggle("hidden", !data.classroom.allow_student_report_download);

  const gs = data.grade_summary;
  const att = data.attendance_summary;
  const kpiEl = document.getElementById("s-kpi-grid");
  if (kpiEl) {
    kpiEl.innerHTML = `
      <div class="kpi-card"><div class="kpi-label">Nilai Akhir</div><div class="kpi-value">${gs.final_score ?? "-"}</div><div class="kpi-sub">Tren: ${escapeHtml(gs.trend_indicator)}</div></div>
      <div class="kpi-card"><div class="kpi-label">Kehadiran</div><div class="kpi-value">${att.attendance_percentage != null ? att.attendance_percentage + "%" : "-"}</div><div class="kpi-sub">${att.hadir} dari ${att.total_recorded} pertemuan</div></div>
      <div class="kpi-card"><div class="kpi-label">Sakit / Izin / Alpa</div><div class="kpi-value">${att.sakit} / ${att.izin} / ${att.alpa}</div><div class="kpi-sub">Berdasarkan pertemuan tercatat</div></div>
      <div class="kpi-card"><div class="kpi-label">Penilaian Dipublikasikan</div><div class="kpi-value">${gs.graded_assessments} / ${gs.total_assessments}</div><div class="kpi-sub">KKM Kelas: ${data.classroom.mastery_threshold}</div></div>
    `;
  }

  const mats = data.materials || [];
  const matOptsHtml =
    `<option value="">Semua Materi</option>` +
    mats.map((m) => `<option value="${m.id}">${escapeHtml(m.title)}</option>`).join("");
  const sCmpLeft = document.getElementById("s-compare-mat-left");
  const sCmpRight = document.getElementById("s-compare-mat-right");
  if (sCmpLeft) {
    const prevL = sCmpLeft.value;
    sCmpLeft.innerHTML = matOptsHtml;
    if (prevL && mats.some((m) => String(m.id) === prevL)) sCmpLeft.value = prevL;
    else if (mats.length >= 2) sCmpLeft.value = String(mats[0].id);
  }
  if (sCmpRight) {
    const prevR = sCmpRight.value;
    sCmpRight.innerHTML = matOptsHtml;
    if (prevR && mats.some((m) => String(m.id) === prevR)) sCmpRight.value = prevR;
    else if (mats.length >= 2) sCmpRight.value = String(mats[1].id);
  }

  renderStudentGradesAndCharts(data);

  const checklistBody = document.getElementById("s-checklist-tbody");
  if (checklistBody) {
    const checklistTasks = data.checklist_tasks || [];
    checklistBody.innerHTML = checklistTasks.length
      ? checklistTasks
          .map(
            (c) => `<tr>
              <td>${escapeHtml(c.date)}</td>
              <td><span class="badge">${escapeHtml(c.material_title || "Belum Dikelompokkan")}</span></td>
              <td><strong>${escapeHtml(c.title)}</strong><div class="small muted">${escapeHtml(c.description)}</div></td>
              <td><span class="badge badge-blue">${escapeHtml(c.category)}</span></td>
              <td><span class="badge ${c.submitted ? "badge-checklist-done" : "badge-checklist-pending"}">${c.submitted ? "Sudah Mengumpulkan" : "Belum Mengumpulkan"}</span></td>
              <td>${escapeHtml(c.feedback || "-")}</td>
            </tr>`
          )
          .join("")
      : `<tr><td colspan="6" class="muted">Belum ada catatan pada pilihan materi ini.</td></tr>`;
  }

  renderStudentAttendanceRows(data.attendance_records);
  renderStudentAnnouncements(data.announcements || []);
  populateStudentCorrectionTargets();
  await loadStudentCorrections();
  loadActiveSessions("s-sessions-tbody").catch(() => {});
  const pendingReveals = Array.isArray(data.pending_reveals) ? data.pending_reveals : [];
  if (!hasMat && data.early_warning?.is_triggered && !studentEwsShownInSession) {
    studentEwsShownInSession = true;
    queuedRevealItems = pendingReveals;
    showStudentEwsPopup(data.early_warning);
  } else if (!hasMat && pendingReveals.length > 0 && !document.getElementById("student-ews-popup")) {
    showStudentRevealPopup(pendingReveals);
  }
}

export function registerStudentGlobals() {
  Object.assign(window, {
    deleteStudentCorrection: async (requestId, status) => {
      const warn =
        status === "pending"
          ? "Hapus permintaan koreksi yang masih menunggu ini?"
          : "Sembunyikan riwayat permintaan koreksi ini dari dashboard Anda? (Catatan tindak lanjut guru tetap terjaga.)";
      if (!confirm(warn)) return;
      try {
        const res = await api(`/api/student/corrections/${requestId}`, { method: "DELETE" });
        toast(res.message || "Riwayat permintaan koreksi dihapus.");
        await loadStudentCorrections();
      } catch (err) {
        toast(err.message || "Gagal menghapus permintaan koreksi.", true);
      }
    },
    revokeUserSession: async (sessionId, tbodyId) => {
      if (!confirm("Cabut sesi perangkat ini?")) return;
      try {
        const res = await api(`/api/auth/sessions/${sessionId}`, { method: "DELETE" });
        if (res.revoked_current) {
          showView("view-login");
          toast("Sesi perangkat ini telah dicabut.");
          return;
        }
        toast("Sesi perangkat berhasil dicabut.");
        await loadActiveSessions(tbodyId);
      } catch (err) {
        toast(err.message, true);
      }
    },
  });
}

export function bindStudentListeners() {
  const onStudentCompareChange = () => {
    if (state.studentDashboard) renderStudentMaterialComparison(state.studentDashboard);
  };
  onById("s-compare-mat-left", "change", onStudentCompareChange);
  onById("s-compare-mat-right", "change", onStudentCompareChange);
  onById("s-grades-tbody", "click", (e) => {
    const btn = e.target?.closest?.(".btn-reveal-inline");
    if (!btn) return;
    const aid = Number(btn.getAttribute("data-reveal-id"));
    const item = (state.studentDashboard?.grade_timeline || []).find(
      (g) => Number(g.assessment_id) === aid && g.needs_reveal
    );
    if (item) showStudentRevealPopup([item]);
  });
  onById("student-nav", "click", (e) => {
    const btn = e.target.closest(".nav-item");
    if (!btn) return;
    document.querySelectorAll("#student-nav .nav-item").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const tab = btn.dataset.stab;
    document.querySelectorAll(".stab-panel").forEach((p) => p.classList.toggle("hidden", p.id !== `stab-${tab}`));
    if (tab === "s-account") loadActiveSessions("s-sessions-tbody");
    const studentLayout = document.getElementById("view-student");
    if (studentLayout && window.matchMedia("(max-width: 960px)").matches) {
      studentLayout.classList.remove("drawer-open");
    }
  });

  onById("s-filter-material", "change", (e) => {
    const val = e.target.value !== "" ? Number(e.target.value) : null;
    initStudentPortal(val);
  });

  onById("sc-type", "change", populateStudentCorrectionTargets);

  onById("btn-s-att-filter", "click", async () => {
    const month = document.getElementById("s-att-month")?.value || "";
    const res = await api(`/api/student/attendance${month ? "?month=" + encodeURIComponent(month) : ""}`);
    renderStudentAttendanceRows(res.records);
  });

  onById("btn-s-att-reset", "click", async () => {
    const mEl = document.getElementById("s-att-month");
    if (mEl) mEl.value = "";
    const res = await api("/api/student/attendance");
    renderStudentAttendanceRows(res.records);
  });

  onById("form-s-correction", "submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/student/corrections", {
        method: "POST",
        body: {
          target_type: document.getElementById("sc-type").value,
          target_id: Number(document.getElementById("sc-target").value),
          message: document.getElementById("sc-msg").value,
        },
      });
      e.target.reset();
      populateStudentCorrectionTargets();
      toast("Permintaan koreksi berhasil dikirim ke guru.");
      await loadStudentCorrections();
    } catch (err) {
      toast(err.message, true);
    }
  });

  // Fitur baru v7: Siswa ubah username sendiri
  onById("form-s-username", "submit", async (e) => {
    e.preventDefault();
    try {
      const newU = document.getElementById("su-new-username").value;
      const res = await api("/api/student/username", {
        method: "PATCH",
        body: { username: newU },
      });
      if (res.user) {
        state.user = res.user;
        const userEl = document.getElementById("student-user-label");
        if (userEl) userEl.textContent = `@${res.user.username}`;
      }
      toast("Username berhasil diperbarui.");
    } catch (err) {
      toast(err.message, true);
    }
  });

  onById("form-s-password", "submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/auth/change-password", {
        method: "POST",
        body: {
          current_password: document.getElementById("sp-old-pw").value,
          new_password: document.getElementById("sp-new-pw").value,
        },
      });
      e.target.reset();
      toast("Kata sandi berhasil diperbarui dan sesi di perangkat lain dicabut.");
      loadActiveSessions("s-sessions-tbody");
    } catch (err) {
      toast(err.message, true);
    }
  });

  document.querySelectorAll("[data-sexport]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const fmt = btn.dataset.sexport;
      downloadAuthenticatedFile(`/api/reports/individual?fmt=${fmt}`, `laporan_pribadi.${fmt}`);
    });
  });

  onById("btn-refresh-s-sessions", "click", () => loadActiveSessions("s-sessions-tbody"));
}
