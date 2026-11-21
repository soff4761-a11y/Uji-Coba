# Design Specification — EduTrack EGM v2 Revision

**Status:** Draft (Pending Goldfish Implementation Readiness Review)
**Target Scope & File Boundary:**
- `edutrack/configs/app_config.py`
- `edutrack/repositories/database.py`
- `edutrack/repositories/user_repo.py`
- `edutrack/services/auth_service.py`
- `edutrack/services/classroom_service.py`
- `edutrack/services/student_service.py`
- `edutrack/services/grade_service.py`
- `edutrack/web/api.py`
- `edutrack/web/static/index.html`
- `edutrack/web/static/styles.css`
- `edutrack/web/static/app.js`
- `edutrack/tests/egm_v2_integration_test.py`

## 1. Perbaikan Bug Penghapusan Kelas (HTTP 500 -> Safe Dependency Check)
- **Akar Masalah:** `classroom_service.py:delete_classroom(force=True)` mengeksekusi `DELETE FROM student_profiles WHERE class_id = ?`, padahal nama tabel di skema adalah `students` dengan kolom `current_class_id REFERENCES classes(id) ON DELETE RESTRICT`, sehingga langsung memicu `OperationalError`/`UndefinedTable` -> HTTP 500.
- **Solusi:**
  - Tambah `ClassroomService.get_classroom_dependencies(teacher, class_id)` & endpoint `GET /api/teacher/classes/{class_id}/dependencies` yang menghitung `students`, `assessments`, `grades`, `attendance_sessions`, `attendance_records`.
  - Perbaiki `delete_classroom(teacher, class_id, confirm_permanent)`: jalankan dalam transaksi atomik; apabila masih ada data terkait (`students > 0` atau `assessments > 0` atau `grades > 0` atau `attendance_sessions > 0` atau `attendance_records > 0`), tolak penghapusan permanen dengan `ConflictError` (HTTP 409) disertai pesan informatif dan anjuran arsip (`PATCH /api/teacher/classes/{class_id}` `is_archived=true`). Jika benar-benar kosong dan `confirm_permanent=True`, hapus bersih `student_enrollments` dan `classes` dalam transaksi.
  - Di UI: `deleteClass(id)` memeriksa `/dependencies` terlebih dahulu; jika ada data terkait, tampilkan dialog aman yang menawarkan **Arsipkan Kelas** alih-alih menghapus data historis.

## 2. Automatic Session Timeout 60 Menit (Server + Frontend)
- **Skema & Migrasi:** Tambah kolom `last_activity_at TEXT` pada tabel `sessions` (SQLite & PostgreSQL) beserta migrasi idempoten di `Database.initialize()`.
- **Konfigurasi:** `AppConfig.session_idle_timeout_minutes: int = 60` (`EDUTRACK_SESSION_IDLE_TIMEOUT_MINUTES`).
- **Server-Side:** `UserRepository.create_session` mengisi `last_activity_at = now`. `AuthService.authenticate_session` memeriksa `expires_at > now` DAN selisih `now - last_activity_at <= session_idle_timeout_minutes`. Jika melewati batas idle, cabut sesi di DB (`revoke_session`) dan lempar `AuthenticationError` khusus (HTTP 401 + header `X-Session-Expired: idle`). Jika aktif, perbarui `last_activity_at = now`. Tambah `POST /api/auth/ping` untuk refresh aktivitas ringan.
- **Frontend:** Monitor aktivitas nyata (`click`, `keydown`, `input`, `change`, `submit`, `touchstart`) pada portal guru & siswa, kirim `/api/auth/ping` ter-throttle (tiap 2 menit jika ada aktivitas), tampilkan banner peringatan 5 menit sebelum habis (menit ke-55) dengan tombol "Perpanjang Sesi", dan otomatis logout + arahkan ke halaman login dengan notifikasi jelas pada menit ke-60 (atau jika API mengembalikan 401 idle).

## 3. Penyelarasan Diagram Donat pada Dashboard Peserta Didik
- Buat helper tunggal responsif `renderUnifiedDoughnutChart(containerId, opts)` yang digunakan oleh ketiga panel:
  1. `chart-s-trend` (**Perkembangan Nilai Pribadi**): donat menampilkan kontribusi/capaian tiap penilaian terpublikasi berurutan kronologis, nilai tengah menampilkan nilai akhir/rata-rata + indikator tren historis (`Naik` / `Stabil` / `Turun` + delta), legenda memuat nama penilaian, skor, dan persentase.
  2. `chart-s-category` (**Capaian per Kategori**): donat menampilkan rata-rata per kategori penilaian, nilai tengah menampilkan rata-rata kategori, legenda memuat kategori, rata-rata, dan persentase.
  3. `chart-s-attendance` (**Ringkasan Kehadiran Pribadi**): donat seragam untuk Hadir/Sakit/Izin/Alpa, nilai tengah `% Hadir`, legenda jumlah & persentase.
- Empty state informatif: `"Belum ada data penilaian"` / `"Belum ada data kehadiran"`.

## 4. Template & Impor Data Peserta Didik (Excel `.xlsx` + Preview & Konfirmasi)
- `GET /api/teacher/students/import-template`: unduh `.xlsx` dengan sheet `Data Peserta Didik` (`No.`, `NIS / Identitas`, `Nama Peserta Didik`, `Username`, `Password`, `Catatan`) + 2 baris contoh, dan sheet `Petunjuk Pengisian`.
- `POST /api/teacher/classes/{class_id}/students/import/preview`: validasi tanpa menyimpan (kelengkapan nama/username/password min. 8 karakter, keunikan username terhadap DB & internal file, duplikasi NIS). Mengembalikan `valid_rows` & `invalid_rows` (beserta `row_number`, `column`, `reason`).
- `POST /api/teacher/classes/{class_id}/students/import/confirm`: menyimpan baris valid dengan PBKDF2 hash (`must_change_password=True`), terhubung langsung ke `class_id`, tanpa mengembalikan password tersimpan.

## 5. Template & Impor Nilai Peserta Didik (Excel `.xlsx` + Preview, Konflik & Konfirmasi)
- `GET /api/teacher/assessments/{assessment_id}/import-template`: unduh `.xlsx` berisi metadata konteks (Kelas, Tingkat/Mapel, Tahun/Semester, Kategori, Nama Asesmen, Tanggal, Skor Maks, Status) + daftar siswa kelas terkait (`No.`, `Identitas Peserta Didik`, `Nama Peserta Didik`, `Nilai`, `Umpan Balik`).
- `POST /api/teacher/assessments/{assessment_id}/grades/import/preview`: mencocokkan `Identitas Peserta Didik` ke siswa kelas terkait, memvalidasi rentang `0..max_score`, memastikan sel kosong != 0, mendeteksi nilai eksisting (`has_existing`, `existing_score`), mengembalikan `valid_rows`, `invalid_rows`, dan hitungan konflik.
- `POST /api/teacher/assessments/{assessment_id}/grades/import/confirm`: menerima `conflict_mode` (`skip` | `overwrite` | `cancel`), tidak menimpa nilai lama tanpa `overwrite`, mencatat `grade_history` & `audit_logs`, menjaga status `draft` tetap tersembunyi dari siswa hingga dipublikasikan, mengembalikan `{ inserted, updated, skipped, failed }`.
