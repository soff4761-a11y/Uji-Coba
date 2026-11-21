# Spesifikasi Desain Teknis EduTrack v7 — Penguatan Keamanan Kritis, Performa/DB & Modularisasi Frontend (EGM)

## 1. Tujuan & Ringkasan Perubahan
Dokumen ini menetapkan spesifikasi lengkap (Zero-Decision) untuk 3 kelompok pembaruan besar pada EduTrack:
1. **Perbaikan Keamanan Kritis:**
   - Menutup celah pemulihan akun publik (`/api/auth/recovery/request` & `/api/auth/recovery/reset`) dan **menghapus seluruh fitur reset password via email (SMTP)**.
   - Menetapkan kredensial default peserta didik: **username = NIS** (`student_code`) dan **password = `12345678`** (wajib ganti sandi saat login pertama).
   - Menambahkan fitur **ubah username oleh siswa** (`PATCH /api/student/username`) serta **reset username & password ke NIS + `12345678` oleh guru** (`POST /api/teacher/students/{student_id}/reset-credentials` dan default `12345678` pada `reset-password`).
   - Menghapus `token` dari respons JSON `/api/auth/login` dan menghapus `sessionStorage` token di frontend; menggunakan **cookie `HttpOnly` + Double-Submit CSRF (`edutrack_csrf` cookie + header `X-CSRF-Token`)** pada seluruh permintaan mutasi (`POST/PUT/PATCH/DELETE`).
   - Memanggil `revoke_all_user_sessions(user.id)` di dalam `AuthService.change_password()`, kemudian pada `/api/auth/change-password` mencabut sesi lama dan menerbitkan sesi baru dalam cookie `HttpOnly` segar (atau memaksa login ulang jika diminta) sehingga sesi di perangkat lain langsung tidak valid.
   - Menambahkan peran **`Role.ADMIN`** (`admin`) dan membatasi endpoint `/api/teacher/backups` serta `/api/teacher/backups/restore` khusus untuk peran Admin (`get_current_admin`).
   - Menyembunyikan detail galat internal (`str(exc)` di `/api/health`, `type(exc).__name__` di `_handle_unexpected_error`) agar hanya dicatat di log server.
2. **Penyempurnaan Performa & Basis Data:**
   - **Throttling `touch_session_activity`:** hanya memperbarui `last_activity_at` di DB jika selisih waktu `>= session_touch_interval_seconds` (bawaan **300 detik / 5 menit**).
   - **Connection Pooling (`psycopg_pool`):** menambahkan `psycopg_pool.ConnectionPool` pada `Database` saat mode PostgreSQL (fallback aman ke `_default_postgres_connector` jika custom connector diinjeksi atau `psycopg_pool` tidak tersedia).
   - **Pagination (`limit`/`offset`) & Streaming Ekspor:** menambahkan `limit` & `offset` pada endpoint daftar (kelas, siswa, asesmen, koreksi, audit log) serta generator `StreamingResponse` chunked untuk ekspor CSV/XLSX/PDF.
   - **Skema, Indeks, Translasi SQL & Migrasi Berversi (`schema_migrations`):**
     - Memperbaiki `translate_sql_to_postgres` agar tidak menambahkan `RETURNING id` pada query CTE (`WITH`), `ON CONFLICT ... DO NOTHING`, atau tabel tanpa kolom `id` (`schema_migrations`).
     - Menambahkan `CheckViolation` dan `NotNullViolation` pada `_is_integrity_exception`.
     - Menambahkan constraint `CHECK (score IS NULL OR score >= 0)` pada `grades.score`.
     - Menambahkan indeks komposit pada `student_enrollments(student_id, class_id)`, `learning_materials(class_id, is_archived, sort_order)`, `grade_history(assessment_id, student_id, changed_at)`, dan `attendance_history(session_id, student_id, changed_at)`.
     - Menggunakan tipe asli PostgreSQL (`TIMESTAMPTZ` dan `BOOLEAN`) pada skema PostgreSQL baru + tabel migrasi berversi `schema_migrations(version, name, applied_at)`.
3. **Penyempurnaan Frontend (Modul ES & Grafik SVG):**
   - Memecah `app.js` monolitik menjadi modul ES: `js/state.js`, `js/api.js`, `js/charts.js`, `js/teacher.js`, `js/student.js`, dan entry point `app.js` (`<script type="module">`), serta memperbarui `sw.js` untuk men-cache semua modul.
   - Menggabungkan `renderUnifiedDoughnutChart` & `renderDonutChart` menjadi satu komponen `renderDoughnutChart` di `charts.js`, membuat `renderBarChart` responsif/dapat digulir horizontal saat item banyak, dan membuat sumbu Y `renderLineChart` dinamis sesuai rentang data aktual.

---

## 2. Spesifikasi Detail per Komponen

### A. Keamanan Kritis
1. **Penghapusan Pemulihan Publik & Reset Email:**
   - Hapus `POST /api/auth/recovery/request`, `POST /api/auth/recovery/reset`, `RecoveryRequestPayload`, `RecoveryResetPayload` dari `api.py`.
   - Hapus `create_recovery_token`, `reset_password_with_token`, `_send_smtp_email`, dan parameter `email_sender` dari `auth_service.py`, serta hapus field `smtp_*` & `allow_direct_recovery_token` dari `app_config.py`.
   - Hapus panel `#panel-recovery` dan tombol `#btn-toggle-recovery` dari `index.html`; ganti footer login dengan informasi singkat agar menghubungi guru kelas untuk reset kredensial ke NIS & sandi standar.
2. **Default Kredensial Murid (NIS + `12345678`), Ubah Username Murid, & Reset Kredensial oleh Guru:**
   - Di `StudentService.create_student()` dan `confirm_student_excel_import()`:
     - Jika `username` kosong: gunakan **NIS (`student_code`)** yang dinormalisasi (`re.sub(r"\s+", "", student_code.strip())`, fallback unik jika bentrok).
     - Jika `initial_password` kosong: gunakan **`12345678`** (`DEFAULT_STUDENT_PASSWORD = "12345678"`).
   - Di `StudentService.reset_student_credentials(teacher, student_id, reset_username=True)` (`POST /api/teacher/students/{student_id}/reset-credentials`):
     - Memverifikasi kepemilikan guru atas siswa.
     - Menyetel `username` siswa kembali ke NIS (`student.student_code` yang dibersihkan; tolak dengan `ConflictError` jika NIS tersebut kebetulan dipakai user lain).
     - Mereset kata sandi ke `12345678` (di-hash PBKDF2, `must_change_password=True`, `activate_if_pending=False`), mencabut seluruh sesi lama siswa (`revoke_all_user_sessions`), mencatat log audit, dan mengembalikan `{"username": ..., "temporary_password": "12345678", ...}`.
   - Di `StudentService.reset_student_password()`: default kata sandi sementara jika tidak diisi diubah menjadi `"12345678"`.
   - Endpoint baru **`PATCH /api/student/username`** (`StudentUsernamePayload(username: str)`): memungkinkan siswa mengubah username miliknya sendiri (minimal 3 karakter, tanpa spasi, unik) dengan audit log.
3. **Cookie HttpOnly + Double-Submit CSRF (Tanpa `sessionStorage`):**
   - `AppConfig`: tambahkan `csrf_cookie_name: str = "edutrack_csrf"` dan `session_touch_interval_seconds: int = 300`.
   - `/api/auth/login`:
     - Hanya mengembalikan `{"expires_at": ..., "user": ...}` (TIDAK menyertakan `token` di body JSON!).
     - Menyetel 2 cookie: `edutrack_session` (`httponly=True, samesite="lax", secure=cfg.cookie_secure`) dan `edutrack_csrf` (`httponly=False, samesite="lax", secure=cfg.cookie_secure`, nilai random 32 byte).
   - Proteksi CSRF di `api.py`:
     - Pada setiap request dengan metode mutasi (`POST`, `PUT`, `PATCH`, `DELETE`) yang bukan `/api/auth/login` dan mengandalkan cookie sesi (`request.cookies.get(cfg.cookie_name)` ada): verifikasi `secrets.compare_digest(cookie_csrf, header_csrf)` di mana `header_csrf = request.headers.get("X-CSRF-Token", "")`. Jika tidak cocok/kosong, kembalikan `AuthorizationError` (HTTP 403, `code="csrf_failed"`).
     - Catatan kompatibilitas test: pada `TestClient`, helper `_login()` di test otomatis membaca cookie `edutrack_csrf` dan menyertakan header `X-CSRF-Token` pada client tersebut!
   - Di `js/api.js`: baca cookie `edutrack_csrf` dari `document.cookie` dan kirimkan `headers["X-CSRF-Token"] = csrf` pada setiap request `POST/PUT/PATCH/DELETE`. Hapus seluruh `sessionStorage` untuk `edutrack_token`.
4. **Cabut Sesi Lama di `change_password()`:**
   - Di `AuthService.change_password()`: panggil `self._user_repo.revoke_all_user_sessions(user.id)` setelah `update_password(...)`.
   - Pada endpoint `POST /api/auth/change-password`: setelah `change_password()` berhasil mencabut seluruh sesi lama, terbitkan 1 sesi baru untuk perangkat saat ini (memanggil `create_session` + menyetel cookie `edutrack_session` & `edutrack_csrf` baru) sehingga semua sesi di perangkat lain langsung hangus, sedangkan perangkat yang baru mengganti sandi (termasuk siswa `pending_activation` pada aktivasi pertama) tetap berjalan mulus tanpa error 401!
5. **Batasi Backup/Restore Khusus Admin (`Role.ADMIN`):**
   - Tambah `ADMIN = "admin"` pada `enum Role` di `edutrack/domain/models.py`.
   - Perbarui CHECK constraint `role IN ('admin', 'teacher', 'student')` pada `users` (migrasi berversi + DDL).
   - Tambah `AuthService.register_admin(...)` dan dependency `get_current_admin` di `api.py`.
   - Ganti dependency `/api/teacher/backups`, `POST /api/teacher/backups`, dan `POST /api/teacher/backups/restore` menjadi `Depends(get_current_admin)`. Di frontend, sembunyikan kartu Backup/Restore jika `state.user.role !== "admin"`.
6. **Sembunyikan Detail Galat Internal:**
   - `/api/health`: log exception via `logger.exception("Health check failed")`, kembalikan `{"status": "degraded", "database_backend": backend, "database_connected": False}` tanpa `detail`.
   - `_handle_unexpected_error`: kembalikan `{"detail": "Terjadi kesalahan internal pada server. Silakan muat ulang halaman atau coba lagi.", "code": "internal_server_error"}` tanpa `type(exc).__name__`.

### B. Performa & Basis Data
1. **Throttling `touch_session_activity`:**
   - Tambah metode `get_active_session_with_activity(token_hash, now_iso)` di `user_repo.py` yang mengembalikan `(User, last_activity_at)`.
   - Di `AuthService.authenticate_token()`: panggil `touch_session_activity` hanya jika `(now - last_act_dt).total_seconds() >= self._config.session_touch_interval_seconds` (default `300`).
2. **Connection Pooling PostgreSQL (`psycopg_pool`):**
   - Tambah `psycopg-pool>=3.2.0` ke `requirements.txt` & `edutrack/requirements.txt`.
   - Di `Database.__init__`: jika `is_postgres` dan tidak ada custom `pg_connector` yang diinjeksi, inisialisasi `psycopg_pool.ConnectionPool(conninfo=normalized, min_size=1, max_size=5, kwargs={"row_factory": dict_row, "prepare_threshold": None, "connect_timeout": 10})` dengan fallback aman ke `_default_postgres_connector` jika `psycopg_pool` belum terpasang. `request_scope()` meminjam koneksi dari pool (`pool.getconn()`) secara lazy dan mengembalikannya (`pool.putconn(conn)`) di `finally`.
3. **Pagination & Streaming Ekspor:**
   - Tambah parameter opsional `limit: Optional[int] = None, offset: int = 0` (dengan validasi `offset >= 0`, `1 <= limit <= 500` jika disetel) pada:
     - `GET /api/teacher/classes`
     - `GET /api/teacher/students`
     - `GET /api/teacher/classes/{class_id}/assessments`
     - `GET /api/teacher/corrections`
     - `GET /api/teacher/audit-logs`
   - Tambah `stream_export_class_grades`, `stream_export_attendance_recap`, `stream_export_individual_progress` (atau generator chunk 64KB + row-by-row CSV generator) sehingga `/api/reports/*` memakai `StreamingResponse(iterator, media_type=...)` tanpa menampung seluruh CSV sekaligus di memori.
4. **Translasi SQL, Integrity Exceptions, Constraints, Indeks Komposit, Tipe Native PG, & Migrasi Berversi:**
   - `translate_sql_to_postgres`: hanya tambahkan `RETURNING id` jika pernyataan dimulai dengan `INSERT INTO ` (bukan `WITH `), tidak mengandung `RETURNING `, tidak mengandung `ON CONFLICT` + `DO NOTHING`, dan target tabel bukan tabel tanpa kolom `id` (seperti `schema_migrations`).
   - `_is_integrity_exception`: tambahkan `"CheckViolation"` dan `"NotNullViolation"`.
   - `grades.score`: tambahkan `CHECK (score IS NULL OR score >= 0)`.
   - Indeks komposit baru:
     - `idx_enrollments_student_class ON student_enrollments(student_id, class_id)`
     - `idx_materials_class_arch_order ON learning_materials(class_id, is_archived, sort_order)`
     - `idx_grade_history_lookup ON grade_history(assessment_id, student_id, changed_at)`
     - `idx_att_history_lookup ON attendance_history(session_id, student_id, changed_at)`
   - Tipe asli PostgreSQL pada `POSTGRES_SCHEMA_STATEMENTS`: gunakan `TIMESTAMPTZ` untuk kolom waktu (`created_at`, `updated_at`, `expires_at`, `revoked_at`, `last_activity_at`, `enrolled_at`, `left_at`, `changed_at`, `attempted_at`) dan `BOOLEAN` (`DEFAULT FALSE`/`TRUE`) untuk flag boolean; pastikan repository membandingkan boolean secara portabel (`= FALSE` / `= 0` — gunakan parameter `?` dengan `False`/`0` atau `CASE`/`COALESCE` yang aman di SQLite & PostgreSQL!).
   - **Migrasi Berversi (`schema_migrations`):** Buat tabel `schema_migrations(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)` dan jalankan daftar migrasi bernomor (`v1`..`v5`) secara idempoten hanya untuk versi yang belum tercatat.

### C. Frontend Modular ES & Grafik SVG
- Pecah `app.js` menjadi:
  - `edutrack/web/static/js/state.js` — `state`, `escapeHtml`, `setHtml`, `onById`, `toast`, `showView`, `applyTheme`, `toggleTheme`.
  - `edutrack/web/static/js/api.js` — `getCsrfToken`, `api()`, `downloadAuthenticatedFile()`, **ZERO `sessionStorage` token**.
  - `edutrack/web/static/js/charts.js` — komponen tunggal `renderDoughnutChart` (menghapus duplikasi `renderUnifiedDoughnutChart` & `renderDonutChart`), `renderBarChart` responsif dengan horizontal scroll container saat item banyak, dan `renderLineChart` dengan skala Y dinamis (`minVal`..`maxVal` + padding).
  - `edutrack/web/static/js/teacher.js` — portal guru (dashboard, EWS, kelas, pengumuman, siswa + bulk delete + reset ke NIS/`12345678`, materi & buku nilai, kehadiran + offline PWA sync, laporan/audit, sesi aktif, backup admin-only).
  - `edutrack/web/static/js/student.js` — portal siswa (sidebar dinamis, topbar identitas, jam real-time, filter materi, 3 donat seragam, pengumuman read-only, koreksi, ubah username siswa, sesi aktif).
  - `edutrack/web/static/app.js` — entry point ES module (`<script type="module" src="/static/app.js?v=20261120-v7"></script>`).
- Perbarui `sw.js` untuk men-cache semua modul `/static/js/*.js` dan naikkan versi cache ke `edutrack-shell-v7`.

---

## 3. Target Scope & File Boundary
- `requirements.txt`, `edutrack/requirements.txt`
- `edutrack/configs/app_config.py`
- `edutrack/domain/models.py`
- `edutrack/repositories/database.py`
- `edutrack/repositories/user_repo.py`
- `edutrack/repositories/academic_repo.py`
- `edutrack/repositories/grade_repo.py`
- `edutrack/repositories/attendance_repo.py`
- `edutrack/services/auth_service.py`
- `edutrack/services/student_service.py`
- `edutrack/services/classroom_service.py`
- `edutrack/services/grade_service.py`
- `edutrack/services/attendance_service.py`
- `edutrack/services/report_service.py`
- `edutrack/web/api.py`
- `edutrack/web/static/index.html`, `styles.css`, `sw.js`, `app.js`
- `edutrack/web/static/js/{state,api,charts,teacher,student}.js` (baru)
- `edutrack/tests/egm_v7_hardening_test.py` (baru) + penyesuaian tes lama untuk CSRF & penghapusan recovery publik/email.
