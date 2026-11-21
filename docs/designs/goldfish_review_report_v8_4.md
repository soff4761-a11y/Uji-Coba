# Laporan Peninjauan Goldfish — Pembaruan Dashboard, Hard Delete, Perbandingan Materi & Pop-up Kejutan Ujian (v8.4)

- **Status:** `resolved` (Auto accept oleh pengguna — seluruh PROPOSE FIX diterapkan pada Fase 5)
- **Dokumen Target:** `docs/designs/egm_v8_4_dashboard_ux_hard_delete_spec.md`
- **Peninjau Terisolasi:** Comprehension & Zoom Out, Design Critic & Codebase Auditor, Implementation Readiness
- **Ringkasan Temuan (Setelah Deduplikasi):** `4 Blocker` | `7 Major` | `3 Nit` | `0 Escalate`

---

## Daftar Temuan & Kategorisasi Resolusi (`egm-resolve`)

### Blocker

#### Isu #1 — Nama Tabel, Kolom, dan Metode Aktual pada Jalur Hard Delete Siswa
- **Persona Peninjau:** Codebase Auditor, Implementation Readiness
- **Severity:** `Blocker`
- **Affected Scope:** Bagian 3.3 (#1), Bagian 6 (#2) vs. `database.py` (baris 56, 217–225, 296, 469–477) & `academic_repo.py` (baris 614–681)
- **Discrepancy Description:** (1) Nama tabel aktual adalah `recovery_tokens` (bukan `password_recovery_tokens`); (2) kolom pada `audit_logs` adalah `actor_user_id` (bukan `user_id`); (3) metode hapus massal di `academic_repo.py` adalah `bulk_archive_or_delete_students` (bukan `bulk_delete_students`) dan pembersihan permanen hanya berjalan pada cabang `mode == "permanent"` sambil mempertahankan guard `OUT_OF_SCOPE` dan `MULTI_CLASS`.
- **Rationale:** Query dengan nama tabel/kolom yang salah akan gagal runtime pada SQLite maupun PostgreSQL.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Terverifikasi langsung terhadap skema `database.py` dan `academic_repo.py`.
- **Proposed Edit:** Perbaiki seluruh nama ke `recovery_tokens`, `audit_logs.actor_user_id`, dan `bulk_archive_or_delete_students` (cabang `mode == "permanent"`).

#### Isu #2 — Anti-Bocor Nilai Kejutan (`needs_reveal`) di UI Siswa & Kompatibilitas `api_security_e2e_test.py`
- **Persona Peninjau:** Comprehension / Zoom Out, Design Critic, Implementation Readiness
- **Severity:** `Blocker`
- **Affected Scope:** Bagian 3.6, Bagian 6 (#3, #5) vs. `analytics_service.py`, `student.js`, `api_security_e2e_test.py` (baris 89, 141–144)
- **Discrepancy Description:** Nilai `Ujian`/`Asesmen Sumatif` yang berstatus `needs_reveal=True` dapat bocor di grafik siswa sebelum klik **"Lihat"** jika tidak disaring di UI; sebaliknya jika dikecualikan dari `grade_summary.final_score` di backend, `api_security_e2e_test.py` akan gagal. Selain itu, kontrak `/reveal` untuk siswa pindah kelas, nilai `NULL`, idempotensi, dan `upsert_grade` belum eksplisit.
- **Rationale:** Menjaga momen kejutan tetap utuh di UI siswa tanpa mematahkan uji keamanan E2E eksisting.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Pemisahan kontrak backend (tetap menghitung `final_score` + menandai `needs_reveal: true`) dan UI siswa (menyembunyikan skor `needs_reveal` dari tabel `#s-grades-tbody`, grafik `#chart-s-trend`, dan grafik perbandingan materi hingga tombol **"Lihat"** diklik, lalu merender ulang setelah `/reveal`) menyelesaikan kedua syarat sekaligus.
- **Proposed Edit:** Tetapkan: (a) UI siswa menyembunyikan skor `needs_reveal` pada tabel, grafik tren, dan perbandingan materi hingga dibuka via `/reveal`; (b) `/reveal` memvalidasi baris `grades` milik `profile.id` + `published` + `is_graded` + kategori `SURPRISE_REVEAL_CATEGORIES` + `score IS NOT NULL`, bersifat idempoten `200 OK` tanpa menimpa timestamp awal; (c) di `upsert_grade`, jika `score` diset `None` maka `revealed_at` direset ke `NULL`, sedangkan pembaruan skor non-null mempertahankan `revealed_at` yang sudah ada.

#### Isu #3 — Cakupan & Urutan Pembersihan `correction_requests` Yatim (Anti-Tabrakan ID)
- **Persona Peninjau:** Zoom Out, Design Critic, Implementation Readiness
- **Severity:** `Blocker`
- **Affected Scope:** Bagian 3.3 (#2–#4), Bagian 6 (#2) vs. `attendance_repo.py` (baris 92–106) & `grade_repo.py`
- **Discrepancy Description:** (a) Query hapus `correction_requests` di `delete_session`/`reset_session_records` wajib dijalankan **sebelum** `DELETE FROM attendance_records` dan dibatasi ke `student_id` kelas/sesi terkait agar `target_id = session_id` tidak salah menghapus koreksi `attendance_records.id` milik kelas/guru lain; (b) `reset_grades_for_assessment` juga harus membersihkan `correction_requests` (`target_type = 'grade' AND target_id = ?`).
- **Rationale:** Mencegah penghapusan data lintas kelas dan menjamin tidak ada koreksi yatim tersisa saat reset nilai.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Terverifikasi langsung di `attendance_service.py:322-324` dan `student.js:218`.
- **Proposed Edit:** Jalankan pembersihan `correction_requests` sebelum `DELETE FROM attendance_records` dengan filter `student_id` terikat sesi/kelas, serta tambahkan pembersihan `correction_requests` di `reset_grades_for_assessment`.

#### Isu #4 — Cakupan Allowlist Berkas (`classroom_service.py` & `state.js`)
- **Persona Peninjau:** Design Critic / Codebase Auditor, Implementation Readiness
- **Severity:** `Blocker`
- **Affected Scope:** Bagian 5 (`Target Scope & File Boundary`)
- **Discrepancy Description:** `ClassroomService.reset_classroom_data` (`classroom_service.py`) belum membersihkan `grade_history`, `attendance_history`, dan `correction_requests` yatim; selain itu `state.js` dibutuhkan untuk menyimpan `state.attentionStudents` dan `state.studentAllGrades`. Keduanya belum masuk Allowlist Bagian 5.
- **Rationale:** Allowlist Fase 5 wajib mencakup seluruh berkas yang disentuh secara eksplisit.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Menambahkan `edutrack/services/classroom_service.py` dan `edutrack/web/static/js/state.js` ke Allowlist (total 20 berkas eksisting diubah + 1 berkas uji baru).
- **Proposed Edit:** Perbarui Bagian 5 dan Bagian 6 untuk menyertakan `classroom_service.py` dan `state.js`.

---

### Major

#### Isu #5 — Sinkronisasi EWS Gabungan saat Klik "Perbarui EWS" (`loadEarlyWarningSystem`)
- **Persona Peninjau:** Design Critic / Codebase Auditor, Implementation Readiness
- **Severity:** `Major`
- **Affected Scope:** Bagian 3.1 & `teacher.js` (`loadTeacherDashboard`, `loadEarlyWarningSystem`, `renderEarlyWarningSystem`)
- **Discrepancy Description:** `loadEarlyWarningSystem()` memanggil `GET /api/teacher/early-warning` yang tidak mengembalikan `attention_students`, sehingga klik **"Perbarui EWS"** akan menghilangkan siswa dari `attention_students` bila tidak disimpan di `state.attentionStudents`.
- **AI Suggestion:** `PROPOSE FIX`
- **Proposed Edit:** Simpan `state.attentionStudents = data.attention_students || []` di `loadTeacherDashboard()` dan gunakan sebagai fallback di `renderEarlyWarningSystem(ews, attentionStudents = state.attentionStudents)`.

#### Isu #6 — Pembersihan Modal Kejutan & Reset State Sesi saat Logout / Idle Expiry di `app.js`
- **Persona Peninjau:** Design Critic
- **Severity:** `Major`
- **Affected Scope:** Bagian 3.6–3.7, `app.js`, `student.js`
- **Discrepancy Description:** Logout / `expireSessionNow` di `app.js` harus menutup modal kejutan (`dismissStudentRevealPopup()`) dan mereset flag `studentEwsShownInSession` / antrean reveal agar modal tidak tertinggal di atas layar login atau memblokir akun berikutnya.
- **AI Suggestion:** `PROPOSE FIX`
- **Proposed Edit:** Ekspor `resetStudentModalSessionState()` (yang memanggil `dismissStudentEwsPopup()` + `dismissStudentRevealPopup()` + reset flag) dari `student.js` dan panggil di jalur logout/expiry `app.js`.

#### Isu #7 — Pemuatan Daftar Materi & Penanganan "Semua Kelas" pada Perbandingan Materi Guru
- **Persona Peninjau:** Design Critic / Codebase Auditor, Implementation Readiness
- **Severity:** `Major`
- **Affected Scope:** Bagian 3.4 & `teacher.js` (`loadTeacherDashboard`, `runStudentComparison`)
- **Discrepancy Description:** `loadTeacherDashboard()` belum memuat `/api/teacher/classes/{class_id}/materials` untuk mengisi `#compare-mat-left`/`#compare-mat-right`, belum menangani kondisi `selectedClassId === null` ("Semua Kelas"), dan belum menetapkan apakah `change` dropdown otomatis memicu perbandingan.
- **AI Suggestion:** `PROPOSE FIX`
- **Proposed Edit:** Muat `/api/teacher/classes/{class_id}/materials` saat `state.selectedClassId` terisi (nonaktifkan dropdown dengan pesan informatif saat "Semua Kelas"), sertakan opsi `Semua Materi`, `Tanpa Materi (0)`, dan daftar materi, serta picu perbandingan otomatis pada event `change`.

#### Isu #8 — Kompatibilitas Migrasi v7 PostgreSQL (`StrictPsycopgV3Cursor`) di `database_pg_test.py`
- **Persona Peninjau:** Codebase Auditor
- **Severity:** `Major`
- **Affected Scope:** Bagian 6 (#1) & `database.py` (`_mig_007_grades_revealed_at`)
- **Discrepancy Description:** Pada mode PostgreSQL, `_mig_007_grades_revealed_at` harus memeriksa `if not cols or "revealed_at" not in cols:` agar lolos mock `StrictPsycopgV3Cursor` pada `database_pg_test.py`.
- **AI Suggestion:** `PROPOSE FIX`
- **Proposed Edit:** Gunakan pola `if not cols or "revealed_at" not in cols:` di `_mig_007_grades_revealed_at`.

#### Isu #9 — Formula & Urutan Deterministik `component_averages` per Kategori + Kontrak `compare_students_for_teacher`
- **Persona Peninjau:** Comprehension, Design Critic, Implementation Readiness
- **Severity:** `Major`
- **Affected Scope:** Bagian 3.4–3.5 & `analytics_service.py`
- **Discrepancy Description:** Tetapkan *pooled mean* (rata-rata seluruh skor ternormalisasi pada kategori tersebut) dengan urutan kategori alfabetis/kanonik deterministik, serta kunci field `material_id`, `material_title`, dan `average` per seri di `compare_students_for_teacher` dan `all_grade_timeline` dari backend.
- **AI Suggestion:** `PROPOSE FIX`
- **Proposed Edit:** Kunci kontrak JSON dan formula *pooled mean* + urutan deterministik di Bagian 6.

#### Isu #10 — Palet Hex Eksplisit Modal Kejutan (`contrast_check.py`) & Matriks Uji v8.4
- **Persona Peninjau:** Implementation Readiness
- **Severity:** `Major`
- **Affected Scope:** Bagian 3.6 & Bagian 7
- **Discrepancy Description:** Daftar warna hex modal kejutan (gelap & terang) dan matriks kasus uji `egm_v8_4_dashboard_ux_hard_delete_test.py` perlu ditulis eksplisit tanpa placeholder `...`.
- **AI Suggestion:** `PROPOSE FIX`
- **Proposed Edit:** Tetapkan palet hex terverifikasi WCAG AA (`#0f172a`/`#f8fafc`/`#cbd5e1`/`#0369a1`/`#ffffff` gelap; `#ffffff`/`#0f172a`/`#334155`/`#0369a1`/`#ffffff` terang; badge `#fde68a`/`#78350f` gelap & `#92400e`/`#fffbeb` terang) dan matriks uji lengkap di Bagian 7.

#### Isu #11 — `FeatureRange` Anti-Weeds
- **Persona Peninjau:** Zoom Out
- **Severity:** `Major`
- **Affected Scope:** Bagian 2–3
- **Discrepancy Description:** Beberapa detail SQL/ID DOM muncul di `FeatureRange`.
- **AI Suggestion:** `DECLINE` (struktur sudah tervalidasi oleh ketiga reviewer dan siap masuk Fase 5 setelah resolusi isu teknis #1–#10).

---

### Nit

#### Isu #12 — `overflow-x: hidden; overflow-y: auto;` pada `.student-panel-scroll`
- **Persona Peninjau:** Codebase Auditor
- **Severity:** `Nit`
- **Affected Scope:** Bagian 3.2 & `styles.css`
- **Discrepancy Description:** Menghindari scrollbar horizontal tidak perlu pada 3 kartu donat siswa di mobile (`R-03`).
- **AI Suggestion:** `PROPOSE FIX`

#### Isu #13 — Konstanta Bersama `SURPRISE_REVEAL_CATEGORIES`
- **Persona Peninjau:** Design Critic
- **Severity:** `Nit`
- **Affected Scope:** `models.py` / `grade_service.py` / `analytics_service.py`
- **Discrepancy Description:** Definisikan `SURPRISE_REVEAL_CATEGORIES = frozenset({"ujian", "asesmen sumatif"})` di `edutrack/domain/models.py` agar konsisten 100%.
- **AI Suggestion:** `PROPOSE FIX`

#### Isu #14 — Urutan Hapus `correction_requests` & Respons `DELETE /grades`
- **Persona Peninjau:** Implementation Readiness
- **Severity:** `Nit`
- **Affected Scope:** Bagian 6 (#2)
- **Discrepancy Description:** Respons `DELETE /api/teacher/assessments/{id}/grades` mengembalikan `{"status": "reset", "cleared": count}` dan mencatat audit `reset_assessment_grades`.
- **AI Suggestion:** `PROPOSE FIX`
