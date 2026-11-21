# Design Specification — EduTrack EGM v3 Revision

**Status:** Draft (Pending Goldfish Implementation Readiness Review)
**Target Scope & File Boundary:**
- `edutrack/domain/models.py`
- `edutrack/repositories/database.py`
- `edutrack/repositories/grade_repo.py`
- `edutrack/repositories/attendance_repo.py`
- `edutrack/repositories/academic_repo.py`
- `edutrack/services/grade_service.py`
- `edutrack/services/analytics_service.py`
- `edutrack/services/student_service.py`
- `edutrack/services/attendance_service.py`
- `edutrack/web/api.py`
- `edutrack/web/static/index.html`
- `edutrack/web/static/styles.css`
- `edutrack/web/static/app.js`
- `edutrack/tests/egm_v3_integration_test.py`

## 1. Perbaikan Bug Visualisasi Nilai Dashboard Peserta Didik (Prioritas 1)
- **Akar Masalah:** `analytics_service.py:466` mengembalikan key `"category_comparison"`, sedangkan `app.js:1065` membaca `data.category_averages` (`undefined`), sehingga diagram donat **Capaian per Kategori Penilaian** selalu jatuh ke empty state. Selain itu, kedua diagram belum mendukung filter materi dan perlu memastikan `normalized_score` (termasuk nilai `0`) tetap dirender valid tanpa error pembagian nol.
- **Solusi:**
  - Di `app.js`: baca `data.category_comparison || data.category_averages || []`, jaga nilai `0` agar tampil dengan proporsi minimal visual `0.01` namun tetap menampilkan nilai asli `0` di legenda, dan pastikan kedua diagram donat (`#chart-s-trend` & `#chart-s-category`) selalu terbarui saat filter materi berubah.

## 2. Fitur Materi Pembelajaran pada Penilaian & Buku Nilai (Prioritas 2)
- **Skema & Migrasi (`database.py`, `models.py`):**
  - Tabel baru `learning_materials` (SQLite & PostgreSQL): `id`, `class_id REFERENCES classes(id) ON DELETE CASCADE`, `period_id REFERENCES academic_periods(id) ON DELETE RESTRICT`, `teacher_id REFERENCES users(id) ON DELETE CASCADE`, `title TEXT NOT NULL`, `description TEXT NOT NULL DEFAULT ''`, `sort_order INTEGER NOT NULL DEFAULT 1`, `is_archived INTEGER NOT NULL DEFAULT 0`, `created_at TEXT NOT NULL`, `updated_at TEXT NOT NULL`.
  - Tambah kolom nullable `material_id INTEGER REFERENCES learning_materials(id) ON DELETE SET NULL` pada `assessments` melalui migrasi idempoten SQLite (`PRAGMA table_info(assessments)`) & PostgreSQL (`ALTER TABLE assessments ADD COLUMN IF NOT EXISTS material_id INTEGER REFERENCES learning_materials(id) ON DELETE SET NULL`). Nilai lama tetap dipertahankan dengan `material_id = NULL` ("Belum Dikelompokkan") agar guru dapat mengelompokkannya secara manual via ubah penilaian.
  - Tambah dataclass `LearningMaterial` dan field `material_id: Optional[int] = None` pada `Assessment` di `models.py`.
- **API & Service (`grade_repo.py`, `grade_service.py`, `api.py`):**
  - `GET /api/teacher/classes/{class_id}/materials?include_archived=false`
  - `POST /api/teacher/classes/{class_id}/materials` (`title`, `description`, `sort_order`)
  - `PATCH /api/teacher/materials/{material_id}` (`title`, `description`, `sort_order`, `is_archived`)
  - `DELETE /api/teacher/materials/{material_id}`: jika masih memiliki `assessments`, tolak dengan `ConflictError` (HTTP 409) dan sarankan arsip agar nilai historis tidak terlepas/hilang; jika kosong, hapus permanen.
  - Perbarui `POST /api/teacher/classes/{class_id}/assessments` dan `PATCH /api/teacher/assessments/{assessment_id}` agar menerima `material_id: Optional[int] = None` (memvalidasi materi milik kelas yang sama).
  - Perbarui `GET /api/teacher/classes/{class_id}/gradebook?material_id=...` agar mengembalikan daftar `materials`, mengelompokkan `assessments` berdasarkan materi, menghitung rata-rata per materi (`material_averages` per siswa & ringkasan antarmateri), dan mempertahankan rumus `final_score` keseluruhan kelas.

## 3. Integrasi Filter Materi pada Dashboard Peserta Didik (Prioritas 3)
- Perbarui `AnalyticsService.get_student_dashboard(..., material_id: Optional[int] = None)` dan `GET /api/student/dashboard?material_id=...`:
  - Kembalikan daftar `materials` milik kelas siswa (aktif, atau yang memiliki penilaian terpublikasi).
  - Saat `material_id` dipilih, filter `grade_timeline`, `category_comparison`, dan `grade_summary` hanya pada penilaian terpublikasi di materi tersebut (`status='published'` dan `material_id == material_id`). Saat kosong (`Semua Materi`), tampilkan seluruh penilaian terpublikasi.
  - Sertakan `material_id` dan `material_title` pada setiap item `grade_timeline` agar tabel **Daftar Nilai** menampilkan rincian materi & komponen penilaian secara terpisah.
- Di `index.html` & `app.js`: tambahkan dropdown `#s-filter-material` (**Semua Materi** / daftar materi) yang terhubung ke ringkasan, kedua diagram donat, dan tabel Daftar Nilai secara konsisten.

## 4. Fitur Hapus Semua & Hapus Terpilih pada Daftar Peserta Didik (Prioritas 4)
- `GET /api/teacher/classes/{class_id}/students/bulk-delete-preview`: menghitung total siswa di kelas, jumlah yang memiliki riwayat akademik (`grades`, `attendance_records`, `correction_requests`, atau riwayat perpindahan `student_enrollments > 1`), dan jumlah yang bersih tanpa riwayat.
- `POST /api/teacher/classes/{class_id}/students/bulk-delete`: menerima `{ delete_all: bool, student_ids: List[int], mode: "archive" | "permanent", confirm: bool }`.
  - Dibatasi ketat pada `class_id` milik guru tersebut (tidak menyentuh kelas lain).
  - Mode `"archive"` (disarankan bila ada riwayat): menonaktifkan akun (`deactivated`) & mencabut sesi secara atomik dalam satu transaksi tanpa menghapus nilai/kehadiran historis.
  - Mode `"permanent"`: memblokir siswa yang masih terhubung dengan kelas lain (`student_enrollments` > 1 kelas) dan hanya menghapus permanen setelah `confirm=True`; seluruh operasi dijalankan atomik dalam satu transaksi DB (`rollback` penuh bila gagal) dan dicatat di `audit_logs`.
- Di UI (`#tab-t-students`): tambah checkbox *Select All* (`#chk-select-all-students`) + checkbox per baris, tombol **Hapus Terpilih**, dan tombol **Hapus Semua** dengan dialog konfirmasi yang menampilkan jumlah siswa terdampak serta opsi Arsipkan/Nonaktifkan vs Hapus Permanen.

## 5. Fitur Hapus pada "Riwayat Permintaan Koreksi Saya" (Prioritas 5)
- Tambah kolom `hidden_by_student INTEGER NOT NULL DEFAULT 0` pada `correction_requests` (migrasi idempoten SQLite & PostgreSQL).
- `AttendanceRepository.list_correction_requests_for_student` memfilter `AND COALESCE(hidden_by_student, 0) = 0` (sedangkan `list_correction_requests_for_teacher` tetap menampilkan seluruh catatan tindak lanjut guru!).
- Tambah `DELETE /api/student/corrections/{request_id}` (`AttendanceService.delete_student_correction`):
  - Verifikasi kepemilikan ketat `request.student_id == profile.id` (jika bukan miliknya -> `AuthorizationError` HTTP 403 atau `NotFoundError` HTTP 404).
  - Jika `status == 'pending'`: hapus permanen baris dari `correction_requests`.
  - Jika `status != 'pending'` (sudah ditanggapi/diproses guru): set `hidden_by_student = 1` sehingga hilang dari dashboard siswa tanpa menghapus catatan guru!
  - Tidak pernah mengubah data nilai maupun kehadiran.
- Di UI (`#s-corrections-tbody`): tambahkan tombol **Hapus** dengan dialog konfirmasi dan pembaruan daftar langsung tanpa reload.

## 6. Menghapus Tulisan "DB: PostgreSQL Cloud" dari Antarmuka (Prioritas 6)
- Hapus `<div id="db-backend-badge" ...></div>` dari `edutrack/web/static/index.html` dan hapus blok pengisian teks `"DB: PostgreSQL Cloud"` / `"DB: SQLite Lokal"` di `edutrack/web/static/app.js` tanpa mengubah `/api/health` maupun konfigurasi PostgreSQL backend.
