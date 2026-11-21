# Spesifikasi Desain Teknis v8.3 — Tugas Dinilai vs. Checklist Pengumpulan & Modal EWS Tengah Anti-Slop (EGM)

- **Status:** Disetujui (`resolved` pasca tinjauan Goldfish v8.3 — 19 berkas diubah + 1 berkas uji baru)
- **Baseline:** `uji-coba-v8.2.2-bahasa-indonesia.zip`
- **Tanggal:** 2026-11-21
- **Anti-Slop Mode:** Mode 1 (`during`) aktif sejak perancangan & implementasi, ditutup Delivery Gate + `contrast_check.py`
- **Design Read (`R-37`):** `Reading this as: academic teacher/student dashboard and centered EWS alert dialog for teachers and students of Bahasa Indonesia, in a calm high-contrast utility style matching the existing app theme, dial ENERGY 2 / RHYTHM 2 / MOTION 1.`
- **Batas Semantik Dokumen:**
  - `FeatureRange`: Bagian 1 sampai Bagian 4 (Arsitektur, Model Data, EWS, Desain Anti-Slop, Risiko & Alternatif)
  - `DetailedRange`: Bagian 5 sampai Bagian 7 (Target Scope & File Boundary, Rencana Implementasi Zero-Decision, Rencana Pengujian & Delivery Gate)

---

## 1. Overview & Problem Statement

Aplikasi **Bahasa Indonesia** saat ini memperlakukan setiap komponen di tabel `assessments` sebagai penilaian bernilai angka yang masuk ke perhitungan nilai akhir, KKM, grafik tren, dan statistik kelas. Guru membutuhkan kemampuan membuat dua jenis tugas:
1. **Tugas Dinilai (Angka):** perilaku standar saat ini (skor numerik, bobot, skala 100, masuk perhitungan nilai akhir & KKM).
2. **Tugas Tidak Dinilai (Checklist Pengumpulan):** seperti pengumpulan buku catatan yang cukup dicentang (**Sudah Mengumpulkan** / **Belum Mengumpulkan**), tidak masuk perhitungan nilai akhir/KKM, ditampilkan terpisah di dashboard siswa, namun tetap memicu peringatan EWS apabila peserta didik tidak mengumpulkan beberapa kali (`>= 3` tugas checklist dipublikasikan).

Selain itu, pop-up EWS siswa (`#student-ews-popup`) saat ini berupa banner kecil (`460px`) di bagian atas layar yang otomatis menutup dalam 3 detik dan memakai emoji dekoratif `⚠️`. Pemilik proyek meminta dialog EWS diperbesar, ditampilkan di tengah layar, bertahan hingga siswa mengklik tombol **Mengerti**, dan dikoreksi desainnya sesuai standar **anti-slop**.

---

## 2. Goals & Non-Goals

### 2.1 Goals
1. **Skema & Migrasi v6 (SQLite + PostgreSQL/Supabase):** Menambahkan kolom `is_graded` pada tabel `assessments` secara aditif dan idempoten (default `TRUE`/`1` sehingga seluruh asesmen lama tetap bertipe dinilai).
2. **Input & Buku Nilai Guru:** Menambahkan pilihan jenis tugas (**Dinilai (Angka)** vs **Tidak Dinilai (Checklist Pengumpulan)**) di form komponen penilaian, menonaktifkan input skor maks & bobot saat checklist dipilih, dan mengubah kolom input Buku Nilai menjadi kotak centang (**Sudah Mengumpulkan** / **Belum Mengumpulkan**) untuk tugas checklist.
3. **Pemisahan Tampilan Dashboard Siswa:** Memisahkan tab penilaian siswa menjadi dua kartu yang jelas: **Tugas & Penilaian Bernilai** (`grade_timeline`) dan **Tugas Pengumpulan / Checklist (Tanpa Nilai)** (`checklist_tasks`).
4. **Isolasi Perhitungan Nilai & Integrasi EWS:** Mengecualikan tugas checklist 100% dari `final_score`, KKM, statistik kelas, distribusi nilai, grafik tren nilai, dan ekspor laporan nilai angka; menambahkan pemicu EWS `unsubmitted_checklist` saat jumlah tugas checklist dipublikasikan yang belum dikumpulkan `>= ews_unsubmitted_checklist_threshold` (default `3`).
5. **Modal EWS Tengah Berbasis `anti-slop`:** Mengubah `#student-ews-popup` menjadi dialog modal terpusat berukuran lebih besar (`min(580px, calc(100vw - 2rem))`) dengan *backdrop*, tombol utama **Mengerti** (`>= 44×44px`), tombol tutup `×` (`>= 44×44px`), dukungan keyboard `Escape`, fokus awal otomatis, tanpa timer auto-dismiss, tanpa emoji dekoratif (`R-04`), tanpa em dash (`R-02`) pada teks UI baru, kontras WCAG AA diverifikasi `contrast_check.py` untuk tema gelap & terang (`R-25`, `R-34`), serta `prefers-reduced-motion: reduce` (`R-39`).

### 2.2 Non-Goals
- Tidak mengubah rumus `compute_final_score` atau bobot untuk tugas bernilai.
- Tidak menambahkan tabel database baru (`checklist_submissions`); pemanfaatan kolom `is_graded` pada `assessments` + `grades.score` (`1.0` = sudah mengumpulkan, `NULL` = belum mengumpulkan) jauh lebih sederhana (YAGNI) dan otomatis mewarisi riwayat, audit, serta penghapusan berjenjang (`ON DELETE CASCADE`).
- Tidak mengubah alur autentikasi, CSRF, atau endpoint koreksi/kehadiran.

---

## 3. High-Level Architecture & Design

### 3.1 Model Data & Migrasi v6 (`database.py`, `models.py`, `app_config.py`)
- **`AppConfig`:** Tambah `ews_unsubmitted_checklist_threshold: int = 3` (env var opsional `EDUTRACK_EWS_UNSUBMITTED_THRESHOLD`, minimal 1).
- **`Assessment` dataclass:** Tambah field `is_graded: bool = True`.
- **Migrasi v6 (`assessments_is_graded_flag`):**
  - SQLite: `ALTER TABLE assessments ADD COLUMN is_graded INTEGER NOT NULL DEFAULT 1 CHECK(is_graded IN (0, 1))` (cek `PRAGMA table_info(assessments)` dulu agar idempoten).
  - PostgreSQL: `ALTER TABLE assessments ADD COLUMN IF NOT EXISTS is_graded BOOLEAN NOT NULL DEFAULT TRUE`.
  - Juga tambahkan kolom `is_graded` pada DDL `CREATE TABLE IF NOT EXISTS assessments` untuk database baru.
- **Konvensi Penyimpanan Checklist pada `grades`:**
  - Saat `is_graded = False`, asesmen disimpan dengan `max_score = 1.0` dan `weight = 0.0` (memenuhi `CHECK(max_score > 0)` dan `CHECK(weight >= 0)`).
  - Pada `grades`: `score = 1.0` berarti **Sudah Mengumpulkan**; `score IS NULL` (atau tidak ada baris di `grades`) berarti **Belum Mengumpulkan**. Jika client mengirim `score = 0` pada asesmen checklist, `GradeService.save_grades_bulk` menormalisasinya menjadi `None` agar semantik selalu biner (`1.0` vs `NULL`).

### 3.2 Isolasi Analitik & Aturan EWS (`analytics_service.py`, `report_service.py`)
- **`evaluate_student_ews(...)`:** Memperluas tanda tangan secara *backward-compatible* dengan parameter opsional:
  ```python
  def evaluate_student_ews(
      final_score: Optional[float],
      mastery_threshold: float,
      alpa_count: int,
      alpa_threshold: int,
      unsubmitted_checklist_count: int = 0,
      unsubmitted_checklist_threshold: int = 3,
  ) -> Dict[str, Any]:
  ```
  - Validasi: `unsubmitted_checklist_count >= 0`, `unsubmitted_checklist_threshold >= 1`.
  - Pemicu baru: `checklist_over = int(unsubmitted_checklist_count) >= int(unsubmitted_checklist_threshold)`.
  - Jika `checklist_over`: tambahkan `"unsubmitted_checklist"` ke `triggers` dan `"Belum mengumpulkan {unsubmitted_checklist_count} tugas pengumpulan (batas peringatan: {unsubmitted_checklist_threshold} tugas)"` ke `reasons`.
  - Severity: `len(triggers) >= 2` -> `"kritis"`, `len(triggers) == 1` -> `"perhatian"`, `0` -> `"aman"`.
  - Sertakan field `unsubmitted_checklist_count` dan `unsubmitted_checklist_threshold` pada dict hasil.
- **Pemisahan di `AnalyticsService`:**
  - `get_teacher_dashboard`, `get_early_warning_report`, `compare_students_for_teacher`, dan `_build_student_analytics` hanya menyertakan asesmen `is_graded = True` dalam perhitungan `final_score`, statistik kelas, distribusi nilai, dan grafik tren.
  - Ketiga titik EWS (`get_teacher_dashboard`, `get_early_warning_report`, `_build_student_analytics`) menghitung `unsubmitted_checklist_count` dari seluruh asesmen kelas berstatus `published` dengan `is_graded = False` yang belum memiliki `score >= 1` untuk siswa terkait, sehingga hasil EWS guru dan siswa 100% sinkron.
  - `_build_student_analytics` menambahkan array `"checklist_tasks"` berisi seluruh asesmen `published` bertipe `is_graded = False` milik kelas siswa (`assessment_id`, `assessment_date`, `material_title`, `title`, `category`, `submitted`, `feedback`), terpisah dari `"grade_timeline"` (khusus `is_graded = True`).
- **`ReportService`:** Pada `export_class_grades` dan `export_student_report`, saring asesmen bernilai (`is_graded = True`) untuk perhitungan nilai/rata-rata agar angka `1.0` checklist tidak pernah tercampur ke nilai numerik.

### 3.3 Desain UI & Koreksi `anti-slop` (Mode 1: During)
- **Liveliness & Purpose-Gate:**
  - **Satu titik fokus modal (`C-1`, `R-12`):** Saat siswa masuk EWS, modal tengah menjadi fokus tunggal dengan *scrim* gelap (`rgba(15, 23, 42, 0.72)`) dan bayangan terangkat selektif; tanpa *glow* berlebih (`R-13`) dan tanpa `backdrop-filter` pada kartu biasa (`R-10`, hanya 1 permukaan modal jika dipakai).
  - **Tanpa emoji dekoratif (`R-04`):** Ganti `⚠️` dengan ikon SVG inline `aria-hidden="true"` berukuran `24×24` px.
  - **Kontras WCAG AA terverifikasi `contrast_check.py` (`R-25`, `R-34`):**
    - Mode Gelap (Perhatian): latar `#0f172a`, teks judul `#f8fafc` (17.06:1), teks isi `#cbd5e1` (12.02:1), aksen label `#fde68a` (14.33:1), tombol Mengerti `#ffffff` di `#0369a1` (5.93:1).
    - Mode Gelap (Kritis): latar `#450a0a`, teks judul `#fef2f2` (14.76:1), teks isi `#fecaca` (11.16:1), tombol Mengerti `#ffffff` di `#b91c1c` (6.47:1).
    - Mode Terang (Perhatian): latar `#ffffff`, teks judul `#0f172a` (17.85:1), teks isi `#334155` (10.35:1), aksen lencana `#92400e` di `#fffbeb` (6.84:1), tombol Mengerti `#ffffff` di `#0369a1` (5.93:1).
    - Mode Terang (Kritis): latar `#fef2f2`, teks judul `#7f1d1d` (9.16:1), teks isi `#0f172a` (16.4:1), tombol Mengerti `#ffffff` di `#b91c1c` (6.47:1).
  - **Aksesibilitas & Mobile (`R-03`, `R-32`, `R-39`):** `role="dialog"`, `aria-modal="true"`, `aria-labelledby="ews-modal-title"`, tombol **Mengerti** dan tombol tutup `×` minimal `44×44 px`, fokus dipindahkan ke tombol **Mengerti** saat modal terbuka, mendukung tutup dengan `Escape` dan klik area luar, indikator `:focus-visible` kontras tinggi, serta `@media (prefers-reduced-motion: reduce)` mematikan transisi.
  - **Teks UI Baru Bebas Em Dash (`R-02`):** Seluruh label dan pesan baru menggunakan titik dua, koma, atau tanda kurung.

### 3.4 Failure Modes, Security & Rollback
- **Migrasi DB pada Supabase PostgreSQL yang sudah berjalan:** `ALTER TABLE assessments ADD COLUMN IF NOT EXISTS is_graded BOOLEAN NOT NULL DEFAULT TRUE` bersifat non-destruktif dan idempoten; seluruh baris lama langsung bernilai `TRUE`.
- **Kompatibilitas Uji Lama (`egm_v8_2_corrections_ews_test.py`):** Karena modal EWS tidak lagi auto-dismiss 3 detik melainkan menutup saat klik **Mengerti** / tombol tutup / `Escape`, uji runtime Node di `egm_v8_2_corrections_ews_test.py` harus diperbarui agar menguji perilaku klik **Mengerti** dan tombol `Escape`.
- **RBAC & Anti-IDOR:** Tidak ada perubahan hak akses; guru tetap hanya dapat mengelola asesmen dan checklist untuk kelas miliknya sendiri.

---

## 4. Alternatives Considered

1. **Alternatif A — Membuat Tabel Terpisah `checklist_tasks` dan `checklist_submissions`:**
   - *Alasan Ditolak:* Menggandakan hampir seluruh CRUD materi, publikasi draft/published, filter materi, dan relasi kelas/periode yang sudah stabil di `assessments`/`grades`. Menambahkan satu flag boolean `is_graded` jauh lebih ringkas, aman, dan mudah dirawat (YAGNI).
2. **Alternatif B — Mempertahankan Auto-Dismiss 5 Detik pada Modal EWS:**
   - *Alasan Ditolak:* Pemilik proyek secara eksplisit meminta modal EWS di tengah layar ditutup secara sadar oleh siswa melalui tombol **Mengerti** agar peringatan akademik tidak terlewat.

---

## 5. Target Scope & File Boundary (Allowlist Fase 5)

Hanya berkas berikut yang diizinkan diubah atau dibuat pada Fase 5:

### Berkas yang Diubah (15 berkas)
1. `edutrack/configs/app_config.py`
2. `edutrack/domain/models.py`
3. `edutrack/repositories/database.py`
4. `edutrack/repositories/grade_repo.py`
5. `edutrack/services/grade_service.py`
6. `edutrack/services/analytics_service.py`
7. `edutrack/services/report_service.py`
8. `edutrack/web/api.py`
9. `edutrack/web/static/index.html`
10. `edutrack/web/static/styles.css`
11. `edutrack/web/static/js/teacher.js`
12. `edutrack/web/static/js/student.js`
13. `edutrack/web/static/sw.js`, `edutrack/web/static/app.js`, `edutrack/web/static/js/api.js`, `edutrack/web/static/js/charts.js` (penyelarasan cache-bust `20261120-v8.3` / `edutrack-shell-v8.3`)
14. `edutrack/tests/egm_v8_bugfix_test.py`, `edutrack/tests/egm_v8_2_1_rebrand_test.py`, `edutrack/tests/egm_v8_2_corrections_ews_test.py` (penyesuaian versi cache-bust `v8.3` & uji modal klik **Mengerti**)

### Berkas Baru (1 berkas)
15. `edutrack/tests/egm_v8_3_ungraded_tasks_ews_modal_test.py`

*(Total 19 berkas eksisting diubah + 1 berkas uji baru)*

---

## 6. Actionable Steps (Zero-Decision Implementation Plan)

1. **Konfigurasi & Model (`app_config.py`, `models.py`):**
   - Tambahkan `ews_unsubmitted_checklist_threshold: int = 3` di `AppConfig` dan baca dari `EDUTRACK_EWS_UNSUBMITTED_THRESHOLD` pada `from_env()` (minimal 1).
   - Tambahkan `is_graded: bool = True` pada dataclass `Assessment`.
2. **Database Migrasi v6 (`database.py`):**
   - Tambahkan `is_graded` ke DDL `CREATE TABLE IF NOT EXISTS assessments` (SQLite & PostgreSQL).
   - Tambahkan `(6, "assessments_is_graded_flag", self._mig_006_assessments_is_graded)` di `_run_versioned_migrations()` dan implementasikan `_mig_006_assessments_is_graded`.
3. **Repositori Nilai (`grade_repo.py`):**
   - Baca `is_graded` di `_row_to_assessment` (default `True` bila kolom belum ada pada mock row lama).
   - Tambahkan parameter `is_graded: bool = True` pada `create_assessment` dan `is_graded: Optional[bool] = None` pada `update_assessment` menggunakan `self._db.bool_val(...)`.
   - Sertakan `a.is_graded` pada `SELECT` di `list_grades_for_class` dan `list_grades_for_student`.
4. **Layanan Nilai & API (`grade_service.py`, `api.py`):**
   - Di `GradeService.create_assessment` & `update_assessment`: terima `is_graded`; jika `is_graded` adalah `False`, paksa `max_score = 1.0` dan `weight = 0.0`.
   - Di `GradeService.save_grades_bulk`: jika `not assessment.is_graded`, validasi `score in (None, 0, 0.0, 1, 1.0)` lalu normalisasi `1.0` jika `score == 1`, atau `None` jika `score in (None, 0, 0.0)`.
   - Di `api.py`: tambah `is_graded: bool = True` di `AssessmentCreatePayload`, `is_graded: Optional[bool] = None` di `AssessmentUpdatePayload`, sertakan `"is_graded": a.is_graded` di `_serialize_assessment`, dan teruskan ke `grade_service`.
5. **Analitik, EWS & Laporan (`analytics_service.py`, `report_service.py`):**
   - Perluas `evaluate_student_ews(...)` dengan `unsubmitted_checklist_count: int = 0` dan `unsubmitted_checklist_threshold: int = 3`.
   - Saring asesmen `is_graded = True` pada perhitungan `final_score`, tren, statistik kelas, distribusi, dan laporan nilai (`report_service.py`).
   - Hitung `unsubmitted_checklist_count` (asesmen kelas berstatus `published` dengan `is_graded = False` yang belum dicentang `score >= 1`) dan teruskan ke `evaluate_student_ews` di `_build_student_analytics`, `get_teacher_dashboard`, serta `get_early_warning_report`.
   - Tambahkan `"checklist_tasks"` ke payload `_build_student_analytics`.
6. **Frontend Guru (`index.html`, `js/teacher.js`):**
   - Di `#form-assessment`: tambah `<select id="a-is-graded" aria-label="Jenis Penilaian">` dengan opsi `1` (`Dinilai (Angka)`) dan `0` (`Tidak Dinilai (Checklist Pengumpulan)`). Tambahkan listener `change` agar saat `0` dipilih, `#a-max` dan `#a-weight` berstatus `disabled` dengan nilai `1` dan `0`.
   - Di `teacher.js`: kirim `is_graded: el("a-is-graded").value === "1"` saat submit; tampilkan penanda `(Checklist)` pada dropdown `#select-grade-assessment`; pada `renderGradebook`, jika `asmt.is_graded === false`, tampilkan checkbox pengumpulan (`Sudah Mengumpulkan` / `Belum Mengumpulkan`) dengan label target sentuh minimal `44px` dan simpan `score: checked ? 1 : null`.
7. **Frontend Siswa & Modal EWS Tengah Anti-Slop (`index.html`, `js/student.js`, `styles.css`):**
   - Di `#stab-s-grades` (`index.html`): pisahkan menjadi dua kartu:
     - Kartu 1: `Tugas & Penilaian Bernilai` (`#s-grades-tbody`)
     - Kartu 2: `Tugas Pengumpulan (Tanpa Nilai)` (`#s-checklist-tbody`, kolom: Tanggal, Materi, Nama Tugas, Kategori, Status Pengumpulan, Catatan Guru).
   - Di `js/student.js`:
     - Render `data.grade_timeline` ke `#s-grades-tbody` dan `data.checklist_tasks` ke `#s-checklist-tbody` (dengan empty state informatif dan lencana teks `Sudah Mengumpulkan` / `Belum Mengumpulkan`).
     - Perbarui `showStudentEwsPopup(ews)` (tetap terima argumen opsional kedua demi kompatibilitas pemanggilan lama, namun abaikan auto-dismiss timer): buat overlay `#student-ews-popup.ews-modal-backdrop` di tengah layar berisi `.ews-modal-dialog` (`role="dialog"`, `aria-modal="true"`, `aria-labelledby="ews-modal-title"`), ikon SVG inline `aria-hidden="true"` (tanpa `⚠️`), judul, daftar alasan EWS, dan tombol utama **Mengerti** (`#btn-ews-ack`) + tombol tutup `×`. Tutup modal hanya saat klik **Mengerti**, klik `×`, klik backdrop luar, atau tekan `Escape` (dengan pembersihan event listener `keydown` saat ditutup).
   - Di `styles.css`: tulis langsung gaya `.ews-modal-backdrop`, `.ews-modal-dialog`, varian `--kritis` & `--perhatian` untuk `[data-theme="dark"]` dan `[data-theme="light"]`, gaya `.checklist-toggle` (44px touch target), `:focus-visible`, dan `@media (prefers-reduced-motion: reduce)`.
8. **Cache-Bust & Pengujian:**
   - Naikkan `?v=20261120-v8.2.2` -> `?v=20261120-v8.3` dan `edutrack-shell-v8.2.2` -> `edutrack-shell-v8.3` di seluruh berkas statis dan uji terkait.
   - Perbarui `egm_v8_2_corrections_ews_test.py` untuk menguji penutupan modal lewat klik **Mengerti** dan tombol `Escape`.
   - Buat `edutrack/tests/egm_v8_3_ungraded_tasks_ews_modal_test.py` (happy path, edge cases, anti-pollution nilai akhir/KKM, pemicu EWS checklist `>= 3`, migrasi v6, dan uji modal EWS tengah).

---

## 7. Test Plan, Verification & Anti-Slop Delivery Gate

### Perintah Verifikasi Wajib
1. `node --check edutrack/web/static/sw.js && for f in edutrack/web/static/app.js edutrack/web/static/js/*.js; do node --input-type=module --check < "$f"; done`
2. `python3 <skill_dir>/scripts/contrast_check.py ...` (seluruh pasangan warna modal EWS gelap & terang + lencana checklist -> wajib 100% PASS WCAG AA `>= 4.5:1`).
3. `python3 -m unittest discover -s edutrack/tests -p "*_test.py" -v`
4. `python3 -O -m unittest edutrack/tests/egm_v8_3_ungraded_tasks_ews_modal_test.py edutrack/tests/egm_v8_2_corrections_ews_test.py -v`
5. Audit `anti-slop` Delivery Gate penuh (Block 1 Hard Gate, Block 2 Purpose-Gate, Block 3 Liveliness, Block 4 Craftsmanship & Quality Locks).
