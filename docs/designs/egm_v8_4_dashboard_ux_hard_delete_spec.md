# Spesifikasi Desain Teknis v8.4 — Pembaruan Dashboard Guru & Siswa, Hard Delete, Perbandingan Materi & Pop-up Kejutan Ujian (EGM + Anti-Slop)

- **Status:** Disetujui (`resolved` pasca tinjauan Goldfish v8.4 — 20 berkas eksisting diubah + 1 berkas uji baru)
- **Baseline:** `uji-coba-v8.3-bahasa-indonesia.zip`
- **Tanggal:** 2026-11-21
- **Anti-Slop Mode:** Mode 1 (`during`) aktif sejak perancangan & implementasi, ditutup Delivery Gate + `contrast_check.py`
- **Design Read (`R-37`):** `Reading this as: teacher and student academic analytics dashboards plus an interactive exam score reveal dialog for Bahasa Indonesia classes, in a calm structured utility style matching the existing app theme, dial ENERGY 2 / RHYTHM 2 / MOTION 1.`
- **Batas Semantik Dokumen:**
  - `FeatureRange`: Bagian 1 sampai Bagian 4 (Ruang Lingkup 7 Fitur, Arsitektur Data & UI, Desain Anti-Slop, Risiko & Alternatif)
  - `DetailedRange`: Bagian 5 sampai Bagian 7 (Target Scope & File Boundary, Rencana Implementasi Zero-Decision, Rencana Pengujian & Delivery Gate)

---

## 1. Overview & Problem Statement

Tujuh kendala UX dan integritas data teridentifikasi pada versi `v8.3`:
1. **Duplikasi Peringatan Guru:** Dashboard guru menampilkan dua tabel terpisah (**Peserta Didik yang Memerlukan Perhatian** dan **Early Warning System**) yang fungsinya tumpang tindih dan memakan ruang vertikal.
2. **Daftar Sesi Pertemuan Memanjang:** `#att-sessions-list` tidak memiliki batas tinggi sehingga 30 sesi pertemuan membuat halaman memanjang jauh ke bawah.
3. **Sisa Data Pasca-Penghapusan:** Penghapusan siswa, sesi pertemuan, asesmen, dan reset nilai belum membersihkan seluruh data yatim (seperti `correction_requests` yang merujuk `target_id` tanpa FK, `grade_history`, `attendance_history`, `audit_logs` akun siswa, serta baris `grades` bernilai `NULL` saat reset nilai).
4. **Panel Grafik Siswa Tidak Seragam:** Tiga panel utama siswa (**Perkembangan Nilai Pribadi**, **Capaian per Kategori Penilaian**, **Ringkasan Kehadiran Pribadi**) tidak memiliki tinggi tetap yang dapat digulir.
5. **Perbandingan Materi Terbatas:** Guru belum bisa memfilter materi pada **Analisis Tren Individual & Perbandingan Peserta Didik**, dan baik guru maupun siswa belum bisa membandingkan tren nilai dua materi secara berdampingan kanan-kiri.
6. **Grafik Komponen Terlalu Rinci:** **Rata-Rata Antarkomponen Penilaian** menampilkan setiap asesmen satu per satu alih-alih mengelompokkan berdasarkan kategori (`Tugas`, `Kuis`, `Proyek`, `Latihan`, `Ujian`, dll.).
7. **Pengalaman Membuka Nilai Ujian/Sumatif:** Siswa langsung melihat nilai **Ujian** dan **Asesmen Sumatif** di tabel tanpa momen kejutan klik **"Lihat"**.

---

## 2. Goals & Non-Goals

### 2.1 Goals
1. **Penggabungan EWS & Perhatian Khusus (Dashboard Guru):** Menghapus kartu terpisah `#t-attention-tbody` dan menyatukannya ke kartu `#ews-card` (**Sistem Peringatan Dini & Peserta Didik Memerlukan Perhatian**) dengan deduplikasi per `student_id`.
2. **Daftar Sesi Pertemuan Scrollable (Maks 5):** Menerapkan tinggi tetap scrollable pada `#att-sessions-list` agar maksimal 5 item pertemuan terlihat sekaligus.
3. **Hard Delete Permanen Menyeluruh:** Membersihkan seluruh entitas dan tabel terkait secara atomik saat menghapus siswa (satuan/massal), sesi pertemuan, asesmen, serta saat mereset nilai/sesi sehingga pencatatan kembali bersih dari nol.
4. **Panel Siswa Scrollable (`anti-slop`):** Menerapkan tinggi tetap + gulir rapi pada 3 panel grafik siswa di `#stab-s-overview`.
5. **Perbandingan Materi Kanan-Kiri (Guru & Siswa, `anti-slop`):** Menambahkan filter materi + panel perbandingan **Materi Kiri (A) vs. Materi Kanan (B)** berdampingan pada dashboard guru dan dashboard siswa.
6. **Rata-Rata Antarkomponen per Kategori (`anti-slop`):** Mengelompokkan data `component_averages` di dashboard guru berdasarkan `category` khusus tugas bernilai (`is_graded = true`).
7. **Pop-up Kejutan Nilai Ujian & Asesmen Sumatif (`anti-slop`):** Menambahkan kolom `grades.revealed_at` (migrasi v7), endpoint `POST /api/student/grades/{assessment_id}/reveal`, dan modal kejutan dengan tombol **"Lihat"** di dashboard siswa yang setelah diklik langsung menampilkan nilai normal di tabel.

### 2.2 Non-Goals
- Tidak menghapus field `attention_students` dari respons JSON `GET /api/teacher/dashboard` demi menjaga kompatibilitas mundur pengujian eksisting.
- Tidak menerapkan pop-up kejutan pada kategori selain **`Ujian`** dan **`Asesmen Sumatif`**.
- Tidak mengubah mekanisme `is_graded` checklist maupun modal EWS tengah dari v8.3.

---

## 3. High-Level Architecture & Design

### 3.1 Penggabungan EWS & Perhatian Khusus Guru
- Di `index.html`: hapus kartu `#t-attention-tbody`, ubah judul `#ews-card` menjadi **Sistem Peringatan Dini (EWS) & Peserta Didik Memerlukan Perhatian**.
- Di `teacher.js`: fungsi `renderEarlyWarningSystem(ews, attentionStudents)` menggabungkan `ews.students` dan `attentionStudents` secara deduplikasi berdasarkan `student_id` (alasan digabung tanpa duplikat; siswa yang hanya muncul di `attentionStudents` mendapat tingkat `PERHATIAN` dan kolom Nilai/KKM serta Alpa tetap terisi).

### 3.2 Scrollable Containers (Sesi Pertemuan & 3 Panel Siswa — `anti-slop`)
- **Daftar Sesi Pertemuan (`#att-sessions-list`):** Kelas `.att-sessions-scroll` (`max-height: 370px; overflow-y: auto; padding-right: 0.35rem; scrollbar-gutter: stable;`) yang menampilkan maksimal 5 kartu sesi (`~66px` + gap `8px`).
- **3 Panel Grafik Siswa (`#chart-s-trend`, `#chart-s-category`, `#chart-s-attendance`):** Kelas `.student-panel-scroll` (`height: 290px; max-height: 290px; overflow-y: auto; overflow-x: auto; padding-right: 0.25rem; scrollbar-gutter: stable;`) sehingga ketiga panel sejajar, dapat digulir saat data padat, dan tidak menyebabkan overflow horizontal pada mobile (`R-03`).

### 3.3 Hard Delete Permanen Menyeluruh
1. **`AcademicRepository.delete_student(student_id)` & `bulk_delete_students(...)`:** Dalam satu transaksi atomik, hapus eksplisit baris pada `grade_history`, `attendance_history`, `correction_requests`, `grades`, `attendance_records`, `student_enrollments` (by `student_id`), lalu `sessions`, `password_recovery_tokens`, `audit_logs` (by `user_id`), lalu `students` dan `users`.
2. **`AttendanceRepository.delete_session(session_id)` & `reset_session_records(session_id)`:** Hapus juga `correction_requests` yatim (`WHERE target_type = 'attendance' AND (target_id = ? OR target_id IN (SELECT id FROM attendance_records WHERE session_id = ?))`) dan `attendance_history` (`WHERE session_id = ?`) sebelum menghapus `attendance_records` / `attendance_sessions`.
3. **`GradeRepository.delete_assessment(assessment_id)`:** Hapus eksplisit `correction_requests` (`WHERE target_type = 'grade' AND target_id = ?`), `grade_history`, `grades`, dan `assessments`.
4. **`GradeRepository.reset_grades_for_assessment(assessment_id)` + `GradeService.reset_assessment_grades(teacher, assessment_id)` + `DELETE /api/teacher/assessments/{assessment_id}/grades`:** Menghapus permanen seluruh baris `grade_history` dan `grades` untuk `assessment_id` terkait (bukan menyimpan baris `score = NULL`) sehingga pencatatan benar-benar dimulai dari nol. Tombol `#btn-reset-grades` di `teacher.js` memanggil endpoint `DELETE` ini.

### 3.4 Perbandingan Materi Kanan-Kiri (Guru & Siswa — `anti-slop`)
- **Backend (`analytics_service.py`, `api.py`):**
  - `compare_students_for_teacher(teacher, class_id, student_ids, material_id: Optional[int] = None)` menyaring `asmt.is_graded == True` dan (bila `material_id is not None`) menyaring `asmt.material_id == material_id` (`0` = `material_id is None`). Menyertakan `material_title` dan rata-rata per siswa pada hasil.
  - `GET /api/teacher/classes/{class_id}/compare` menerima query opsional `material_id: Optional[int] = None`.
- **Frontend Guru (`index.html`, `teacher.js`, `styles.css`):**
  - Di kartu **Analisis Tren Individual & Perbandingan Peserta Didik**, tambahkan dropdown `#compare-mat-left` (**Materi Kiri**) dan `#compare-mat-right` (**Materi Kanan**), masing-masing berisi `Semua Materi` + daftar materi kelas.
  - Layout `.compare-split-grid` menampilkan 2 panel berdampingan (`.compare-pane`) di desktop (`grid-template-columns: repeat(2, minmax(0, 1fr))`) dan menumpuk rapi (`1fr`) pada `<= 900px`: kiri `#chart-t-compare` dan kanan `#chart-t-compare-right`.
- **Frontend Siswa (`index.html`, `student.js`, `styles.css`):**
  - Di `#stab-s-overview`, tambahkan kartu **Perbandingan Tren Nilai Antar Materi** dengan dropdown `#s-compare-mat-left` dan `#s-compare-mat-right` (opsi `Semua Materi` + daftar materi kelas) yang memfilter data `all_grade_timeline` (disimpan dari respons dashboard siswa tanpa query tambahan ke Supabase) dan merender dua grafik garis berdampingan kanan-kiri (`#chart-s-compare-left` dan `#chart-s-compare-right`) beserta rata-rata masing-masing.
  - Catatan penting: saat siswa memilih filter materi utama `#s-filter-material`, backend `_build_student_analytics` tetap menyertakan `"all_grade_timeline"` (seluruh nilai bernilai terpublikasi kelas tanpa filter materi) atau frontend menyimpannya saat muatan awal (`!hasMat`) agar perbandingan materi kanan-kiri selalu punya akses ke semua materi! Menyertakan `"all_grade_timeline"` (atau memakai cache `state.studentAllGrades`) memastikan perbandingan tidak pernah kosong walau filter utama sedang aktif.

### 3.5 Rata-Rata Antarkomponen Penilaian per Kategori
- Di `analytics_service.py` (`get_teacher_dashboard`): kelompokkan skor ternormalisasi dari seluruh asesmen bernilai (`asmt.is_graded == True`) berdasarkan `asmt.category` (mis. `Tugas`, `Kuis`, `Latihan`, `Proyek`, `Praktik`, `Asesmen Formatif`, `Asesmen Sumatif`, `Ujian`).
- Setiap entri pada `component_averages` merepresentasikan satu kelompok kategori dengan field: `title` (nama kategori), `category`, `average` (rata-rata skala 100), `graded_count` (jumlah nilai masuk), dan `assessment_count` (jumlah komponen dalam kategori).

### 3.6 Pop-up Kejutan Nilai Ujian & Asesmen Sumatif (`anti-slop` + Migrasi v7)
- **Migrasi DB v7 (`grades_revealed_at_column`):**
  - SQLite: `ALTER TABLE grades ADD COLUMN revealed_at TEXT DEFAULT NULL`
  - PostgreSQL: `ALTER TABLE grades ADD COLUMN IF NOT EXISTS revealed_at TIMESTAMPTZ DEFAULT NULL`
  - Tambahkan juga `revealed_at` pada DDL `CREATE TABLE IF NOT EXISTS grades`.
- **Aturan Bisnis:**
  - Berlaku **hanya** untuk asesmen berstatus `published`, bertipe dinilai (`is_graded == True`), dengan kategori `Ujian` atau `Asesmen Sumatif` (case-insensitive), dan memiliki nilai tidak `None`.
  - Item dianggap belum dibuka (`needs_reveal = True`) bila `revealed_at IS NULL`.
  - Endpoint `POST /api/student/grades/{assessment_id}/reveal` (role `STUDENT` + CSRF): memverifikasi asesmen `published` milik kelas siswa, kategori `Ujian`/`Asesmen Sumatif`, dan nilai sudah ada; memperbarui `grades.revealed_at = utc_now_iso()`; mengembalikan `{ "assessment_id", "title", "category", "raw_score", "max_score", "normalized_score", "feedback", "revealed_at" }`.
  - Di dashboard siswa (`student.js`):
    - Selama `needs_reveal === true`, baris di `#s-grades-tbody` menyembunyikan angka skor dan menampilkan tombol **`Lihat`** (`min-height: 44px`).
    - Saat dashboard dimuat dan ada item `needs_reveal === true`, modal kejutan `#student-reveal-popup` (`role="dialog"`, `aria-modal="true"`, `aria-labelledby="reveal-modal-title"`) muncul di tengah layar (jika modal EWS juga aktif, modal kejutan otomatis muncul segera setelah siswa menutup modal EWS agar tidak bertumpuk!).
    - Di dalam modal kejutan: tampilkan nama penilaian, badge kategori (`Ujian` / `Asesmen Sumatif`), dan tombol **`Lihat`** (`#btn-reveal-score`, `>= 44×44px`). Setelah diklik, panggil API reveal, tampilkan nilai besar + skala 100 + umpan balik guru di modal, ganti tombol menjadi **`Tutup`** (atau **`Lihat Nilai Berikutnya`** bila masih ada antrean), dan langsung perbarui baris `#s-grades-tbody` agar nilainya tampil normal!
- **Standar `anti-slop` & Kontras WCAG AA:**
  - Tanpa emoji dekoratif (`R-04`), gunakan ikon SVG inline `aria-hidden="true"`; tanpa em dash (`R-02`); tombol `>= 44×44px` (`R-03`); *focus trap* + `Escape` + `:focus-visible` (`R-32`); tema gelap & terang penuh (`R-34`); `@media (prefers-reduced-motion: reduce)` (`R-39`); semua pasangan warna diverifikasi `contrast_check.py` (`R-25`).

### 3.7 Failure Modes, Security & Rollback
- **Anti-IDOR pada `/reveal`:** Siswa hanya dapat membuka nilai miliknya sendiri (`student_id = profile.id`) pada asesmen berstatus `published`; upaya membuka asesmen `draft` atau kelas lain ditolak `404`/`403`.
- **Koordinasi 2 Modal (EWS + Kejutan Ujian):** Antrean sederhana di `student.js` memastikan modal kejutan hanya terbuka setelah modal EWS ditutup sehingga tidak pernah ada 2 modal bertumpuk.
- **Rollback:** Migrasi v7 (`revealed_at`) bersifat aditif (nullable), sehingga aman terhadap database Supabase eksisting.

---

## 4. Alternatives Considered

1. **Alternatif A — Menyimpan Status "Sudah Dilihat" Hanya di `localStorage`:**
   - *Alasan Ditolak:* Tidak sinkron lintas perangkat (HP vs laptop) dan hilang bila cache browser dibersihkan. Kolom `grades.revealed_at` (migrasi v7) jauh lebih andal dan otomatis ikut terhapus saat nilai dihapus permanen.
2. **Alternatif B — Memanggil Endpoint Baru untuk Perbandingan Materi Siswa:**
   - *Alasan Ditolak:* Menambah query HTTP & beban Postgres setiap siswa mengganti dropdown materi. Memfilter langsung dari `all_grade_timeline` yang sudah dikirim sekali oleh dashboard siswa menghasilkan respons instan (0 ms) dan hemat kuota Supabase.

---

## 5. Target Scope & File Boundary (Allowlist Fase 5)

### Berkas yang Diubah (18 berkas)
1. `edutrack/repositories/database.py` (migrasi v7 `grades.revealed_at` + DDL)
2. `edutrack/repositories/academic_repo.py` (hard delete siswa satuan & massal menyeluruh)
3. `edutrack/repositories/attendance_repo.py` (hard delete sesi & reset sesi termasuk `correction_requests` yatim & `attendance_history`)
4. `edutrack/repositories/grade_repo.py` (hard delete asesmen + `reset_grades_for_assessment` + `reveal_student_grade` + kolom `revealed_at`)
5. `edutrack/services/grade_service.py` (`reset_assessment_grades` + `reveal_student_grade`)
6. `edutrack/services/analytics_service.py` (agregasi `component_averages` per kategori, `compare_students_for_teacher` dengan `material_id`, `needs_reveal` & `all_grade_timeline` di `_build_student_analytics`)
7. `edutrack/web/api.py` (`DELETE /api/teacher/assessments/{assessment_id}/grades`, `POST /api/student/grades/{assessment_id}/reveal`, query `material_id` pada `/api/teacher/classes/{class_id}/compare`)
8. `edutrack/web/static/index.html` (gabung EWS + Attention, panel perbandingan materi guru & siswa, scrollable panels)
9. `edutrack/web/static/styles.css` (`.att-sessions-scroll`, `.student-panel-scroll`, `.compare-split-grid`, modal kejutan `#student-reveal-popup` gelap & terang + `prefers-reduced-motion`)
10. `edutrack/web/static/js/teacher.js` (gabung render EWS + Attention, perbandingan materi kanan-kiri, panggil `DELETE` pada reset nilai, render kategori pada `#chart-t-components`)
11. `edutrack/web/static/js/student.js` (perbandingan materi kanan-kiri, modal kejutan nilai Ujian/Asesmen Sumatif + koordinasi dengan modal EWS, sembunyikan nilai `needs_reveal` di tabel + tombol Lihat)
12. `edutrack/web/static/sw.js` (cache-bust `edutrack-shell-v8.4` & `20261120-v8.4`)
13. `edutrack/web/static/app.js` (cache-bust `20261120-v8.4`)
14. `edutrack/web/static/js/api.js` (cache-bust `20261120-v8.4`)
15. `edutrack/web/static/js/charts.js` (cache-bust `20261120-v8.4`)
16. `edutrack/tests/egm_v7_hardening_test.py` (versi migrasi `[1, 2, 3, 4, 5, 6, 7]`)
17. `edutrack/tests/egm_v8_bugfix_test.py` (cache-bust `20261120-v8.4`)
18. `edutrack/tests/egm_v8_2_1_rebrand_test.py` (cache-bust `edutrack-shell-v8.4`)

### Berkas Baru (1 berkas)
19. `edutrack/tests/egm_v8_4_dashboard_ux_hard_delete_test.py`

*(Total 18 berkas eksisting diubah + 1 berkas uji baru)*

---

## 6. Actionable Steps (Zero-Decision Implementation Plan)

1. **Migrasi v7 (`database.py`):** Tambah `revealed_at TEXT DEFAULT NULL` (SQLite) / `revealed_at TIMESTAMPTZ DEFAULT NULL` (PostgreSQL) pada `CREATE TABLE IF NOT EXISTS grades` dan migrasi `(7, "grades_revealed_at_column", self._mig_007_grades_revealed_at)`.
2. **Hard Delete Permanen (`academic_repo.py`, `attendance_repo.py`, `grade_repo.py`, `grade_service.py`, `api.py`):**
   - `academic_repo.delete_student` & `bulk_delete_students`: hapus eksplisit semua tabel terkait (`grade_history`, `attendance_history`, `correction_requests`, `grades`, `attendance_records`, `student_enrollments`, `sessions`, `password_recovery_tokens`, `audit_logs`, `students`, `users`).
   - `attendance_repo.delete_session` & `reset_session_records`: hapus juga `correction_requests` yatim (`target_type = 'attendance'`) dan `attendance_history`.
   - `grade_repo.delete_assessment`: hapus juga `correction_requests` yatim (`target_type = 'grade'`), `grade_history`, `grades`.
   - `grade_repo.reset_grades_for_assessment` + `grade_service.reset_assessment_grades` + `DELETE /api/teacher/assessments/{assessment_id}/grades`: hapus permanen `grade_history` dan `grades` untuk `assessment_id`.
3. **Analitik Kategori, Perbandingan Materi & Reveal (`grade_repo.py`, `grade_service.py`, `analytics_service.py`, `api.py`):**
   - `grade_repo.list_grades_for_student`: sertakan `g.revealed_at`; tambah `grade_repo.reveal_student_grade(assessment_id, student_id, revealed_at)`.
   - `grade_service.reveal_student_grade(student_user, assessment_id)` + `POST /api/student/grades/{assessment_id}/reveal`.
   - `analytics_service.get_teacher_dashboard`: agregasi `component_averages` berdasarkan `asmt.category` (khusus `is_graded == True`).
   - `analytics_service.compare_students_for_teacher`: terima `material_id: Optional[int] = None`, saring `is_graded == True` dan `material_id`, kembalikan `material_id` dan `series`.
   - `analytics_service._build_student_analytics`: sertakan `revealed_at`, `is_surprise_category`, `needs_reveal` pada `grade_timeline`, dan sertakan `all_grade_timeline` (semua nilai bernilai terpublikasi kelas tanpa filter materi) untuk perbandingan materi kanan-kiri siswa.
4. **Frontend Guru (`index.html`, `teacher.js`, `styles.css`):**
   - Hapus kartu `#t-attention-tbody`, gabungkan render EWS & Attention ke `#ews-card` (`#ews-tbody`) dengan deduplikasi `student_id`.
   - Beri `.att-sessions-scroll` pada `#att-sessions-list` (maks 5 sesi terlihat).
   - Tambah `#compare-mat-left` & `#compare-mat-right` + `.compare-split-grid` (`#chart-t-compare` & `#chart-t-compare-right`) pada kartu perbandingan guru.
   - Ubah `#btn-reset-grades` memanggil `DELETE /api/teacher/assessments/${state.selectedAssessmentId}/grades`.
5. **Frontend Siswa & Modal Kejutan (`index.html`, `student.js`, `styles.css`):**
   - Beri `.student-panel-scroll` pada `#chart-s-trend`, `#chart-s-category`, `#chart-s-attendance`.
   - Tambah kartu **Perbandingan Tren Nilai Antar Materi** (`#s-compare-mat-left`, `#s-compare-mat-right`, `#chart-s-compare-left`, `#chart-s-compare-right`) di `#stab-s-overview`.
   - Tambahkan modal kejutan `#student-reveal-popup` (`showStudentScoreRevealModal`) khusus `needs_reveal === true` (kategori `Ujian` / `Asesmen Sumatif`), terkoordinasi pasca-EWS, dengan tombol **`Lihat`** (`POST /api/student/grades/{id}/reveal`), tampilan nilai terbuka, dan pembaruan instan `#s-grades-tbody`.
6. **Cache-Bust & Pengujian:** Naikkan versi ke `20261120-v8.4` / `edutrack-shell-v8.4`, perbarui 3 berkas uji eksisting, dan buat `egm_v8_4_dashboard_ux_hard_delete_test.py`.

---

## 7. Test Plan, Verification & Anti-Slop Delivery Gate

1. `node --check edutrack/web/static/sw.js && for f in edutrack/web/static/app.js edutrack/web/static/js/*.js; do node --input-type=module --check < "$f"; done`
2. `python3 /working_dir/c_a05e5d97cf160f27/skills/user/anti-slop/scripts/contrast_check.py ...` (verifikasi seluruh pasangan warna modal kejutan gelap & terang + tombol Lihat + fokus).
3. `python3 -m unittest discover -s edutrack/tests -p "*_test.py" -v`
4. `python3 -O -m unittest edutrack/tests/egm_v8_4_dashboard_ux_hard_delete_test.py -v`
5. Delivery Gate `anti-slop` lengkap (Block 1–4 PASS).
