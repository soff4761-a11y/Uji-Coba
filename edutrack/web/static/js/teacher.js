/**
 * Modul Portal Guru & Admin EduTrack (ES Module v7):
 * - Dashboard, EWS, Kelas, Pengumuman Kelas, Peserta Didik (+ Bulk Delete & Reset ke NIS/12345678)
 * - Materi Pembelajaran & Buku Nilai, Impor Excel Pratinjau/Konfirmasi
 * - Kehadiran + Antrean Offline PWA & Sinkronisasi Otomatis
 * - Laporan, Koreksi, Log Audit, & Backup (Khusus Admin)
 */

import { api, downloadAuthenticatedFile } from "./api.js?v=20261120-v8.4.2";
import { renderBarChart, renderDoughnutChart, renderLineChart } from "./charts.js?v=20261120-v8.4.2";
import { escapeHtml, onById, setHtml, state, toast } from "./state.js?v=20261120-v8.4.2";
import { loadActiveSessions } from "./student.js?v=20261120-v8.4.2";

// --- PORTAL GURU ---

async function initTeacherPortal() {
  if (document.getElementById("teacher-user-label")) document.getElementById("teacher-user-label").textContent = `${state.user.full_name} (@${state.user.username})`;
  document.getElementById("tp-username").value = state.user.username || "";
  document.getElementById("tp-name").value = state.user.full_name || "";
  document.getElementById("tp-email").value = state.user.email || "";
  document.getElementById("a-date").value = new Date().toISOString().slice(0, 10);
  document.getElementById("att-date").value = new Date().toISOString().slice(0, 10);
  await refreshTeacherPeriodsAndClasses();
  if (state.classes && state.classes.length) {
    try { localStorage.setItem(_offlineKey("classes"), JSON.stringify(state.classes)); } catch (_) {}
  }
  await loadTeacherDashboard();
  updateOfflineSyncBanner();
  loadEarlyWarningSystem();
  loadTeacherAnnouncements();
  loadActiveSessions("t-sessions-tbody");
  syncOfflineAttendanceQueue();
}

async function refreshTeacherPeriodsAndClasses() {
  const showArchivedEl = document.getElementById("chk-show-archived");
  const showArchived = showArchivedEl ? showArchivedEl.checked : false;
  const cRes = await api(`/api/teacher/classes?include_archived=${showArchived}`);
  state.classes = cRes.classes;
  if (!state.classes.some((c) => c.id === state.selectedClassId)) {
    state.selectedClassId = state.classes[0]?.id || null;
  }

  const cSel = document.getElementById("filter-class");
  const classOptions = state.classes
    .map((c) => `<option value="${c.id}" ${c.id === state.selectedClassId ? "selected" : ""}>${escapeHtml(c.name)}</option>`)
    .join("");
  if (cSel) cSel.innerHTML = `<option value="">Semua Kelas</option>` + classOptions;

  const emptyOpt = `<option value="">Belum ada kelas — buat kelas terlebih dahulu</option>`;
  for (const selId of ["s-class-id", "import-class-id", "att-class-id"]) {
    const el = document.getElementById(selId);
    if (el) {
      if (el) el.innerHTML = classOptions || emptyOpt;
      if (state.selectedClassId) el.value = String(state.selectedClassId);
    }
  }

  renderPeriodsAndClassesTables();
}

function renderPeriodsAndClassesTables() {
  const tbody = document.getElementById("t-classes-tbody");
  if (!tbody) return;
  if (tbody) tbody.innerHTML = state.classes.length
    ? state.classes
        .map(
          (c) => `<tr>
            <td><strong>${escapeHtml(c.name)}</strong><div class="small muted">${escapeHtml(c.description)}</div></td>
            <td>${escapeHtml(c.education_level)}</td>
            <td>${c.calculation_mode === "weighted" ? "Berbobot" : "Rata-rata"}</td>
            <td>${c.mastery_threshold}</td>
            <td>${c.is_archived ? `<span class="badge badge-amber">Arsip</span>` : `<span class="badge badge-green">Aktif</span>`}</td>
            <td class="row gap-sm">
              <button class="btn btn-secondary btn-pill btn-sm" onclick="editClass(${c.id})">Ubah</button>
              <button class="btn btn-secondary btn-pill btn-sm" onclick="resetClassData(${c.id})">Reset</button>
              <button class="btn btn-secondary btn-pill btn-sm" onclick="toggleArchiveClass(${c.id}, ${!c.is_archived})">${c.is_archived ? "Pulihkan" : "Arsipkan"}</button>
              <button class="btn btn-danger btn-pill btn-sm" onclick="deleteClass(${c.id})">Hapus</button>
            </td>
          </tr>`
        )
        .join("")
    : `<tr><td colspan="6" class="muted">Belum ada kelas. Tambahkan kelas secara manual di formulir atas.</td></tr>`;
}

window.editClass = async (id) => {
  const cls = state.classes.find((c) => c.id === id);
  if (!cls) return;
  const name = prompt("Ubah Nama Kelas:", cls.name);
  if (name === null || !name.trim()) return;
  const level = prompt("Ubah Tingkat / Mata Pelajaran:", cls.education_level);
  if (level === null || !level.trim()) return;
  const kkmRaw = prompt("Ubah KKM (0-100):", String(cls.mastery_threshold));
  if (kkmRaw === null) return;
  const desc = prompt("Ubah Keterangan (opsional):", cls.description || "");
  if (desc === null) return;
  try {
    await api(`/api/teacher/classes/${id}`, {
      method: "PATCH",
      body: {
        name: name.trim(),
        education_level: level.trim(),
        mastery_threshold: Number(kkmRaw),
        description: desc.trim(),
      },
    });
    toast("Data kelas berhasil diperbarui.");
    await refreshTeacherPeriodsAndClasses();
    await loadTeacherDashboard();
  } catch (err) {
    toast(err.message, true);
  }
};

window.resetClassData = async (id) => {
  const cls = state.classes.find((c) => c.id === id);
  const label = cls ? cls.name : `#${id}`;
  if (!confirm(`Reset seluruh data nilai dan kehadiran pada kelas "${label}"? (Daftar kelas dan peserta didik tetap aman.)`)) return;
  try {
    const res = await api(`/api/teacher/classes/${id}/reset`, {
      method: "POST",
      body: { reset_grades: true, reset_attendance: true },
    });
    toast(`Kelas direset (${res.cleared_grades} nilai & ${res.cleared_attendance} kehadiran dihapus).`);
    state.selectedSessionId = null;
    await loadTeacherDashboard();
  } catch (err) {
    toast(err.message, true);
  }
};

window.toggleArchiveClass = async (id, archive) => {
  try {
    await api(`/api/teacher/classes/${id}`, { method: "PATCH", body: { is_archived: archive } });
    toast(archive ? "Kelas diarsipkan (riwayat tetap tersimpan)." : "Kelas dipulihkan.");
    await refreshTeacherPeriodsAndClasses();
  } catch (err) {
    toast(err.message, true);
  }
};

window.deleteClass = async (id) => {
  try {
    const dep = await api(`/api/teacher/classes/${id}/dependencies`);
    if (dep.has_related_data) {
      const c = dep.counts;
      const parts = [];
      if (c.students) parts.push(`${c.students} peserta didik`);
      if (c.assessments || c.grades) parts.push(`${c.assessments} penilaian / ${c.grades} nilai`);
      if (c.attendance_sessions || c.attendance_records) parts.push(`${c.attendance_sessions} sesi / ${c.attendance_records} kehadiran`);
      if (c.enrollments && !c.students) parts.push(`${c.enrollments} riwayat kepindahan`);
      const wantArchive = confirm(
        `Kelas "${dep.class_name}" masih memiliki data terkait (${parts.join(", ")}).\n\n` +
        `Penghapusan permanen dinonaktifkan agar nilai dan riwayat kehadiran peserta didik tidak hilang.\n` +
        `Apakah Anda ingin MENGARSIPKAN kelas ini sebagai gantinya?`
      );
      if (wantArchive && !dep.is_archived) {
        await api(`/api/teacher/classes/${id}`, { method: "PATCH", body: { is_archived: true } });
        toast(`Kelas "${dep.class_name}" berhasil diarsipkan dengan aman.`);
        await refreshTeacherPeriodsAndClasses();
        await loadTeacherDashboard();
      }
      return;
    }
    if (!confirm(`Kelas "${dep.class_name}" tidak memiliki data terkait. Hapus permanen kelas ini?`)) return;
    await api(`/api/teacher/classes/${id}?confirm_permanent=true`, { method: "DELETE" });
    toast(`Kelas "${dep.class_name}" berhasil dihapus permanen.`);
    await refreshTeacherPeriodsAndClasses();
    await loadTeacherDashboard();
  } catch (err) {
    toast(err.message || "Gagal memproses penghapusan kelas.", true);
  }
};

async function loadTeacherDashboard() {
  const qs = new URLSearchParams();
  if (state.selectedClassId) qs.set("class_id", state.selectedClassId);
  const data = await api(`/api/teacher/dashboard?${qs.toString()}`);

  const gs = data.grade_statistics;
  const att = data.attendance_summary;
  if (document.getElementById("t-kpi-grid")) document.getElementById("t-kpi-grid").innerHTML = `
    <div class="kpi-card"><div class="kpi-label">Kelas Dikelola</div><div class="kpi-value">${data.total_classes}</div><div class="kpi-sub">Total kelas aktif</div></div>
    <div class="kpi-card"><div class="kpi-label">Peserta Didik</div><div class="kpi-value">${data.total_students}</div><div class="kpi-sub">${data.pending_corrections} permintaan koreksi</div></div>
    <div class="kpi-card"><div class="kpi-label">Rata-Rata Nilai</div><div class="kpi-value">${gs.average ?? "-"}</div><div class="kpi-sub">Median: ${gs.median_score ?? "-"} | Min: ${gs.lowest ?? "-"} | Maks: ${gs.highest ?? "-"}</div></div>
    <div class="kpi-card"><div class="kpi-label">Ketuntasan Kelas</div><div class="kpi-value">${gs.mastery_percentage != null ? gs.mastery_percentage + "%" : "-"}</div><div class="kpi-sub">${gs.mastery_count} dari ${gs.graded_count} dinilai</div></div>
    <div class="kpi-card"><div class="kpi-label">Kehadiran Kelas</div><div class="kpi-value">${att.attendance_percentage != null ? att.attendance_percentage + "%" : "-"}</div><div class="kpi-sub">H:${att.hadir} S:${att.sakit} I:${att.izin} A:${att.alpa}</div></div>
  `;

  const isLightThemeDash = document.documentElement.getAttribute("data-theme") === "light";
  renderBarChart(
    "chart-t-components",
    data.component_averages
      .filter((c) => c.average !== null)
      .map((c) => ({ label: c.category || c.title, value: c.average })),
    isLightThemeDash ? "#1d4ed8" : "#38bdf8",
    { fullWidth: true }
  );
  const dist = (gs && gs.distribution) || {};
  const isLightTheme = document.documentElement.getAttribute("data-theme") === "light";
  const distBuckets = [
    { key: "90-100", color: isLightTheme ? "#047857" : "#34d399" },
    { key: "80-89", color: isLightTheme ? "#0369a1" : "#38bdf8" },
    { key: "70-79", color: isLightTheme ? "#4f46e5" : "#818cf8" },
    { key: "60-69", color: isLightTheme ? "#b45309" : "#fbbf24" },
    { key: "<60", color: isLightTheme ? "#dc2626" : "#f87171" },
  ];
  renderDoughnutChart("chart-t-distribution", {
    centerValue: gs && gs.average != null ? String(gs.average) : "-",
    centerLabel: "Rata-Rata",
    centerBadge: gs && gs.graded_count ? `${gs.graded_count} Siswa` : "",
    segments: distBuckets.map((b) => {
      const cnt = Number(dist[b.key] || 0);
      return {
        label: b.key,
        value: cnt,
        displayValue: `${cnt} siswa`,
        color: b.color,
      };
    }),
    emptyMessage: "Belum ada data distribusi nilai",
  });
  const a = att || {};
  renderDoughnutChart("chart-t-attendance", {
    centerValue: a.attendance_percentage != null ? `${a.attendance_percentage}%` : "-",
    centerLabel: "Kehadiran",
    centerBadge: a.total_recorded ? `${a.total_recorded} Catatan` : "",
    segments: [
      { label: "Hadir", value: a.hadir || 0, displayValue: `${a.hadir || 0}x`, color: "#34d399" },
      { label: "Sakit", value: a.sakit || 0, displayValue: `${a.sakit || 0}x`, color: "#fbbf24" },
      { label: "Izin", value: a.izin || 0, displayValue: `${a.izin || 0}x`, color: "#38bdf8" },
      { label: "Alpa", value: a.alpa || 0, displayValue: `${a.alpa || 0}x`, color: "#f87171" },
    ],
    emptyMessage: "Belum ada data kehadiran",
  });

  state.attentionStudents = data.attention_students || [];
  if (data.early_warning) {
    renderEarlyWarningSystem(data.early_warning, state.attentionStudents);
  }

  const hintEl = document.getElementById("t-compare-hint");
  const leftMatSel = document.getElementById("compare-mat-left");
  const rightMatSel = document.getElementById("compare-mat-right");
  const stuSel = document.getElementById("select-compare-students");
  const btnSelAll = document.getElementById("btn-compare-select-all");
  const btnClrAll = document.getElementById("btn-compare-clear-all");
  const btnRunCmp = document.getElementById("btn-run-compare");

  if (state.selectedClassId) {
    const [stuRes, matRes] = await Promise.all([
      api(`/api/teacher/students?class_id=${state.selectedClassId}`),
      api(`/api/teacher/classes/${state.selectedClassId}/materials`).catch(() => ({ materials: [] })),
    ]);
    state.compareMaterials = matRes.materials || [];
    const matOpts =
      `<option value="">Semua Materi</option>` +
      state.compareMaterials.map((m) => `<option value="${m.id}">${escapeHtml(m.title)}</option>`).join("");
    if (leftMatSel) {
      const prevL = leftMatSel.value;
      leftMatSel.innerHTML = matOpts;
      leftMatSel.disabled = false;
      if (prevL && state.compareMaterials.some((m) => String(m.id) === prevL)) {
        leftMatSel.value = prevL;
      } else if (state.compareMaterials.length >= 2) {
        leftMatSel.value = String(state.compareMaterials[0].id);
      } else {
        leftMatSel.value = "";
      }
    }
    if (rightMatSel) {
      const prevR = rightMatSel.value;
      rightMatSel.innerHTML = matOpts;
      rightMatSel.disabled = false;
      if (prevR && state.compareMaterials.some((m) => String(m.id) === prevR)) {
        rightMatSel.value = prevR;
      } else if (state.compareMaterials.length >= 2) {
        rightMatSel.value = String(state.compareMaterials[1].id);
      } else {
        rightMatSel.value = "";
      }
    }
    if (hintEl) hintEl.classList.add("hidden");

    const hasStudents = stuRes.students.length > 0;
    if (btnSelAll) btnSelAll.disabled = !hasStudents;
    if (btnClrAll) btnClrAll.disabled = !hasStudents;
    if (btnRunCmp) btnRunCmp.disabled = !hasStudents;

    if (stuSel) {
      stuSel.innerHTML = stuRes.students
        .map((s, idx) => `<option value="${s.id}" ${idx < 3 ? "selected" : ""}>${escapeHtml(s.full_name)}</option>`)
        .join("");
    }
    if (hasStudents) {
      await runStudentComparison(stuRes.students.slice(0, 3).map((s) => s.id));
    } else {
      syncComparePanelTitles();
      renderLineChart("chart-t-compare", []);
      renderLineChart("chart-t-compare-right", []);
    }
  } else {
    state.compareMaterials = [];
    if (leftMatSel) {
      leftMatSel.innerHTML = `<option value="">Semua Materi</option>`;
      leftMatSel.disabled = true;
    }
    if (rightMatSel) {
      rightMatSel.innerHTML = `<option value="">Semua Materi</option>`;
      rightMatSel.disabled = true;
    }
    if (stuSel) stuSel.innerHTML = "";
    if (btnSelAll) btnSelAll.disabled = true;
    if (btnClrAll) btnClrAll.disabled = true;
    if (btnRunCmp) btnRunCmp.disabled = true;
    if (hintEl) {
      hintEl.textContent = "Pilih salah satu kelas pada filter atas untuk membandingkan tren nilai peserta didik antarmateri.";
      hintEl.classList.remove("hidden");
    }
    syncComparePanelTitles();
    renderLineChart("chart-t-compare", []);
    renderLineChart("chart-t-compare-right", []);
  }
}

function syncComparePanelTitles() {
  const leftSel = document.getElementById("compare-mat-left");
  const rightSel = document.getElementById("compare-mat-right");
  const leftTitle = document.getElementById("t-compare-left-title");
  const rightTitle = document.getElementById("t-compare-right-title");
  if (leftTitle && leftSel) {
    leftTitle.textContent = leftSel.options[leftSel.selectedIndex]?.text || "Semua Materi";
  }
  if (rightTitle && rightSel) {
    rightTitle.textContent = rightSel.options[rightSel.selectedIndex]?.text || "Semua Materi";
  }
}

async function runStudentComparison(ids) {
  syncComparePanelTitles();
  if (!state.selectedClassId || !ids.length) {
    renderLineChart("chart-t-compare", []);
    renderLineChart("chart-t-compare-right", []);
    return;
  }
  const leftSel = document.getElementById("compare-mat-left");
  const rightSel = document.getElementById("compare-mat-right");
  const leftMat = leftSel ? leftSel.value : "";
  const rightMat = rightSel ? rightSel.value : "";

  const buildUrl = (matVal) => {
    const qs = new URLSearchParams({ student_ids: ids.join(",") });
    if (matVal) qs.set("material_id", matVal);
    return `/api/teacher/classes/${state.selectedClassId}/compare?${qs.toString()}`;
  };

  const [leftData, rightData] = await Promise.all([
    api(buildUrl(leftMat)),
    leftMat === rightMat ? Promise.resolve(null) : api(buildUrl(rightMat)),
  ]);
  const rData = rightData || leftData;

  renderLineChart(
    "chart-t-compare",
    (leftData.series || []).map((s) => ({
      name: s.full_name,
      points: s.points.map((p) => ({ label: p.title, value: p.score })),
    }))
  );
  renderLineChart(
    "chart-t-compare-right",
    (rData.series || []).map((s) => ({
      name: s.full_name,
      points: s.points.map((p) => ({ label: p.title, value: p.score })),
    }))
  );
}

async function loadStudentsTab() {
  const qs = new URLSearchParams();
  if (state.selectedClassId) qs.set("class_id", state.selectedClassId);
  const search = document.getElementById("s-search").value.trim();
  const status = document.getElementById("s-filter-status").value;
  if (search) qs.set("search", search);
  if (status) qs.set("status", status);

  const res = await api(`/api/teacher/students?${qs.toString()}`);
  const tbody = document.getElementById("t-students-tbody");
  if (tbody) tbody.innerHTML = res.students.length
    ? res.students
        .map((s) => {
          const badge =
            s.account_status === "active"
              ? "badge-green"
              : s.account_status === "pending_activation"
              ? "badge-amber"
              : "badge-red";
          const nextStatus = s.account_status === "deactivated" ? "active" : "deactivated";
          return `<tr>
            <td><input type="checkbox" class="chk-student-row" value="${s.id}" aria-label="Pilih ${escapeHtml(s.full_name)}" /></td>
            <td>${escapeHtml(s.student_code)}</td>
            <td><strong>${escapeHtml(s.full_name)}</strong></td>
            <td><code>${escapeHtml(s.username)}</code></td>
            <td><span class="badge ${badge}">${escapeHtml(s.account_status)}</span></td>
            <td><div class="row gap-sm">
              <button class="btn btn-secondary btn-sm" onclick="editStudent(${s.id}, '${escapeHtml(s.full_name)}', '${escapeHtml(s.student_code)}', '${escapeHtml(s.username)}')">Edit</button>
              <button class="btn btn-secondary btn-sm" onclick="moveStudent(${s.id})">Pindah Kelas</button>
              <button class="btn btn-secondary btn-sm" onclick="toggleStudentStatus(${s.id}, '${nextStatus}')">${nextStatus === "active" ? "Aktifkan" : "Nonaktifkan"}</button>
              <button class="btn btn-secondary btn-sm" onclick="resetStudentCredentials(${s.id}, '${escapeHtml(s.full_name)}', '${escapeHtml(s.student_code)}')">Reset ke NIS</button>
              <button class="btn btn-secondary btn-sm" onclick="resetStudentPw(${s.id})">Reset Sandi</button>
              <button class="btn btn-danger btn-sm" onclick="deleteStudent(${s.id}, '${escapeHtml(s.full_name)}', '${s.account_status}')">Hapus</button>
              <button class="btn btn-secondary btn-sm" onclick="downloadTeacherIndividual(${s.id})">PDF</button>
            </div></td>
          </tr>`;
        })
        .join("")
    : `<tr><td colspan="6" class="muted">Belum ada peserta didik pada filter ini.</td></tr>`;
}

window.editStudent = async (id, curName, curCode, curUsername) => {
  const fullName = prompt("Nama lengkap peserta didik:", curName);
  if (fullName === null) return;
  const studentCode = prompt("Nomor Induk / NIS:", curCode);
  if (studentCode === null) return;
  const username = prompt("Username login (min. 3 karakter tanpa spasi):", curUsername);
  if (username === null) return;
  try {
    await api(`/api/teacher/students/${id}`, {
      method: "PATCH",
      body: { full_name: fullName, student_code: studentCode, username },
    });
    toast("Data dan username peserta didik diperbarui.");
    await loadStudentsTab();
  } catch (err) {
    toast(err.message, true);
  }
};

window.moveStudent = async (id) => {
  if (state.classes.length < 2) {
    return toast("Buat minimal 2 kelas terlebih dahulu untuk memindahkan peserta didik.", true);
  }
  const choices = state.classes.map((c) => `${c.id}: ${c.name}`).join("\n");
  const picked = prompt(`Masukkan ID kelas tujuan:
${choices}`);
  if (!picked) return;
  try {
    await api(`/api/teacher/students/${id}/move`, {
      method: "POST",
      body: { target_class_id: Number(picked.trim()) },
    });
    toast("Peserta didik dipindahkan (riwayat kelas lama tetap tersimpan).");
    await loadStudentsTab();
  } catch (err) {
    toast(err.message, true);
  }
};

window.toggleStudentStatus = async (id, status) => {
  try {
    await api(`/api/teacher/students/${id}`, { method: "PATCH", body: { account_status: status } });
    toast("Status akun peserta didik diperbarui.");
    await loadStudentsTab();
  } catch (err) {
    toast(err.message, true);
  }
};

window.deleteStudent = async (id, name, currentStatus) => {
  const msg =
    currentStatus === "deactivated"
      ? `Hapus permanen akun dan seluruh data peserta didik "${name}"?`
      : `Akun "${name}" masih aktif. Nonaktifkan terlebih dahulu lalu hapus permanen beserta datanya?`;
  if (!confirm(msg)) return;
  try {
    if (currentStatus !== "deactivated") {
      await api(`/api/teacher/students/${id}`, {
        method: "PATCH",
        body: { account_status: "deactivated" },
      });
    }
    await api(`/api/teacher/students/${id}?confirm_permanent=true`, { method: "DELETE" });
    toast(`Akun peserta didik "${name}" berhasil dihapus.`);
    await loadStudentsTab();
    await loadTeacherDashboard();
  } catch (err) {
    toast(err.message, true);
  }
};

window.resetStudentPw = async (id) => {
  try {
    const res = await api(`/api/teacher/students/${id}/reset-password`, { method: "POST", body: {} });
    const banner = document.getElementById("student-cred-banner");
    banner.classList.remove("hidden");
    if (banner) banner.innerHTML = `Kata sandi sementara untuk <strong>${escapeHtml(res.username)}</strong>: <code>${escapeHtml(res.temporary_password)}</code> (wajib diganti saat login).`;
    toast("Kata sandi sementara berhasil dibuat.");
  } catch (err) {
    toast(err.message, true);
  }
};


window.downloadTeacherIndividual = (studentId) => {
  downloadAuthenticatedFile(`/api/reports/individual?student_id=${studentId}&fmt=pdf`, `laporan_siswa_${studentId}.pdf`);
};

async function loadGradesTab() {
  if (!state.selectedClassId) {
    setHtml("gradebook-container", `<p class="muted">Pilih kelas terlebih dahulu di pojok kanan atas.</p>`);
    return;
  }
  const matFilterEl = document.getElementById("filter-grade-material");
  const activeMatFilter = matFilterEl && matFilterEl.value !== "" ? Number(matFilterEl.value) : null;
  const gbQs = activeMatFilter !== null ? `?material_id=${activeMatFilter}` : "";
  const gb = await api(`/api/teacher/classes/${state.selectedClassId}/gradebook${gbQs}`);
  state.materials = gb.materials || [];
  const matOpts = state.materials
    .filter((m) => !m.is_archived)
    .map((m) => `<option value="${m.id}">${escapeHtml(m.title)}</option>`)
    .join("");
  const asmtMatSel = document.getElementById("a-material-id");
  if (asmtMatSel) {
    const prevVal = asmtMatSel.value;
    asmtMatSel.innerHTML = `<option value="">Tanpa Materi (Umum)</option>` + matOpts;
    if (prevVal) asmtMatSel.value = prevVal;
  }
  if (matFilterEl) {
    const hasUngrouped = (gb.material_summary || []).some((m) => (m.id ?? m.material_id) === 0);
    matFilterEl.innerHTML =
      `<option value="">Semua Materi (${gb.all_assessments_count ?? gb.assessments.length})</option>` +
      state.materials
        .map((m) => `<option value="${m.id}" ${activeMatFilter === m.id ? "selected" : ""}>${escapeHtml(m.title)}${m.is_archived ? " (Arsip)" : ""}</option>`)
        .join("") +
      (hasUngrouped ? `<option value="0" ${activeMatFilter === 0 ? "selected" : ""}>Belum Dikelompokkan</option>` : "");
  }
  const matListEl = document.getElementById("materials-list");
  if (matListEl) {
    const mSum = gb.material_summary || [];
    matListEl.innerHTML = mSum.length
      ? mSum
          .map((m) => {
            const mid = m.id ?? m.material_id;
            const isArch = Boolean(m.is_archived ?? (m.status === "archived"));
            const isUngrouped = mid === 0;
            return `<div class="info-banner row" style="justify-content:space-between;">
              <div>
                <strong>${isUngrouped ? "" : `${m.sort_order}. `}${escapeHtml(m.title)}</strong>
                ${isArch ? `<span class="badge badge-amber">Arsip</span>` : ""}
                <div class="small muted">${m.assessment_count} penilaian • Rata-rata: ${m.class_average ?? "-"}</div>
              </div>
              <div class="row gap-sm">
                <button class="btn btn-secondary btn-pill btn-sm" type="button" onclick="selectGradeMaterial(${mid})">Lihat</button>
                ${isUngrouped ? "" : `
                  <button class="btn btn-secondary btn-pill btn-sm" type="button" onclick="editMaterial(${mid})">Ubah</button>
                  <button class="btn btn-secondary btn-pill btn-sm" type="button" onclick="toggleArchiveMaterial(${mid}, ${!isArch})">${isArch ? "Aktifkan" : "Arsip"}</button>
                  <button class="btn btn-danger btn-pill btn-sm" type="button" onclick="deleteMaterial(${mid})">Hapus</button>
                `}
              </div>
            </div>`;
          })
          .join("")
      : `<p class="muted small">Belum ada materi pembelajaran. Tambahkan bab/materi di atas untuk mengelompokkan penilaian.</p>`;
  }
  state.gradebook = gb;
  const sel = document.getElementById("select-grade-assessment");
  if (sel) sel.innerHTML = gb.assessments.length
    ? gb.assessments
        .map((a) => `<option value="${a.id}">${a.is_graded === false ? "[Checklist] " : ""}${escapeHtml(a.title)} (${a.status === "published" ? "Publik" : "Draft"})</option>`)
        .join("")
    : `<option value="">Belum ada penilaian</option>`;

  if (gb.assessments.length && !gb.assessments.some((a) => a.id === state.selectedAssessmentId)) {
    state.selectedAssessmentId = gb.assessments[0].id;
  }
  if (state.selectedAssessmentId) sel.value = String(state.selectedAssessmentId);

  const activeAsmt = gb.assessments.find((a) => a.id === Number(sel.value));
  const isChecklist = activeAsmt && activeAsmt.is_graded === false;
  const box = document.getElementById("gradebook-container");
  if (!activeAsmt) {
    if (box) box.innerHTML = `<p class="muted">Buat komponen penilaian terlebih dahulu.</p>`;
  } else if (isChecklist) {
    if (box) box.innerHTML = `
      <table class="data-table">
        <thead>
          <tr><th>NIS</th><th>Nama Peserta Didik</th><th>Status Pengumpulan (${escapeHtml(activeAsmt.title)})</th><th>Catatan Guru</th><th>Nilai Akhir Kelas</th></tr>
        </thead>
        <tbody>
          ${gb.rows
            .map((r) => {
              const cell = r.scores[activeAsmt.id] || { score: null, feedback: "" };
              const done = cell.score !== null && Number(cell.score) >= 1;
              return `<tr data-student-id="${r.student_id}">
                <td>${escapeHtml(r.student_code)}</td>
                <td><strong>${escapeHtml(r.full_name)}</strong></td>
                <td>
                  <label class="checklist-toggle">
                    <input class="checklist-input" type="checkbox" ${done ? "checked" : ""} />
                    <span class="badge ${done ? "badge-checklist-done" : "badge-checklist-pending"} checklist-status-label">${done ? "Sudah Mengumpulkan" : "Belum Mengumpulkan"}</span>
                  </label>
                </td>
                <td><input class="fb-input" type="text" value="${escapeHtml(cell.feedback)}" placeholder="Catatan opsional" /></td>
                <td><strong>${r.final_score ?? "Belum Ada"}</strong></td>
              </tr>`;
            })
            .join("")}
        </tbody>
      </table>`;
    if (box) {
      box.querySelectorAll(".checklist-input").forEach((cb) => {
        cb.addEventListener("change", () => {
          const lbl = cb.closest(".checklist-toggle")?.querySelector(".checklist-status-label");
          if (lbl) {
            lbl.textContent = cb.checked ? "Sudah Mengumpulkan" : "Belum Mengumpulkan";
            lbl.className = `badge ${cb.checked ? "badge-checklist-done" : "badge-checklist-pending"} checklist-status-label`;
          }
        });
      });
    }
  } else {
    if (box) box.innerHTML = `
      <table class="data-table">
        <thead>
          <tr><th>NIS</th><th>Nama Peserta Didik</th><th>Nilai (${escapeHtml(activeAsmt.title)}, maks ${activeAsmt.max_score})</th><th>Umpan Balik</th><th>Nilai Akhir Kelas</th></tr>
        </thead>
        <tbody>
          ${gb.rows
            .map((r) => {
              const cell = r.scores[activeAsmt.id] || { score: null, feedback: "" };
              return `<tr data-student-id="${r.student_id}">
                <td>${escapeHtml(r.student_code)}</td>
                <td><strong>${escapeHtml(r.full_name)}</strong></td>
                <td><input class="score-input" type="number" step="0.5" min="0" max="${activeAsmt.max_score}" value="${cell.score === null ? "" : cell.score}" placeholder="Kosong" /></td>
                <td><input class="fb-input" type="text" value="${escapeHtml(cell.feedback)}" placeholder="Umpan balik opsional" /></td>
                <td><strong>${r.final_score ?? "Belum Ada"}</strong></td>
              </tr>`;
            })
            .join("")}
        </tbody>
      </table>`;
  }

  const hRes = await api(`/api/teacher/classes/${state.selectedClassId}/grade-history`);
  if (document.getElementById("t-grade-history-tbody")) document.getElementById("t-grade-history-tbody").innerHTML = hRes.history.length
    ? hRes.history
        .slice(0, 20)
        .map(
          (h) => `<tr>
            <td class="small">${escapeHtml(h.changed_at)}</td>
            <td>${escapeHtml(h.assessment_title)}</td>
            <td>${escapeHtml(h.student_name)}</td>
            <td>${h.old_score === null ? "Kosong" : h.old_score}</td>
            <td>${h.new_score === null ? "Kosong" : h.new_score}</td>
            <td>${escapeHtml(h.changed_by_name)}</td>
            <td>${escapeHtml(h.reason)}</td>
          </tr>`
        )
        .join("")
    : `<tr><td colspan="7" class="muted">Belum ada riwayat perubahan nilai.</td></tr>`;
}

function getTodayIsoDate() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function updateAttendanceLiveSummary() {
  const box = document.getElementById("att-live-summary");
  if (!box) return;
  const rows = document.querySelectorAll("#att-records-tbody tr[data-att-student]");
  if (!rows.length) {
    if (box) box.innerHTML = "";
    return;
  }
  const counts = { hadir: 0, sakit: 0, izin: 0, alpa: 0 };
  rows.forEach((tr) => {
    const st = tr.dataset.attStatus || "hadir";
    if (counts[st] !== undefined) counts[st] += 1;
  });
  if (box) box.innerHTML = `
    <span class="badge badge-green">Hadir: ${counts.hadir}</span>
    <span class="badge badge-amber">Sakit: ${counts.sakit}</span>
    <span class="badge badge-blue">Izin: ${counts.izin}</span>
    <span class="badge badge-red">Alpa: ${counts.alpa}</span>
  `;
}

window.setStudentAttStatus = (btn, status) => {
  const tr = btn.closest("tr[data-att-student]");
  if (!tr) return;
  tr.dataset.attStatus = status;
  tr.querySelectorAll(".att-pill").forEach((b) => {
    b.classList.toggle("active", b.dataset.status === status);
  });
  updateAttendanceLiveSummary();
};

async function loadAttendanceTab() {
  const attClassSel = document.getElementById("att-class-id");
  const dateInp = document.getElementById("att-date");
  const meetInp = document.getElementById("att-meeting");
  if (dateInp && !dateInp.value) dateInp.value = getTodayIsoDate();

  let targetClassId = state.selectedClassId;
  if (!targetClassId && state.classes.length > 0) {
    targetClassId = state.classes[0].id;
    state.selectedClassId = targetClassId;
    const topSel = document.getElementById("filter-class");
    if (topSel) topSel.value = String(targetClassId);
  }
  if (attClassSel && targetClassId) attClassSel.value = String(targetClassId);

  const list = document.getElementById("att-sessions-list");
  const countEl = document.getElementById("att-session-count");
  const tbody = document.getElementById("att-records-tbody");

  const btnDelAll = document.getElementById("btn-delete-all-sessions");
  if (!targetClassId) {
    if (list) list.innerHTML = `<p class="muted small">Belum ada kelas. Buat kelas terlebih dahulu di menu Kelas.</p>`;
    if (tbody) tbody.innerHTML = `<tr><td colspan="4" class="muted">Buat kelas terlebih dahulu untuk mencatat kehadiran.</td></tr>`;
    if (countEl) countEl.textContent = "0 sesi";
    if (btnDelAll) btnDelAll.disabled = true;
    return;
  }

  try {
    const res = await api(`/api/teacher/classes/${targetClassId}/attendance/sessions`);
    state.sessions = res.sessions || [];
    if (countEl) countEl.textContent = `${state.sessions.length} sesi`;
    if (btnDelAll) btnDelAll.disabled = state.sessions.length === 0;

    // Suggest next meeting number automatically so creating new session is smooth
    if (meetInp) {
      const maxMeet = state.sessions.reduce((acc, s) => Math.max(acc, Number(s.meeting_number) || 0), 0);
      meetInp.value = String(maxMeet + 1);
    }

    if (!state.sessions.some((s) => s.id === state.selectedSessionId)) {
      state.selectedSessionId = state.sessions[0]?.id || null;
    }

    if (list) list.innerHTML = state.sessions.length
      ? state.sessions
          .map(
            (s) => `<div class="att-session-card ${s.id === state.selectedSessionId ? "active" : ""}" onclick="openAttSession(${s.id})">
              <div>
                <strong>Pertemuan #${s.meeting_number}</strong> <span class="muted small">• ${escapeHtml(s.session_date)}</span>
                <div class="small muted">${escapeHtml(s.topic || "Tanpa topik")}</div>
              </div>
              <span class="badge ${s.id === state.selectedSessionId ? "badge-blue" : ""}">${s.id === state.selectedSessionId ? "Aktif" : "Buka"}</span>
            </div>`
          )
          .join("")
      : `<p class="muted small">Belum ada sesi pertemuan di kelas ini. Buat sesi baru di samping.</p>`;

    if (state.selectedSessionId) {
      await openAttSession(state.selectedSessionId);
    } else {
      if (document.getElementById("att-editor-title")) document.getElementById("att-editor-title").textContent = "Formulir Kehadiran Pertemuan";
      setHtml("att-live-summary", "");
      if (tbody) tbody.innerHTML = `<tr><td colspan="4" class="muted">Buat sesi pertemuan terlebih dahulu untuk mencatat kehadiran.</td></tr>`;
    }
    await loadAttendanceRecap();
  } catch (err) {
    toast(err.message || "Gagal memuat data kehadiran.", true);
  }
}

async function openAttSession(sessionId) {
  state.selectedSessionId = sessionId;
  try {
    const data = await api(`/api/teacher/attendance/sessions/${sessionId}`);
    state.activeSessionDetail = data.session;
    if (document.getElementById("att-editor-title")) document.getElementById("att-editor-title").textContent =
      `Kehadiran: Pertemuan #${data.session.meeting_number} (${data.session.session_date})${data.session.topic ? " — " + data.session.topic : ""}`;

    // Refresh active highlight on session list
    document.querySelectorAll("#att-sessions-list .att-session-card").forEach((card, idx) => {
      const s = state.sessions[idx];
      if (!s) return;
      const isAct = s.id === sessionId;
      card.classList.toggle("active", isAct);
      const b = card.querySelector(".badge");
      if (b) {
        b.className = `badge ${isAct ? "badge-blue" : ""}`;
        b.textContent = isAct ? "Aktif" : "Buka";
      }
    });

    const tbody = document.getElementById("att-records-tbody");
    if (!data.records.length) {
      if (tbody) tbody.innerHTML = `<tr><td colspan="4" class="muted">Belum ada peserta didik di kelas ini. Tambahkan peserta didik di menu Peserta Didik.</td></tr>`;
      updateAttendanceLiveSummary();
      return;
    }

    const statusLabels = [
      ["hadir", "Hadir"],
      ["sakit", "Sakit"],
      ["izin", "Izin"],
      ["alpa", "Alpa"],
    ];
    if (tbody) tbody.innerHTML = data.records
      .map((r) => {
        const cur = (r.status || "hadir").toLowerCase();
        return `<tr data-att-student="${r.student_id}" data-att-status="${cur}">
          <td>${escapeHtml(r.student_code)}</td>
          <td><strong>${escapeHtml(r.full_name)}</strong></td>
          <td>
            <div class="att-pill-group">
              ${statusLabels
                .map(
                  ([val, lbl]) =>
                    `<button type="button" class="att-pill ${cur === val ? "active" : ""}" data-status="${val}" onclick="setStudentAttStatus(this, '${val}')">${lbl}</button>`
                )
                .join("")}
            </div>
          </td>
          <td><input class="att-note-inp" value="${escapeHtml(r.note)}" placeholder="Catatan opsional" /></td>
        </tr>`;
      })
      .join("");
    updateAttendanceLiveSummary();
  } catch (err) {
    toast(err.message || "Gagal membuka sesi kehadiran.", true);
  }
}
window.openAttSession = openAttSession;

async function loadAttendanceRecap() {
  const targetClassId = state.selectedClassId;
  const tbody = document.getElementById("att-recap-tbody");
  if (!targetClassId || !tbody) return;
  try {
    const gran = document.getElementById("att-recap-granularity").value;
    const recap = await api(`/api/teacher/classes/${targetClassId}/attendance/recap?granularity=${gran}`);
    if (tbody) tbody.innerHTML = recap.students.length
      ? recap.students
          .map(
            (s) => `<tr>
              <td>${escapeHtml(s.student_code)}</td>
              <td><strong>${escapeHtml(s.full_name)}</strong></td>
              <td>${s.total_recorded}</td>
              <td>${s.hadir}</td><td>${s.sakit}</td><td>${s.izin}</td><td>${s.alpa}</td>
              <td>${s.attendance_percentage != null ? s.attendance_percentage + "%" : "-"} ${s.needs_attention ? `<span class="badge badge-red">Perlu Tindak Lanjut</span>` : ""}</td>
            </tr>`
          )
          .join("")
      : `<tr><td colspan="8" class="muted">Belum ada data rekap kehadiran.</td></tr>`;
  } catch (err) {
    toast(err.message || "Gagal memuat rekap kehadiran.", true);
  }
}

async function loadReportsAndAuditTab() {
  const isAdmin = String(state.user?.role || "").toLowerCase() === "admin";
  const backupInput = document.getElementById("backup-label");
  const backupBtn = document.getElementById("btn-create-backup");
  if (backupInput) backupInput.classList.toggle("hidden", !isAdmin);
  if (backupBtn) backupBtn.classList.toggle("hidden", !isAdmin);

  const [corrOutcome, bakOutcome] = await Promise.allSettled([
    api("/api/teacher/corrections"),
    isAdmin ? api("/api/teacher/backups") : Promise.resolve({ backups: [], restricted: true }),
  ]);

  const corrBody = document.getElementById("t-corrections-tbody");
  if (corrBody) {
    if (corrOutcome.status === "fulfilled") {
      const list = corrOutcome.value.corrections || [];
      corrBody.innerHTML = list.length
        ? list
            .map(
              (c) => `<tr>
                <td><strong>${escapeHtml(c.student_name)}</strong></td>
                <td>${escapeHtml(c.class_name)}</td>
                <td>${escapeHtml(c.target_type)} #${c.target_id}</td>
                <td>${escapeHtml(c.message)}</td>
                <td><span class="badge ${c.status === "resolved" ? "badge-green" : "badge-amber"}">${escapeHtml(c.status)}</span></td>
                <td>
                  ${
                    c.status === "pending"
                      ? `<button class="btn btn-primary btn-sm" onclick="resolveCorrection(${c.id}, 'resolved')">Selesaikan</button>
                         <button class="btn btn-secondary btn-sm" onclick="resolveCorrection(${c.id}, 'rejected')">Tolak</button>`
                      : escapeHtml(c.teacher_response || "-")
                  }
                </td>
                <td>
                  <button class="btn btn-danger btn-sm" onclick="deleteTeacherCorrection(${c.id})">Hapus</button>
                </td>
              </tr>`
            )
            .join("")
        : `<tr><td colspan="7" class="muted">Belum ada permintaan koreksi.</td></tr>`;
    } else {
      corrBody.innerHTML = `<tr><td colspan="7" class="muted">Gagal memuat permintaan koreksi.</td></tr>`;
      toast(corrOutcome.reason?.message || "Gagal memuat permintaan koreksi.", true);
    }
  }

  const backupBox = document.getElementById("backup-list");
  if (backupBox) {
    if (!isAdmin) {
      backupBox.innerHTML = `<p class="muted small">Fitur cadangan &amp; pemulihan basis data hanya tersedia untuk akun Admin.</p>`;
    } else if (bakOutcome.status === "fulfilled") {
      const backups = bakOutcome.value.backups || [];
      backupBox.innerHTML = backups.length
        ? backups
            .map(
              (b) => `<div class="info-banner row" style="justify-content:space-between;">
                <span class="small"><code>${escapeHtml(b.filename)}</code> (${Math.round(b.size_bytes / 1024)} KB)</span>
                <button class="btn btn-secondary btn-sm" onclick="restoreBackup('${escapeHtml(b.filename)}')">Pulihkan</button>
              </div>`
            )
            .join("")
        : `<p class="muted small">Belum ada cadangan tersimpan.</p>`;
    } else {
      backupBox.innerHTML = `<p class="muted small">Gagal memuat daftar cadangan basis data.</p>`;
    }
  }
}

window.resolveCorrection = async (id, status) => {
  const rawResponse = prompt("Catatan tanggapan guru untuk peserta didik:");
  if (rawResponse === null) return;
  const response = rawResponse.trim() || "Sudah ditinjau guru.";
  try {
    await api(`/api/teacher/corrections/${id}`, { method: "PATCH", body: { status, teacher_response: response } });
    toast("Tanggapan permintaan koreksi disimpan.");
    await Promise.all([loadReportsAndAuditTab(), loadTeacherDashboard()]);
  } catch (err) {
    toast(err.message || "Gagal menyimpan tanggapan koreksi.", true);
  }
};

window.deleteTeacherCorrection = async (id) => {
  if (!confirm("Hapus catatan permintaan koreksi ini secara permanen?")) return;
  try {
    await api(`/api/teacher/corrections/${id}`, { method: "DELETE" });
    toast("Catatan permintaan koreksi dihapus.");
    await Promise.all([loadReportsAndAuditTab(), loadTeacherDashboard()]);
  } catch (err) {
    toast(err.message || "Gagal menghapus catatan koreksi.", true);
  }
};

window.restoreBackup = async (filename) => {
  if (!confirm(`Pulihkan basis data dari ${filename}?`)) return;
  try {
    await api("/api/teacher/backups/restore", { method: "POST", body: { filename } });
    toast("Basis data berhasil dipulihkan.");
    await loadTeacherDashboard();
  } catch (err) {
    toast(err.message || "Gagal memulihkan basis data.", true);
  }
};



window.resetStudentCredentials = async (studentId, fullName, studentCode) => {
  if (!confirm(`Reset akun "${fullName}" ke username NIS (${studentCode}) dan sandi standar "12345678"? Seluruh sesi login lama siswa akan dicabut.`)) return;
  try {
    const res = await api(`/api/teacher/students/${studentId}/reset-credentials`, { method: "POST" });
    const banner = document.getElementById("student-cred-banner");
    if (banner) {
      banner.classList.remove("hidden");
      banner.innerHTML = `Akun direset: Username <code>${escapeHtml(res.username)}</code> • Sandi standar <code>${escapeHtml(res.temporary_password)}</code> (wajib ganti saat login pertama).`;
    }
    toast(res.message || "Username & sandi siswa direset ke NIS / 12345678.");
    await loadStudentsTab();
  } catch (err) {
    toast(err.message, true);
  }
};

async function loadTeacherAnnouncements() {
  const box = document.getElementById("t-announcements-list");
  if (!box) return;
  if (!state.selectedClassId) {
    box.innerHTML = `<p class="muted small">Pilih kelas terlebih dahulu untuk mengelola pengumuman kelas.</p>`;
    return;
  }
  try {
    const res = await api(`/api/teacher/classes/${state.selectedClassId}/announcements`);
    const items = res.announcements || [];
    state.announcements = items;
    box.innerHTML = items.length
      ? items
          .map(
            (a) => `<article class="announcement-card ${a.is_pinned ? "pinned" : ""}">
              <div class="announcement-head">
                <div>
                  <strong>${escapeHtml(a.title)}</strong>
                  <div class="small muted">${escapeHtml(a.category)} • ${escapeHtml((a.updated_at || a.created_at || "").slice(0, 16).replace("T", " "))}</div>
                </div>
                <div class="row gap-sm">
                  ${a.is_pinned ? `<span class="badge badge-blue">Disematkan</span>` : ""}
                  <button class="btn btn-secondary btn-pill btn-sm" type="button" onclick="editAnnouncement(${a.id})">Ubah</button>
                  <button class="btn btn-secondary btn-pill btn-sm" type="button" onclick="togglePinAnnouncement(${a.id}, ${!a.is_pinned})">${a.is_pinned ? "Lepas Pin" : "Sematkan"}</button>
                  <button class="btn btn-danger btn-pill btn-sm" type="button" onclick="deleteAnnouncement(${a.id})">Hapus</button>
                </div>
              </div>
              <div class="announcement-body">${escapeHtml(a.content)}</div>
            </article>`
          )
          .join("")
      : `<p class="muted small">Belum ada pengumuman pada kelas ini.</p>`;
  } catch (err) {
    box.innerHTML = `<p class="muted small">Gagal memuat pengumuman: ${escapeHtml(err.message)}</p>`;
  }
}

window.editAnnouncement = async (annId) => {
  const cur = (state.announcements || []).find((a) => a.id === annId);
  const title = prompt("Judul pengumuman:", cur ? cur.title : "");
  if (title === null) return;
  const content = prompt("Isi pengumuman:", cur ? cur.content : "");
  if (content === null) return;
  try {
    await api(`/api/teacher/announcements/${annId}`, {
      method: "PATCH",
      body: { title, content },
    });
    toast("Pengumuman diperbarui.");
    await loadTeacherAnnouncements();
  } catch (err) {
    toast(err.message, true);
  }
};

window.togglePinAnnouncement = async (annId, pin) => {
  try {
    await api(`/api/teacher/announcements/${annId}`, {
      method: "PATCH",
      body: { is_pinned: pin },
    });
    toast(pin ? "Pengumuman disematkan." : "Sematkan dilepas.");
    await loadTeacherAnnouncements();
  } catch (err) {
    toast(err.message, true);
  }
};

window.deleteAnnouncement = async (annId) => {
  if (!confirm("Hapus pengumuman ini secara permanen?")) return;
  try {
    await api(`/api/teacher/announcements/${annId}`, { method: "DELETE" });
    toast("Pengumuman dihapus.");
    await loadTeacherAnnouncements();
  } catch (err) {
    toast(err.message, true);
  }
};

function renderEarlyWarningSystem(ews, attentionStudents = state.attentionStudents || []) {
  const tbody = document.getElementById("ews-tbody");
  if (!tbody) return;

  // Gabungkan daftar EWS dan Peserta Didik Memerlukan Perhatian tanpa duplikasi student_id
  const mergedMap = new Map();
  for (const s of (ews?.students || [])) {
    mergedMap.set(Number(s.student_id), {
      student_id: Number(s.student_id),
      student_code: s.student_code,
      full_name: s.full_name,
      class_name: s.class_name,
      severity: s.severity || "perhatian",
      final_score: s.final_score,
      kkm: s.kkm,
      alpa_count: s.alpa_count ?? 0,
      attendance_percentage: s.attendance_percentage ?? null,
      reasons: Array.isArray(s.reasons) ? [...s.reasons] : [],
    });
  }
  for (const a of (attentionStudents || [])) {
    const sid = Number(a.student_id);
    if (mergedMap.has(sid)) {
      const cur = mergedMap.get(sid);
      if (cur.attendance_percentage == null && a.attendance_percentage != null) {
        cur.attendance_percentage = a.attendance_percentage;
      }
      for (const r of (a.reasons || [])) {
        if (!cur.reasons.includes(r)) cur.reasons.push(r);
      }
    } else {
      mergedMap.set(sid, {
        student_id: sid,
        student_code: a.student_code,
        full_name: a.full_name,
        class_name: a.class_name,
        severity: "perhatian",
        final_score: a.final_score,
        kkm: a.kkm ?? "-",
        alpa_count: a.alpa_count ?? 0,
        attendance_percentage: a.attendance_percentage ?? null,
        reasons: Array.isArray(a.reasons) ? [...a.reasons] : [],
      });
    }
  }

  const rows = Array.from(mergedMap.values()).sort((x, y) => {
    const rank = (v) => (v === "kritis" ? 0 : 1);
    return rank(x.severity) - rank(y.severity) || String(x.full_name).localeCompare(String(y.full_name));
  });

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="muted">Semua peserta didik berada dalam batas aman.</td></tr>`;
    return;
  }
  tbody.innerHTML = rows
    .map((s) => {
      const sevBadge = s.severity === "kritis" ? "badge-red" : "badge-amber";
      const sevLabel = s.severity === "kritis" ? "KRITIS" : "PERHATIAN";
      const attCell =
        s.attendance_percentage != null
          ? `${s.attendance_percentage}% (Alpa ${s.alpa_count}x)`
          : `Alpa ${s.alpa_count}x`;
      return `<tr>
        <td><span class="badge ${sevBadge}">${sevLabel}</span></td>
        <td>${escapeHtml(s.student_code)}</td>
        <td><strong>${escapeHtml(s.full_name)}</strong></td>
        <td>${escapeHtml(s.class_name)}</td>
        <td>${s.final_score ?? "-"} / ${s.kkm ?? "-"}</td>
        <td><strong>${attCell}</strong></td>
        <td class="small">${s.reasons.map((r) => escapeHtml(r)).join("; ")}</td>
        <td><button class="btn btn-secondary btn-pill btn-sm" type="button" onclick="downloadTeacherIndividual(${s.student_id})">PDF</button></td>
      </tr>`;
    })
    .join("");
}

async function loadEarlyWarningSystem() {
  const qs = new URLSearchParams();
  if (state.selectedClassId) qs.set("class_id", state.selectedClassId);
  const thr = Number(document.getElementById("ews-alpa-threshold")?.value || 3);
  if (thr >= 1) qs.set("alpa_threshold", String(thr));
  try {
    const ews = await api(`/api/teacher/early-warning?${qs.toString()}`);
    renderEarlyWarningSystem(ews);
  } catch (err) {
    toast(err.message || "Gagal memuat Early Warning System.", true);
  }
}

let _isSyncingOfflineAtt = false;

function _offlineKey(suffix) {
  const uid = state.user?.id || "anon";
  return `edutrack_offline_u${uid}_${suffix}`;
}

function getOfflineAttQueue() {
  try {
    return JSON.parse(localStorage.getItem(_offlineKey("att_queue")) || "[]");
  } catch (_) {
    return [];
  }
}

function setOfflineAttQueue(items) {
  try {
    localStorage.setItem(_offlineKey("att_queue"), JSON.stringify(items || []));
  } catch (_) {}
  updateOfflineSyncBanner();
}

function clearUserOfflineReadCache() {
  if (!state.user?.id) return;
  const prefix = `edutrack_offline_u${state.user.id}_`;
  try {
    Object.keys(localStorage).forEach((k) => {
      if (k.startsWith(prefix) && !k.endsWith("_att_queue")) {
        localStorage.removeItem(k);
      }
    });
  } catch (_) {}
}

function queueOfflineAttendance(entries) {
  const queue = getOfflineAttQueue();
  const isServerId = /^\d+$/.test(String(state.selectedSessionId || ""));
  const item = {
    client_id: "att_" + Date.now() + "_" + Math.random().toString(36).slice(2, 7),
    owner_user_id: state.user?.id || null,
    class_id: Number(state.selectedClassId || document.getElementById("att-class-id")?.value || 0),
    server_session_id: isServerId ? Number(state.selectedSessionId) : null,
    session_date: document.getElementById("att-date")?.value || new Date().toISOString().slice(0, 10),
    meeting_number: Number(document.getElementById("att-meeting")?.value || 1),
    topic: document.getElementById("att-topic")?.value || "",
    entries,
    queued_at: new Date().toISOString(),
    status: "pending",
  };
  queue.push(item);
  setOfflineAttQueue(queue);
  toast("Koneksi offline — kehadiran disimpan sementara di perangkat dan akan disinkronkan otomatis saat sinyal kembali.");
}

function updateOfflineSyncBanner() {
  const statusEl = document.getElementById("offline-sync-status");
  const btnEl = document.getElementById("btn-sync-offline-att");
  if (!statusEl) return;
  const queue = getOfflineAttQueue();
  const pending = queue.filter((q) => q.status !== "failed");
  const failed = queue.filter((q) => q.status === "failed");
  const onlineTxt = navigator.onLine ? "Online" : "Offline (Mode Lokal PWA)";
  if (!queue.length) {
    statusEl.textContent = `Status jaringan: ${onlineTxt} • Tidak ada antrean kehadiran offline.`;
    if (btnEl) btnEl.classList.add("hidden");
  } else {
    statusEl.textContent = `Status jaringan: ${onlineTxt} • ${pending.length} catatan kehadiran menunggu sinkronisasi${failed.length ? ` (${failed.length} gagal)` : ""}.`;
    if (btnEl) btnEl.classList.remove("hidden");
  }
}

async function syncOfflineAttendanceQueue() {
  if (_isSyncingOfflineAtt || !navigator.onLine || !state.user || state.user.role !== "teacher") return;
  const queue = getOfflineAttQueue();
  if (!queue.length) return;
  _isSyncingOfflineAtt = true;
  let synced = 0;
  const remaining = [];
  try {
    for (let i = 0; i < queue.length; i++) {
      const item = queue[i];
      if (item.owner_user_id && item.owner_user_id !== state.user.id) {
        remaining.push(item);
        continue;
      }
      if (item.status === "failed") {
        remaining.push(item);
        continue;
      }
      try {
        let sessionId = item.server_session_id || null;
        if (!sessionId) {
          try {
            const created = await api(`/api/teacher/classes/${item.class_id}/attendance/sessions`, {
              method: "POST",
              body: {
                session_date: item.session_date,
                meeting_number: item.meeting_number,
                topic: item.topic || "",
              },
            });
            sessionId = created.session.id;
          } catch (err) {
            if (err.status === 409) {
              const listRes = await api(
                `/api/teacher/classes/${item.class_id}/attendance/sessions?date_from=${encodeURIComponent(item.session_date)}&date_to=${encodeURIComponent(item.session_date)}`
              );
              const matched = (listRes.sessions || []).find(
                (s) => s.session_date === item.session_date && Number(s.meeting_number) === Number(item.meeting_number)
              );
              if (matched) sessionId = matched.id;
              else throw err;
            } else {
              throw err;
            }
          }
        }
        await api(`/api/teacher/attendance/sessions/${sessionId}/records`, {
          method: "POST",
          body: { entries: item.entries, reason: "Sinkronisasi kehadiran offline" },
        });
        synced += 1;
      } catch (err) {
        if (err.status === 401) {
          remaining.push(...queue.slice(i));
          toast(`Sesi berakhir — silakan login kembali untuk menyinkronkan ${remaining.length} antrean kehadiran.`, true);
          break;
        }
        if (err instanceof TypeError || !navigator.onLine || (err.status && err.status >= 500)) {
          remaining.push(...queue.slice(i));
          break;
        }
        remaining.push({ ...item, status: "failed", last_error: err.message || "Gagal sinkronisasi" });
      }
    }
    setOfflineAttQueue(remaining);
    if (synced > 0) {
      toast(`${synced} catatan kehadiran offline berhasil disinkronkan ke server.`);
      if (typeof loadAttendanceTab === "function") loadAttendanceTab().catch(() => {});
    }
  } finally {
    _isSyncingOfflineAtt = false;
    updateOfflineSyncBanner();
  }
}



export function bindTeacherListeners() {
  // Teacher Nav
  onById("teacher-nav", "click", async (e) => {
    const btn = e.target.closest(".nav-item");
    if (!btn) return;
    document.querySelectorAll("#teacher-nav .nav-item").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const tab = btn.dataset.tab;
    state.activeTeacherTab = tab;
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("hidden", p.id !== `tab-${tab}`));
    if (document.getElementById("teacher-page-title")) document.getElementById("teacher-page-title").textContent = btn.textContent;
    await refreshActiveTeacherTab();
  });

  async function refreshActiveTeacherTab() {
    const tab = state.activeTeacherTab;
    if (tab === "t-dashboard") await loadTeacherDashboard();
    if (tab === "t-classes") await refreshTeacherPeriodsAndClasses();
    if (tab === "t-students") await loadStudentsTab();
    if (tab === "t-grades") await loadGradesTab();
    if (tab === "t-attendance") await loadAttendanceTab();
    if (tab === "t-reports") await loadReportsAndAuditTab();
  }

  // Topbar Class Filter
  onById("filter-class", "change", async (e) => {
    state.selectedClassId = e.target.value ? Number(e.target.value) : null;
    const sClassSel = document.getElementById("s-class-id");
    const impClassSel = document.getElementById("import-class-id");
    state.selectedSessionId = null;
    const attClassSel = document.getElementById("att-class-id");
    if (state.selectedClassId) {
      if (sClassSel) sClassSel.value = String(state.selectedClassId);
      if (impClassSel) impClassSel.value = String(state.selectedClassId);
      if (attClassSel) attClassSel.value = String(state.selectedClassId);
    }
    await refreshActiveTeacherTab();
  });
  onById("chk-show-archived", "change", refreshTeacherPeriodsAndClasses);

  // Teacher Forms
  const triggerTeacherCompare = async () => {
    const sel = document.getElementById("select-compare-students");
    if (!sel) return;
    const ids = Array.from(sel.selectedOptions).map((o) => Number(o.value));
    await runStudentComparison(ids);
  };
  onById("btn-run-compare", "click", triggerTeacherCompare);
  onById("btn-compare-select-all", "click", async () => {
    const sel = document.getElementById("select-compare-students");
    if (!sel) return;
    Array.from(sel.options).forEach((o) => { o.selected = true; });
    await triggerTeacherCompare();
  });
  onById("btn-compare-clear-all", "click", async () => {
    const sel = document.getElementById("select-compare-students");
    if (!sel) return;
    Array.from(sel.options).forEach((o) => { o.selected = false; });
    await runStudentComparison([]);
  });
  onById("compare-mat-left", "change", triggerTeacherCompare);
  onById("compare-mat-right", "change", triggerTeacherCompare);


  onById("form-class", "submit", async (e) => {
    e.preventDefault();
    try {
      const res = await api("/api/teacher/classes", {
        method: "POST",
        body: {
          name: document.getElementById("c-name").value,
          education_level: document.getElementById("c-level").value,
          mastery_threshold: Number(document.getElementById("c-kkm").value || 75),
          calculation_mode: document.getElementById("c-mode").value,
          allow_student_report_download: document.getElementById("c-dl").checked,
          description: document.getElementById("c-desc").value,
        },
      });
      e.target.reset();
      if (res.classroom?.id) state.selectedClassId = res.classroom.id;
      toast("Kelas baru berhasil dibuat.");
      await refreshTeacherPeriodsAndClasses();
      await loadTeacherDashboard();
    } catch (err) {
      toast(err.message, true);
    }
  });

  onById("form-student", "submit", async (e) => {
    e.preventDefault();
    const targetClassId = Number(document.getElementById("s-class-id").value) || state.selectedClassId;
    if (!targetClassId) return toast("Buat atau pilih kelas terlebih dahulu.", true);
    try {
      const res = await api("/api/teacher/students", {
        method: "POST",
        body: {
          class_id: targetClassId,
          full_name: document.getElementById("s-name").value,
          student_code: document.getElementById("s-code").value,
          username: document.getElementById("s-username").value || null,
          initial_password: document.getElementById("s-password").value || null,
          notes: document.getElementById("s-notes").value,
        },
      });
      e.target.reset();
      const banner = document.getElementById("student-cred-banner");
      banner.classList.remove("hidden");
      if (banner) banner.innerHTML = `Akun peserta didik dibuat — Username: <code>${escapeHtml(res.username)}</code> | Sandi Awal: <code>${escapeHtml(res.initial_password)}</code>`;
      toast("Peserta didik & akun berhasil dibuat.");
      await loadStudentsTab();
    } catch (err) {
      toast(err.message, true);
    }
  });

  onById("btn-download-student-template", "click", () => {
    downloadAuthenticatedFile("/api/teacher/students/import-template", "template_impor_peserta_didik.xlsx");
  });

  onById("form-import-students", "submit", async (e) => {
    e.preventDefault();
    const targetClassId = Number(document.getElementById("import-class-id")?.value) || state.selectedClassId;
    if (!targetClassId) return toast("Buat atau pilih kelas terlebih dahulu.", true);
    const fileInput = document.getElementById("import-file");
    const file = fileInput?.files?.[0];
    if (!file) return toast("Pilih berkas Excel (.xlsx) terlebih dahulu.", true);
    const fd = new FormData();
    fd.append("file", file);
    try {
      const preview = await api(`/api/teacher/classes/${targetClassId}/students/import/preview`, {
        method: "POST",
        body: fd,
      });
      state.pendingStudentImport = { classId: targetClassId, file };
      const box = document.getElementById("student-import-preview");
      if (box) {
        box.classList.remove("hidden");
        const validRowsHtml = preview.valid_rows.length
          ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Baris</th><th>NIS</th><th>Nama</th><th>Username</th><th>Password</th></tr></thead><tbody>${preview.valid_rows
              .map(
                (r) => `<tr><td>${r.row_number}</td><td>${escapeHtml(r.student_code)}</td><td>${escapeHtml(r.full_name)}</td><td><code>${escapeHtml(r.username)}</code></td><td><span class="badge badge-green">${escapeHtml(r.password_status)}</span></td></tr>`
              )
              .join("")}</tbody></table></div>`
          : `<p class="muted small">Tidak ada baris valid untuk disimpan.</p>`;
        const invalidRowsHtml = preview.invalid_rows.length
          ? `<div class="mt-2"><strong style="color:var(--danger);">Baris Bermasalah (${preview.invalid_rows.length}):</strong><div class="table-wrap mt-1"><table class="data-table"><thead><tr><th>Baris</th><th>Kolom</th><th>Alasan</th></tr></thead><tbody>${preview.invalid_rows
              .map(
                (er) => `<tr><td>${er.row_number}</td><td>${escapeHtml(er.column)}</td><td>${escapeHtml(er.reason)}</td></tr>`
              )
              .join("")}</tbody></table></div></div>`
          : "";
        box.innerHTML = `
          <div class="row gap-sm" style="justify-content:space-between;">
            <strong>Pratinjau Impor Peserta Didik</strong>
            <div class="row gap-sm">
              <span class="badge badge-green">Valid: ${preview.valid_count}</span>
              <span class="badge badge-red">Bermasalah: ${preview.invalid_count}</span>
            </div>
          </div>
          ${validRowsHtml}
          ${invalidRowsHtml}
          <div class="row gap-sm mt-1">
            ${preview.valid_count > 0 ? `<button id="btn-confirm-student-import" class="btn btn-primary btn-pill btn-sm" type="button">Konfirmasi &amp; Simpan (${preview.valid_count} Akun)</button>` : ""}
            <button id="btn-cancel-student-import" class="btn btn-secondary btn-pill btn-sm" type="button">Batal</button>
          </div>`;

        onById("btn-cancel-student-import", "click", () => {
          state.pendingStudentImport = null;
          box.classList.add("hidden");
          box.innerHTML = "";
        });
        onById("btn-confirm-student-import", "click", async () => {
          if (!state.pendingStudentImport) return;
          const confirmFd = new FormData();
          confirmFd.append("file", state.pendingStudentImport.file);
          try {
            const res = await api(`/api/teacher/classes/${state.pendingStudentImport.classId}/students/import/confirm`, {
              method: "POST",
              body: confirmFd,
            });
            state.pendingStudentImport = null;
            box.classList.add("hidden");
            box.innerHTML = "";
            const resBox = document.getElementById("import-result");
            if (resBox) {
              resBox.classList.remove("hidden");
              resBox.textContent = `Impor selesai — Berhasil dibuat: ${res.imported_count} akun | Gagal/Dilewati: ${res.failed_count}.`;
            }
            if (fileInput) fileInput.value = "";
            toast(`Berhasil mengimpor ${res.imported_count} akun peserta didik.`);
            await loadStudentsTab();
          } catch (err) {
            toast(err.message, true);
          }
        });
      }
    } catch (err) {
      toast(err.message, true);
    }
  });

  onById("btn-search-students", "click", loadStudentsTab);

  const syncAssessmentTypeInputs = () => {
    const typeEl = document.getElementById("a-is-graded");
    const maxEl = document.getElementById("a-max");
    const weightEl = document.getElementById("a-weight");
    const isChecklistType = typeEl && typeEl.value === "0";
    if (maxEl) {
      maxEl.disabled = Boolean(isChecklistType);
      if (isChecklistType) maxEl.value = "1";
      else if (!maxEl.value || maxEl.value === "1") maxEl.value = "100";
    }
    if (weightEl) {
      weightEl.disabled = Boolean(isChecklistType);
      if (isChecklistType) weightEl.value = "0";
      else if (!weightEl.value || weightEl.value === "0") weightEl.value = "10";
    }
  };
  onById("a-is-graded", "change", syncAssessmentTypeInputs);

  onById("form-assessment", "submit", async (e) => {
    e.preventDefault();
    if (!state.selectedClassId) return toast("Pilih kelas terlebih dahulu.", true);
    const isGraded = (document.getElementById("a-is-graded")?.value ?? "1") === "1";
    try {
      await api(`/api/teacher/classes/${state.selectedClassId}/assessments`, {
        method: "POST",
        body: {
          title: document.getElementById("a-title").value,
          category: document.getElementById("a-category").value,
          assessment_date: document.getElementById("a-date").value,
          max_score: isGraded ? Number(document.getElementById("a-max").value) : 1,
          weight: isGraded ? Number(document.getElementById("a-weight").value) : 0,
          status: document.getElementById("a-status").value,
          description: document.getElementById("a-desc").value,
          material_id: document.getElementById("a-material-id")?.value ? Number(document.getElementById("a-material-id").value) : null,
          is_graded: isGraded,
        },
      });
      e.target.reset();
      syncAssessmentTypeInputs();
      toast(isGraded ? "Komponen penilaian ditambahkan." : "Tugas checklist pengumpulan ditambahkan.");
      await loadGradesTab();
    } catch (err) {
      toast(err.message, true);
    }
  });

  onById("select-grade-assessment", "change", (e) => {
    state.selectedAssessmentId = Number(e.target.value) || null;
    loadGradesTab();
  });

  onById("btn-toggle-publish", "click", async () => {
    if (!state.gradebook || !state.selectedAssessmentId) return toast("Pilih penilaian terlebih dahulu.", true);
    const asmt = state.gradebook.assessments.find((a) => a.id === state.selectedAssessmentId);
    if (!asmt) return;
    try {
      const nextStatus = asmt.status === "published" ? "draft" : "published";
      await api(`/api/teacher/assessments/${asmt.id}`, { method: "PATCH", body: { status: nextStatus } });
      toast(nextStatus === "published" ? "Nilai dipublikasikan ke peserta didik." : "Penilaian dikembalikan ke draft.");
      await loadGradesTab();
    } catch (err) {
      toast(err.message, true);
    }
  });

  onById("btn-edit-assessment", "click", async () => {
    if (!state.gradebook || !state.selectedAssessmentId) return toast("Pilih penilaian yang ingin diubah.", true);
    const asmt = state.gradebook.assessments.find((a) => a.id === state.selectedAssessmentId);
    if (!asmt) return;
    const title = prompt("Ubah Nama Penilaian / Tugas:", asmt.title);
    if (title === null || !title.trim()) return;
    let body = { title: title.trim() };
    if (asmt.is_graded !== false) {
      const maxScore = prompt("Ubah Skor Maksimal:", String(asmt.max_score));
      if (maxScore === null) return;
      const weight = prompt("Ubah Bobot Penilaian:", String(asmt.weight));
      if (weight === null) return;
      body = { title: title.trim(), max_score: Number(maxScore), weight: Number(weight) };
    }
    try {
      await api(`/api/teacher/assessments/${asmt.id}`, {
        method: "PATCH",
        body,
      });
      toast("Komponen berhasil diperbarui.");
      await loadGradesTab();
    } catch (err) {
      toast(err.message, true);
    }
  });

  onById("btn-reset-grades", "click", async () => {
    if (!state.gradebook || !state.selectedAssessmentId) return toast("Pilih penilaian terlebih dahulu.", true);
    if (!confirm("Hapus permanen seluruh nilai siswa pada penilaian ini beserta riwayatnya?")) return;
    try {
      await api(`/api/teacher/assessments/${state.selectedAssessmentId}/grades`, {
        method: "DELETE",
      });
      toast("Seluruh nilai penilaian telah dihapus permanen.");
      await loadGradesTab();
    } catch (err) {
      toast(err.message, true);
    }
  });

  onById("btn-delete-assessment", "click", async () => {
    if (!state.gradebook || !state.selectedAssessmentId) return toast("Pilih penilaian yang ingin dihapus.", true);
    const asmt = state.gradebook.assessments.find((a) => a.id === state.selectedAssessmentId);
    if (!confirm(`Hapus penilaian "${asmt ? asmt.title : state.selectedAssessmentId}" beserta seluruh nilainya?`)) return;
    try {
      await api(`/api/teacher/assessments/${state.selectedAssessmentId}`, { method: "DELETE" });
      state.selectedAssessmentId = null;
      toast("Penilaian berhasil dihapus.");
      await loadGradesTab();
    } catch (err) {
      toast(err.message, true);
    }
  });

  onById("btn-save-grades", "click", async () => {
    if (!state.selectedAssessmentId) return toast("Pilih penilaian terlebih dahulu.", true);
    const activeAsmt = state.gradebook?.assessments?.find((a) => a.id === state.selectedAssessmentId);
    const isChecklist = activeAsmt && activeAsmt.is_graded === false;
    const rows = document.querySelectorAll("#gradebook-container tbody tr[data-student-id]");
    const entries = Array.from(rows).map((tr) => {
      if (isChecklist) {
        const cb = tr.querySelector(".checklist-input");
        return {
          student_id: Number(tr.dataset.studentId),
          score: cb && cb.checked ? 1 : null,
          feedback: tr.querySelector(".fb-input")?.value || "",
        };
      }
      const rawVal = tr.querySelector(".score-input").value.trim();
      return {
        student_id: Number(tr.dataset.studentId),
        score: rawVal === "" ? null : Number(rawVal),
        feedback: tr.querySelector(".fb-input").value,
      };
    });
    try {
      await api(`/api/teacher/assessments/${state.selectedAssessmentId}/grades`, {
        method: "POST",
        body: { entries, reason: isChecklist ? "Input checklist pengumpulan" : "Input nilai kelas" },
      });
      toast(isChecklist ? "Status pengumpulan tugas tersimpan." : "Nilai kelas tersimpan.");
      await loadGradesTab();
    } catch (err) {
      toast(err.message, true);
    }
  });

  const attClassEl = document.getElementById("att-class-id");
  if (attClassEl) {
    attClassEl.addEventListener("change", async (e) => {
      state.selectedClassId = e.target.value ? Number(e.target.value) : null;
      state.selectedSessionId = null;
      const topSel = document.getElementById("filter-class");
      if (topSel && state.selectedClassId) topSel.value = String(state.selectedClassId);
      await loadAttendanceTab();
    });
  }

  onById("form-att-session", "submit", async (e) => {
    e.preventDefault();
    const targetClassId = Number(document.getElementById("att-class-id")?.value) || state.selectedClassId;
    if (!targetClassId) return toast("Buat atau pilih kelas terlebih dahulu.", true);
    state.selectedClassId = targetClassId;
    try {
      const res = await api(`/api/teacher/classes/${targetClassId}/attendance/sessions`, {
        method: "POST",
        body: {
          session_date: document.getElementById("att-date").value || getTodayIsoDate(),
          meeting_number: Number(document.getElementById("att-meeting").value || 1),
          topic: document.getElementById("att-topic").value,
          mark_all_present: document.getElementById("att-all-present").checked,
        },
      });
      state.selectedSessionId = res.session.id;
      document.getElementById("att-topic").value = "";
      toast("Sesi kehadiran berhasil dibuat.");
      await loadAttendanceTab();
    } catch (err) {
      toast(err.message, true);
    }
  });

  onById("btn-edit-session", "click", async () => {
    if (!state.selectedSessionId || !state.activeSessionDetail) return toast("Pilih sesi kehadiran terlebih dahulu.", true);
    const cur = state.activeSessionDetail;
    const newDate = prompt("Ubah Tanggal Sesi (YYYY-MM-DD):", cur.session_date);
    if (newDate === null || !newDate.trim()) return;
    const newMeet = prompt("Ubah Nomor Pertemuan:", String(cur.meeting_number));
    if (newMeet === null) return;
    const newTopic = prompt("Ubah Topik Pertemuan:", cur.topic || "");
    if (newTopic === null) return;
    try {
      await api(`/api/teacher/attendance/sessions/${state.selectedSessionId}`, {
        method: "PATCH",
        body: { session_date: newDate.trim(), meeting_number: Number(newMeet), topic: newTopic.trim() },
      });
      toast("Sesi kehadiran diperbarui.");
      await loadAttendanceTab();
    } catch (err) {
      toast(err.message, true);
    }
  });

  onById("btn-reset-attendance", "click", async () => {
    if (!state.selectedSessionId) return toast("Pilih sesi kehadiran terlebih dahulu.", true);
    if (!confirm("Reset seluruh catatan kehadiran pada sesi ini?")) return;
    try {
      const res = await api(`/api/teacher/attendance/sessions/${state.selectedSessionId}/reset`, { method: "POST" });
      toast(`Kehadiran sesi direset (${res.cleared} catatan dibersihkan).`);
      await openAttSession(state.selectedSessionId);
      await loadAttendanceRecap();
    } catch (err) {
      toast(err.message, true);
    }
  });

  onById("btn-delete-session", "click", async () => {
    if (!state.selectedSessionId) return toast("Pilih sesi kehadiran terlebih dahulu.", true);
    if (!confirm("Hapus sesi kehadiran ini beserta seluruh catatannya secara permanen?")) return;
    try {
      await api(`/api/teacher/attendance/sessions/${state.selectedSessionId}`, { method: "DELETE" });
      state.selectedSessionId = null;
      state.activeSessionDetail = null;
      toast("Sesi kehadiran dihapus.");
      await loadAttendanceTab();
    } catch (err) {
      toast(err.message, true);
    }
  });

  onById("btn-delete-all-sessions", "click", async () => {
    const attClassSel = document.getElementById("att-class");
    const targetClassId = Number(attClassSel?.value || state.selectedClassId || 0);
    if (!targetClassId) return toast("Pilih kelas terlebih dahulu.", true);
    const total = (state.sessions || []).length;
    if (total === 0) return toast("Belum ada sesi pertemuan untuk dihapus.", true);
    if (!confirm(`Hapus permanen seluruh ${total} sesi pertemuan beserta semua catatan kehadirannya di kelas ini?`)) return;
    const btn = document.getElementById("btn-delete-all-sessions");
    if (btn) btn.disabled = true;
    try {
      const res = await api(`/api/teacher/classes/${targetClassId}/attendance/sessions`, { method: "DELETE" });
      state.selectedSessionId = null;
      state.activeSessionDetail = null;
      state.sessions = [];
      toast(`Seluruh sesi pertemuan (${res.deleted_sessions ?? total} sesi) telah dihapus permanen.`);
      await loadAttendanceTab();
      await loadAttendanceRecap();
    } catch (err) {
      toast(err.message || "Gagal menghapus seluruh sesi pertemuan.", true);
      if (btn) btn.disabled = (state.sessions || []).length === 0;
    }
  });

  onById("btn-mark-all-present", "click", async () => {
    if (!state.selectedSessionId) return toast("Pilih sesi kehadiran terlebih dahulu.", true);
    try {
      await api(`/api/teacher/attendance/sessions/${state.selectedSessionId}/mark-all-present`, { method: "POST" });
      toast("Seluruh peserta didik ditandai hadir.");
      await openAttSession(state.selectedSessionId);
      await loadAttendanceRecap();
    } catch (err) {
      toast(err.message, true);
    }
  });

  onById("btn-save-attendance", "click", async () => {
    if (!state.selectedSessionId) return toast("Pilih sesi kehadiran terlebih dahulu.", true);
    const rows = document.querySelectorAll("#att-records-tbody tr[data-att-student]");
    if (!rows.length) return toast("Belum ada peserta didik untuk disimpan kehadirannya.", true);
    const entries = Array.from(rows).map((tr) => ({
      student_id: Number(tr.dataset.attStudent),
      status: tr.dataset.attStatus || "hadir",
      note: tr.querySelector(".att-note-inp").value,
    }));
    const isOfflineSession = String(state.selectedSessionId).startsWith("offline:");
    if (!navigator.onLine || isOfflineSession) {
      queueOfflineAttendance(entries);
      return;
    }
    try {
      await api(`/api/teacher/attendance/sessions/${state.selectedSessionId}/records`, {
        method: "POST",
        body: { entries, reason: "Simpan presensi kelas" },
      });
      toast("Catatan kehadiran berhasil disimpan.");
      await loadAttendanceRecap();
    } catch (err) {
      if (err instanceof TypeError || !navigator.onLine) {
        queueOfflineAttendance(entries);
      } else {
        toast(err.message, true);
      }
    }
  });

  onById("att-recap-granularity", "change", loadAttendanceRecap);

  document.querySelectorAll("[data-export]").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (!state.selectedClassId) return toast("Pilih kelas terlebih dahulu.", true);
      const [kind, fmt] = btn.dataset.export.split(":");
      const path =
        kind === "class-grades"
          ? `/api/reports/class/${state.selectedClassId}/grades?fmt=${fmt}`
          : `/api/reports/class/${state.selectedClassId}/attendance?fmt=${fmt}`;
      downloadAuthenticatedFile(path, `${kind}.${fmt}`);
    });
  });

  onById("btn-create-backup", "click", async () => {
    try {
      const label = document.getElementById("backup-label").value || "manual";
      await api("/api/teacher/backups", { method: "POST", body: { label } });
      toast("Cadangan basis data berhasil dibuat.");
      await loadReportsAndAuditTab();
    } catch (err) {
      toast(err.message || "Cadangan tidak tersedia pada mode database cloud.", true);
    }
  });

  onById("form-t-profile", "submit", async (e) => {
    e.preventDefault();
    try {
      const res = await api("/api/auth/profile", {
        method: "PATCH",
        body: {
          username: document.getElementById("tp-username").value,
          full_name: document.getElementById("tp-name").value,
          email: document.getElementById("tp-email").value,
        },
      });
      state.user = res.user;
      if (document.getElementById("teacher-user-label")) document.getElementById("teacher-user-label").textContent =
        `${state.user.full_name} (@${state.user.username})`;
      toast("Akun login & profil guru berhasil diperbarui.");
    } catch (err) {
      toast(err.message, true);
    }
  });

  onById("form-t-password", "submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/auth/change-password", {
        method: "POST",
        body: {
          current_password: document.getElementById("tp-old-pw").value,
          new_password: document.getElementById("tp-new-pw").value,
        },
      });
      e.target.reset();
      toast("Kata sandi diperbarui.");
    } catch (err) {
      toast(err.message, true);
    }
  });



// --- GRADE EXCEL TEMPLATE & IMPORT WITH PREVIEW + CONFLICT RESOLUTION ---
(function initGradeImportWorkflow() {
  onById("btn-download-grade-template", "click", () => {
    if (!state.selectedAssessmentId) return toast("Pilih komponen penilaian terlebih dahulu.", true);
    downloadAuthenticatedFile(
      `/api/teacher/assessments/${state.selectedAssessmentId}/import-template`,
      `template_nilai_${state.selectedAssessmentId}.xlsx`
    );
  });

  onById("form-import-grades", "submit", async (e) => {
    e.preventDefault();
    if (!state.selectedAssessmentId) return toast("Pilih komponen penilaian terlebih dahulu.", true);
    const fileInput = document.getElementById("grade-import-file");
    const file = fileInput?.files?.[0];
    if (!file) return toast("Pilih berkas Excel (.xlsx) nilai terlebih dahulu.", true);

    const fd = new FormData();
    fd.append("file", file);
    try {
      const preview = await api(`/api/teacher/assessments/${state.selectedAssessmentId}/grades/import/preview`, {
        method: "POST",
        body: fd,
      });
      state.pendingGradeImport = { assessmentId: state.selectedAssessmentId, file };
      const box = document.getElementById("grade-import-preview");
      if (!box) return;
      box.classList.remove("hidden");

      const validTable = preview.valid_rows.length
        ? `<div class="table-wrap"><table class="data-table"><thead><tr><th>Baris</th><th>Identitas</th><th>Nama</th><th>Nilai Baru</th><th>Nilai Lama</th><th>Status</th></tr></thead><tbody>${preview.valid_rows
            .map((r) => {
              const statusBadge = r.is_empty
                ? `<span class="badge">Kosong (Dilewati)</span>`
                : r.has_existing
                ? `<span class="badge badge-amber">Sudah Ada Nilai</span>`
                : `<span class="badge badge-green">Baru</span>`;
              return `<tr>
                <td>${r.row_number}</td>
                <td>${escapeHtml(r.student_code)}</td>
                <td>${escapeHtml(r.full_name)}</td>
                <td><strong>${r.is_empty ? "-" : r.score}</strong></td>
                <td>${r.existing_score === null || r.existing_score === undefined ? "-" : r.existing_score}</td>
                <td>${statusBadge}</td>
              </tr>`;
            })
            .join("")}</tbody></table></div>`
        : `<p class="muted small">Tidak ada baris nilai valid.</p>`;

      const invalidTable = preview.invalid_rows.length
        ? `<div class="mt-2"><strong style="color:var(--danger);">Data Perlu Diperbaiki (${preview.invalid_rows.length}):</strong><div class="table-wrap mt-1"><table class="data-table"><thead><tr><th>Baris</th><th>Kolom</th><th>Alasan</th></tr></thead><tbody>${preview.invalid_rows
            .map((er) => `<tr><td>${er.row_number}</td><td>${escapeHtml(er.column)}</td><td>${escapeHtml(er.reason)}</td></tr>`)
            .join("")}</tbody></table></div></div>`
        : "";

      const conflictControl =
        preview.conflict_count > 0
          ? `<div class="field mt-1">
              <label for="grade-import-conflict-mode">Tindakan untuk ${preview.conflict_count} nilai yang sudah ada:</label>
              <select id="grade-import-conflict-mode">
                <option value="skip">Lewati nilai yang sudah ada (pertahankan nilai lama)</option>
                <option value="overwrite">Perbarui / timpa nilai yang sudah ada</option>
                <option value="cancel">Batalkan seluruh impor jika ada nilai lama</option>
              </select>
            </div>`
          : `<input type="hidden" id="grade-import-conflict-mode" value="skip" />`;

      box.innerHTML = `
        <div class="row gap-sm" style="justify-content:space-between;">
          <strong>Pratinjau Nilai: ${escapeHtml(preview.assessment.title)} (${escapeHtml(preview.assessment.status === "published" ? "Publik" : "Draft")})</strong>
          <div class="row gap-sm">
            <span class="badge badge-green">Valid: ${preview.valid_count}</span>
            <span class="badge badge-amber">Konflik: ${preview.conflict_count}</span>
            <span class="badge badge-red">Error: ${preview.invalid_count}</span>
          </div>
        </div>
        ${validTable}
        ${invalidTable}
        ${conflictControl}
        <div class="row gap-sm mt-1">
          ${preview.valid_count > 0 ? `<button id="btn-confirm-grade-import" class="btn btn-primary btn-pill btn-sm" type="button">Konfirmasi Impor Nilai</button>` : ""}
          <button id="btn-cancel-grade-import" class="btn btn-secondary btn-pill btn-sm" type="button">Batal</button>
        </div>`;

      onById("btn-cancel-grade-import", "click", () => {
        state.pendingGradeImport = null;
        box.classList.add("hidden");
        box.innerHTML = "";
      });

      onById("btn-confirm-grade-import", "click", async () => {
        if (!state.pendingGradeImport) return;
        const mode = document.getElementById("grade-import-conflict-mode")?.value || "skip";
        const confirmFd = new FormData();
        confirmFd.append("file", state.pendingGradeImport.file);
        try {
          const res = await api(
            `/api/teacher/assessments/${state.pendingGradeImport.assessmentId}/grades/import/confirm?conflict_mode=${encodeURIComponent(mode)}`,
            { method: "POST", body: confirmFd }
          );
          state.pendingGradeImport = null;
          box.classList.add("hidden");
          box.innerHTML = "";
          if (fileInput) fileInput.value = "";
          const resBox = document.getElementById("grade-import-result");
          if (resBox) {
            resBox.classList.remove("hidden");
            resBox.textContent =
              res.status === "cancelled"
                ? res.message
                : `Impor nilai selesai — Dimasukkan: ${res.inserted} | Diperbarui: ${res.updated} | Dilewati: ${res.skipped} | Gagal: ${res.failed}.`;
          }
          toast(res.status === "cancelled" ? "Impor nilai dibatalkan." : "Impor nilai berhasil disimpan.");
          await loadGradesTab();
        } catch (err) {
          toast(err.message, true);
        }
      });
    } catch (err) {
      toast(err.message, true);
    }
  });
})();



// --- EGM v3: MATERIAL HANDLERS, BULK STUDENT DELETE & STUDENT MATERIAL FILTER ---
window.selectGradeMaterial = (matId) => {
  const el = document.getElementById("filter-grade-material");
  if (el) el.value = matId ? String(matId) : "";
  state.selectedAssessmentId = null;
  loadGradesTab();
};

window.editMaterial = async (matId) => {
  const mat = (state.materials || []).find((m) => m.id === matId);
  if (!mat) return;
  const title = prompt("Ubah Judul Materi:", mat.title);
  if (title === null || !title.trim()) return;
  const order = prompt("Ubah Urutan Materi:", String(mat.sort_order));
  if (order === null) return;
  const desc = prompt("Ubah Deskripsi Materi:", mat.description || "");
  if (desc === null) return;
  try {
    await api(`/api/teacher/materials/${matId}`, {
      method: "PATCH",
      body: { title: title.trim(), sort_order: Number(order), description: desc.trim() },
    });
    toast("Materi pembelajaran diperbarui.");
    await loadGradesTab();
  } catch (err) {
    toast(err.message, true);
  }
};

window.toggleArchiveMaterial = async (matId, archive) => {
  try {
    await api(`/api/teacher/materials/${matId}`, { method: "PATCH", body: { is_archived: archive } });
    toast(archive ? "Materi diarsipkan." : "Materi diaktifkan kembali.");
    await loadGradesTab();
  } catch (err) {
    toast(err.message, true);
  }
};

window.deleteMaterial = async (matId) => {
  if (!confirm("Hapus materi pembelajaran ini?")) return;
  try {
    await api(`/api/teacher/materials/${matId}`, { method: "DELETE" });
    toast("Materi pembelajaran dihapus.");
    await loadGradesTab();
  } catch (err) {
    toast(err.message, true);
  }
};

(function initEgmV3Listeners() {
  onById("form-material", "submit", async (e) => {
    e.preventDefault();
    if (!state.selectedClassId) return toast("Pilih kelas terlebih dahulu.", true);
    try {
      const orderRaw = document.getElementById("m-order")?.value;
      await api(`/api/teacher/classes/${state.selectedClassId}/materials`, {
        method: "POST",
        body: {
          title: document.getElementById("m-title").value,
          description: document.getElementById("m-desc")?.value || "",
          sort_order: orderRaw ? Number(orderRaw) : null,
        },
      });
      e.target.reset();
      toast("Materi pembelajaran ditambahkan.");
      await loadGradesTab();
    } catch (err) {
      toast(err.message, true);
    }
  });

  onById("filter-grade-material", "change", () => {
    state.selectedAssessmentId = null;
    loadGradesTab();
  });



  onById("chk-select-all-students", "change", (e) => {
    document.querySelectorAll(".chk-student-row").forEach((cb) => {
      cb.checked = e.target.checked;
    });
  });

  async function runBulkDeleteStudents(deleteAll) {
    if (!state.selectedClassId) return toast("Pilih kelas terlebih dahulu di pojok kanan atas.", true);
    const selectedIds = deleteAll
      ? []
      : Array.from(document.querySelectorAll(".chk-student-row:checked")).map((cb) => Number(cb.value));
    if (!deleteAll && !selectedIds.length) {
      return toast("Centang minimal satu peserta didik terlebih dahulu.", true);
    }
    try {
      const qs = !deleteAll ? `?student_ids=${selectedIds.join(",")}` : "";
      const prev = await api(`/api/teacher/classes/${state.selectedClassId}/students/bulk-delete-preview${qs}`);
      if (!prev.total_selected) {
        return toast("Tidak ada peserta didik pada kelas ini untuk dihapus.", true);
      }
      const scopeLabel = deleteAll ? `SELURUH (${prev.total_selected})` : `${prev.total_selected} terpilih`;
      const histNote = prev.with_academic_history
        ? `\n\nPERHATIAN: ${prev.with_academic_history} peserta didik sudah memiliki riwayat nilai/kehadiran.`
        : "";
      const proceed = confirm(
        `Apakah Anda yakin ingin menghapus ${scopeLabel} peserta didik pada kelas "${prev.class_name}"?${histNote}`
      );
      if (!proceed) return;

      let mode = "permanent";
      if (prev.with_academic_history > 0) {
        const useArchive = confirm(
          `Untuk melindungi nilai dan riwayat kehadiran, disarankan ARSIPKAN / NONAKTIFKAN akun.\n\n` +
          `Klik OK untuk ARSIPKAN / NONAKTIFKAN (Aman, riwayat tersimpan).\n` +
          `Klik Cancel untuk HAPUS PERMANEN.`
        );
        mode = useArchive ? "archive" : "permanent";
      }

      const res = await api(`/api/teacher/classes/${state.selectedClassId}/students/bulk-delete`, {
        method: "POST",
        body: { delete_all: deleteAll, student_ids: selectedIds, mode, confirm: true },
      });
      toast(res.message || `${res.affected_count} peserta didik diproses.`);
      const chkAll = document.getElementById("chk-select-all-students");
      if (chkAll) chkAll.checked = false;
      await loadStudentsTab();
      await loadTeacherDashboard();
    } catch (err) {
      toast(err.message || "Gagal memproses penghapusan massal peserta didik.", true);
    }
  }

  onById("btn-bulk-delete-all", "click", () => runBulkDeleteStudents(true));
  onById("btn-bulk-delete-selected", "click", () => runBulkDeleteStudents(false));
})();



  onById("form-announcement", "submit", async (e) => {
    e.preventDefault();
    if (!state.selectedClassId) return toast("Pilih kelas terlebih dahulu di pojok kanan atas.", true);
    try {
      await api(`/api/teacher/classes/${state.selectedClassId}/announcements`, {
        method: "POST",
        body: {
          title: document.getElementById("ann-title").value,
          category: document.getElementById("ann-category").value,
          content: document.getElementById("ann-content").value,
          is_pinned: Boolean(document.getElementById("ann-pinned")?.checked),
        },
      });
      e.target.reset();
      toast("Pengumuman kelas diterbitkan.");
      await loadTeacherAnnouncements();
    } catch (err) {
      toast(err.message, true);
    }
  });

  onById("btn-refresh-ews", "click", loadEarlyWarningSystem);
  onById("btn-refresh-t-sessions", "click", () => loadActiveSessions("t-sessions-tbody"));
  onById("btn-sync-offline-att", "click", syncOfflineAttendanceQueue);

  window.addEventListener("online", () => {
    updateOfflineSyncBanner();
    syncOfflineAttendanceQueue();
  });
  window.addEventListener("offline", updateOfflineSyncBanner);

  onById("teacher-nav", "click", (e) => {
    const btn = e.target.closest(".nav-item");
    if (!btn) return;
    if (btn.dataset.tab === "t-classes") loadTeacherAnnouncements();
    if (btn.dataset.tab === "t-account") loadActiveSessions("t-sessions-tbody");
    if (btn.dataset.tab === "t-dashboard") loadEarlyWarningSystem();
    if (btn.dataset.tab === "t-attendance") updateOfflineSyncBanner();
  });

  onById("filter-class", "change", () => {
    setTimeout(() => {
      loadTeacherAnnouncements();
      loadEarlyWarningSystem();
    }, 80);
  });
}

export { initTeacherPortal, clearUserOfflineReadCache };
