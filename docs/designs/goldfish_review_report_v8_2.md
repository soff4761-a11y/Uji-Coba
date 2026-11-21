# Laporan Peninjauan Goldfish — EduTrack v8.2 (Koreksi Guru & Pop-up EWS Siswa)

- **Status:** resolved
- **Dokumen Target:** `docs/designs/egm_v8_2_corrections_student_ews_spec.md`
- **Tanggal:** 2026-11-20
- **Peninjau Goldfish Terisolasi:** Comprehension Goldfish, Design Critic Goldfish, Codebase Auditor Goldfish, Implementation Readiness Goldfish

---

## Ringkasan Temuan & Resolusi

| # | Persona | Severity | Affected Scope | Keputusan | Ringkasan Resolusi |
|---|---|---|---|---|---|
| 1 | Codebase Auditor, Implementation Readiness | Blocker | `styles.css:96`, `student.js` (`#student-ews-popup`) | `PROPOSE FIX` (Diterapkan) | Gunakan selektor `#student-ews-popup.ews-popup` (`z-index: 1100`, spesifisitas `(1,1,0)`) agar tidak tertimpa aturan global `body > *:not(.ambient-bg)` di `styles.css:96`. |
| 2 | Design Critic | Blocker | `student.js` (`showStudentEwsPopup`, `initStudentPortal`), `app.js` | `PROPOSE FIX` (Diterapkan) | Ekspor `dismissStudentEwsPopup()`, panggil saat logout/pindah view di `app.js`, dan tambahkan guard peran siswa setelah `await` di `initStudentPortal()`. |
| 3 | Codebase Auditor | Major | `student.js:368` (`form-s-correction`), `teacher.js` (kontrol backup) | `PROPOSE FIX` (Diterapkan) | Panggil `populateStudentCorrectionTargets()` setelah `e.target.reset()` agar dropdown target sinkron, dan sembunyikan kontrol buat backup bagi non-admin di `loadReportsAndAuditTab()`. |
| 4 | Design Critic, Codebase Auditor, Implementation Readiness | Major | `analytics_service.py` (`evaluate_student_ews`), `student.js` | `PROPOSE FIX` (Diterapkan) | Validasi rentang `0..100` & `math.isfinite()` untuk `final_score` dan `mastery_threshold`, tambahkan kunci `title` eksplisit pada output `evaluate_student_ews`, dan tetapkan allow-list kelas `severity` + fallback `durationMs` ke `3000` ms bila invalid. |
| 5 | Design Critic | Major | `teacher.js` (`loadReportsAndAuditTab`, `resolveCorrection`) | `PROPOSE FIX` (Diterapkan) | Gunakan `Promise.allSettled` untuk pemuatan paralel terisolasi (backup kondisional hanya untuk admin), tangani error tiap panel, batalkan `resolveCorrection` bila `prompt === null`, dan segarkan KPI dashboard. |
| 6 | Codebase Auditor, Implementation Readiness | Major | `egm_v8_2_corrections_ews_test.py`, `egm_v8_bugfix_test.py` | `PROPOSE FIX` (Diterapkan) | Salin ke-4 modul JS (`state.js`, `api.js`, `charts.js`, `student.js`) ke direktori temporer Node untuk uji deterministik `showStudentEwsPopup` 3000ms; perketat regex versi di `egm_v8_bugfix_test.py` agar seluruh `20261120-v*` wajib tepat `20261120-v8.2`. |
| 7 | Design Critic | Nit | `student.js` (aksesibilitas pop-up) | `PROPOSE FIX` (Diterapkan) | Tambahkan tombol tutup eksplisit `<button type="button" class="ews-popup-close" aria-label="Tutup peringatan">×</button>` pada pop-up EWS. |
