# Spesifikasi Desain Teknis EduTrack v6 — 5 Fitur Baru (EGM)

## 1. Ringkasan & Tujuan
Dokumen ini menetapkan kontrak arsitektur, skema basis data (SQLite & PostgreSQL/Supabase), endpoint API, dan antarmuka untuk 5 fitur baru pada EduTrack tanpa merusak fitur yang sudah berjalan atau hak akses (RBAC):
1. **Papan Pengumuman Kelas** (komunikasi searah permanen Guru → Siswa per kelas).
2. **Progressive Web App (PWA) & Pencatatan Kehadiran Offline** (`manifest.json`, Service Worker `sw.js`, cache daftar kelas/siswa, antrean lokal kehadiran offline + sinkronisasi otomatis).
3. **Pembaruan Template PDF** (menghapus footer dari seluruh laporan PDF sambil mempertahankan header banner, KPI, dan diagram vektor).
4. **Penguatan Keamanan Akun & Sesi** (reset kata sandi opsional via email SMTP, manajemen sesi aktif + logout dari semua perangkat, serta rate limiting endpoint login berbasis DB untuk Vercel serverless).
5. **Sistem Peringatan Dini (Early Warning System / EWS)** berbasis `analytics_service.py` & `attendance_service.py` (penandaan otomatis siswa dengan rata-rata nilai di bawah KKM atau jumlah `alpa` melewati ambang batas).

---

## 2. Perubahan Skema Basis Data & Migrasi Idempoten (SQLite & PostgreSQL)
Seluruh perubahan bersifat aditif dan idempoten di `edutrack/repositories/database.py`:

1. **Tabel Baru `class_announcements`** (untuk Fitur 1):
   - `id` (`INTEGER PRIMARY KEY AUTOINCREMENT` / `SERIAL PRIMARY KEY`)
   - `class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE`
   - `teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE`
   - `title TEXT NOT NULL`
   - `category TEXT NOT NULL DEFAULT 'Umum'` (mis. `Jadwal Ujian`, `Perubahan Materi`, `Tenggat Tugas`, `Umum`)
   - `content TEXT NOT NULL`
   - `is_pinned INTEGER NOT NULL DEFAULT 0 CHECK(is_pinned IN (0, 1))`
   - `created_at TEXT NOT NULL`
   - `updated_at TEXT NOT NULL`
   - Indeks: `idx_announcements_class ON class_announcements(class_id, is_pinned, id)`
   - **Sifat Permanen:** Tidak ada kolom `expires_at`; pengumuman tetap tersimpan permanen sampai dihapus eksplisit oleh guru pemilik kelas.

2. **Migrasi Kolom pada `sessions`** (untuk Fitur 4b — Manajemen Sesi Aktif):
   - `user_agent TEXT NOT NULL DEFAULT ''`
   - `ip_address TEXT NOT NULL DEFAULT ''`
   - Migrasi `ALTER TABLE sessions ADD COLUMN ...` idempoten untuk SQLite dan PostgreSQL (`ADD COLUMN IF NOT EXISTS`).

3. **Tabel Baru `login_rate_limits`** (untuk Fitur 4c — Login Rate Limiting lintas instance Vercel serverless):
   - `id` (`INTEGER PRIMARY KEY AUTOINCREMENT` / `SERIAL PRIMARY KEY`)
   - `rate_key TEXT NOT NULL` (format: `ip:<ip>` dan `user:<username_lower>`)
   - `attempted_at TEXT NOT NULL` (ISO-8601 UTC)
   - Indeks: `idx_login_rate_key_time ON login_rate_limits(rate_key, attempted_at)`

4. **Tambahan `get_classroom_dependencies`** di `academic_repo.py`:
   - Sertakan jumlah `announcements` dalam ringkasan dependensi kelas agar konsisten saat penghapusan/pengarsipan kelas.

---

## 3. Desain Detail per Fitur

### Fitur 1: Papan Pengumuman Kelas
- **Model (`edutrack/domain/models.py`):** `ClassAnnouncement(id, class_id, teacher_id, title, category, content, is_pinned, created_at, updated_at)`.
- **Repository (`edutrack/repositories/academic_repo.py`):**
  - `create_announcement`, `get_announcement`, `list_announcements(class_id)`, `update_announcement`, `delete_announcement`.
- **Service (`edutrack/services/classroom_service.py`):**
  - Guru hanya boleh CRUD pengumuman pada kelas miliknya sendiri (`_get_owned_classroom`), mencatat `audit_logs`.
  - Siswa hanya boleh membaca pengumuman pada kelas aktif miliknya (`current_class_id`), read-only (tidak ada endpoint mutasi siswa).
- **API (`edutrack/web/api.py`):**
  - `GET /api/teacher/classes/{class_id}/announcements`
  - `POST /api/teacher/classes/{class_id}/announcements` (status 201)
  - `PATCH /api/teacher/announcements/{announcement_id}`
  - `DELETE /api/teacher/announcements/{announcement_id}`
  - `GET /api/student/announcements` (juga disertakan di `GET /api/student/dashboard` agar langsung tampil di Ringkasan Siswa).
- **UI (`index.html`, `app.js`):**
  - **Portal Guru:** Kartu "Papan Pengumuman Kelas" pada tab Kelas (`#tab-t-classes`) untuk membuat, mengubah, menyematkan (*pin*), dan menghapus pengumuman pada kelas aktif.
  - **Portal Siswa:** Panel "Papan Pengumuman Kelas" langsung tampil di `#stab-s-overview` (Ringkasan) dengan badge kategori (*Jadwal Ujian*, *Perubahan Materi*, *Tenggat Tugas*, *Umum*) dan penanda *Disematkan*.

### Fitur 2: Frontend PWA & Kehadiran Offline-Sync
- **Manifest (`edutrack/web/static/manifest.json`) & Ikon SVG (`edutrack/web/static/icon.svg`):**
  - `name: "EduTrack — Portal Pembelajaran"`, `short_name: "EduTrack"`, `start_url: "/"`, `display: "standalone"`, `theme_color: "#0f172a"`, `background_color: "#0f172a"`.
  - Link `<link rel="manifest" href="/manifest.json" />` dan `<meta name="theme-color" content="#0f172a" />` di `index.html`.
- **Service Worker (`edutrack/web/static/sw.js`) disajikan di root `/sw.js` & `/manifest.json` oleh `api.py`:**
  - `api.py` melayani `GET /sw.js` (`application/javascript`, `Service-Worker-Allowed: /`, `Cache-Control: no-cache`) dan `GET /manifest.json` (`application/manifest+json`) agar scope Service Worker mencakup seluruh aplikasi `/`.
  - Strategi caching:
    - **App Shell (`/`, `/static/styles.css`, `/static/app.js`, `/manifest.json`, `/static/icon.svg`):** Network-first dengan fallback ke cache offline.
    - **API GET daftar kelas & siswa (`/api/teacher/classes`, `/api/teacher/students`):** Network-first dengan fallback cache lokal di `localStorage` (`edutrack_offline_classes`, `edutrack_offline_students_<class_id>`) agar guru tetap bisa membuka kelas dan daftar siswa saat sinyal mati.
- **Antrean Kehadiran Offline & Sinkronisasi Otomatis (`app.js`):**
  - Saat guru menekan **Simpan Kehadiran** ketika `!navigator.onLine` atau `fetch` gagal karena jaringan (`TypeError`), catatan kehadiran (`class_id`, `session_date`, `meeting_number`, `topic`, `records`, `queued_at`, `client_id`) disimpan ke `localStorage` (`edutrack_offline_att_queue`).
  - Banner status koneksi + jumlah antrean tertunda ditampilkan pada tab Kehadiran (`#offline-sync-banner`) lengkap dengan tombol **Sinkronkan Sekarang**.
  - Event listener `window.addEventListener("online", syncOfflineAttendanceQueue)` + pemeriksaan saat `initTeacherPortal()` otomatis menyinkronkan setiap item antrean secara berurutan ke server (`POST /api/teacher/classes/{class_id}/attendance/sessions` — jika sesi sudah ada/409, cari sesi yang cocok via `GET` lalu `POST /records`) dan menghapus item yang sukses dari antrean.

### Fitur 3: Pembaruan Template PDF (Hapus Footer)
- **File:** `edutrack/services/report_service.py`
- Pada `_draw_page_chrome(canvas, doc)`:
  - Pertahankan garis aksen top-bar (`#1E3A8A` + `#0284C7`), banner header gelap, kartu KPI, diagram vektor donat/batang, dan tabel rapi.
  - **Hapus seluruh elemen footer** (garis horizontal bawah, teks `"EduTrack — Laporan Akademik Resmi • Dicetak ..."`, dan `"Halaman X"`).

### Fitur 4: Penguatan Keamanan Akun & Sesi
1. **Alur Lupa Kata Sandi dengan Reset via Email (Opsional):**
   - Tambah konfigurasi SMTP opsional di `AppConfig` (`smtp_host`, `smtp_port`, `smtp_username`, `smtp_password`, `smtp_from_email`, `smtp_use_tls`, `app_base_url`) dibaca di `AppConfig.from_env()`.
   - Tambah helper `_send_recovery_email(...)` berbasis `smtplib` + `email.message.EmailMessage` (stdlib Python, 0 dependensi baru) yang dapat diinjeksi (*email_sender* callable) untuk pengujian unit.
   - Endpoint `POST /api/auth/recovery/request` menerima `username` dan `delivery_method: "token" | "email"` (default `"token"` agar kompatibel mundur).
   - Jika `delivery_method == "email"`:
     - Cek email akun terdaftar; jika SMTP terkonfigurasi, kirim email berisi token pemulihan & tautan reset (`{app_base_url}/?recovery_token=...`) dan kembalikan respons tanpa membocorkan token mentah (`delivery_method="email"`, `email_sent=True`, `masked_email`).
     - Jika akun tidak memiliki email atau SMTP belum dikonfigurasi pada server, kembalikan pesan validasi yang jelas dan sarankan opsi token langsung (atau hubungi guru).
   - Di halaman login (`#panel-recovery`), sediakan pilihan metode pemulihan: **Tampilkan Token Langsung** atau **Kirim ke Email Terdaftar**, serta dukungan membaca `?recovery_token=` dari URL secara otomatis.
2. **Manajemen Sesi Aktif & Logout dari Semua Perangkat:**
   - Simpan `user_agent` dan `ip_address` pada `create_session(...)`.
   - `GET /api/auth/sessions`: mengembalikan daftar seluruh sesi aktif (`revoked_at IS NULL AND expires_at > now`) milik pengguna saat ini, menandai `is_current: True` pada sesi yang sedang digunakan, lengkap dengan `device_label` (ringkasan browser/OS dari User-Agent), `ip_address`, `created_at`, dan `last_activity_at`.
   - `DELETE /api/auth/sessions/{session_id}`: mencabut satu sesi aktif milik pengguna sendiri (anti-IDOR: hanya sesi dengan `user_id == current_user.id`).
   - `POST /api/auth/logout-all`: mencabut seluruh sesi aktif pengguna (opsi `keep_current: bool = False`; default `False` agar logout dari semua perangkat termasuk perangkat saat ini, hapus cookie, dan arahkan ke login).
   - UI di `#tab-t-account` (Guru) dan `#stab-s-account` (Siswa): panel **Sesi Aktif & Keamanan Perangkat** dengan daftar perangkat, tombol **Cabut** per sesi, dan tombol **Keluar dari Semua Perangkat**.
3. **Pembatasan Laju (Rate Limiting) pada Endpoint Login:**
   - Tambah konfigurasi di `AppConfig`: `login_rate_limit_max_attempts: int = 5`, `login_rate_limit_window_seconds: int = 300` (5 percobaan gagal per 5 menit per kombinasi IP / username).
   - Tambah `RateLimitError(DomainError)` dengan `http_status = 429` dan header `Retry-After`.
   - Sebelum verifikasi password di `POST /api/auth/login`, cek jumlah percobaan gagal dalam jendela waktu di tabel `login_rate_limits` (berbasis DB sehingga konsisten di Vercel serverless!).
   - Jika gagal login: catat ke `login_rate_limits`. Jika login berhasil: bersihkan catatan gagal untuk `user:<username>` agar pengguna sah tidak terblokir. Jika melewati batas: kembalikan HTTP **429 Too Many Requests** dengan `Retry-After` dan pesan informatif.

### Fitur 5: Sistem Peringatan Dini (Early Warning System / EWS)
- **Konfigurasi (`AppConfig`):** `ews_alpa_threshold: int = 3` (ambang batas default `alpa >= 3` atau dapat disesuaikan lewat parameter query `alpa_threshold`).
- **Arsitektur (`edutrack/services/analytics_service.py` + `edutrack/services/attendance_service.py`):**
  - Tambah helper `get_student_alpa_counts(teacher, class_id)` pada `AttendanceService` (memakai data kehadiran riil per kelas).
  - Tambah metode `get_early_warning_report(teacher, class_id=None, period_id=None, alpa_threshold=None)` pada `AnalyticsService` yang mengombinasikan data nilai (`final_score` vs `classroom.mastery_threshold` / KKM) dan data `alpa` dari kehadiran:
    - **Trigger Akademik (`below_kkm`):** `final_score is not None and final_score < classroom.mastery_threshold`.
    - **Trigger Kehadiran (`alpa_exceeded`):** `alpa_count >= threshold` (default `3`, atau persentase absen tinggi jika diperlukan tetap terpisah jelas sebagai `alpa_count`).
    - **Tingkat Keparahan:** `kritis` (kedua kondisi terpenuhi), `perhatian` (salah satu kondisi terpenuhi).
    - Kembalikan ringkasan (`total_flagged`, `critical_count`, `warning_count`, `alpa_threshold`) dan daftar terurut (`kritis` dulu, lalu `alpa_count` tertinggi / nilai terendah) berisi `student_id`, `student_code`, `full_name`, `class_id`, `class_name`, `final_score`, `kkm`, `alpa_count`, `severity`, `triggers`, dan `reasons`.
- **API (`edutrack/web/api.py`):**
  - `GET /api/teacher/early-warning?class_id=...&alpa_threshold=...`
  - Juga disinkronkan pada respons `GET /api/teacher/dashboard` (`early_warning`) agar langsung tampil di Dashboard Guru.
- **UI (`index.html`, `app.js`):**
  - Kartu **Sistem Peringatan Dini (Early Warning System)** pada `#tab-t-dashboard` dengan filter ambang `alpa`, ringkasan jumlah siswa `Kritis` & `Perhatian`, badge pemicu (`Nilai < KKM`, `Alpa ≥ N`), dan tombol cepat unduh PDF individu siswa.

---

## 4. Target Scope & File Boundary
File yang diizinkan untuk dibuat/diubah pada Fase Implementasi:
- `edutrack/configs/app_config.py`
- `edutrack/domain/errors.py`
- `edutrack/domain/models.py`
- `edutrack/repositories/database.py`
- `edutrack/repositories/user_repo.py`
- `edutrack/repositories/academic_repo.py`
- `edutrack/services/auth_service.py`
- `edutrack/services/classroom_service.py`
- `edutrack/services/attendance_service.py`
- `edutrack/services/analytics_service.py`
- `edutrack/services/report_service.py`
- `edutrack/web/api.py`
- `edutrack/web/static/manifest.json` (baru)
- `edutrack/web/static/sw.js` (baru)
- `edutrack/web/static/icon.svg` (baru)
- `edutrack/web/static/index.html`
- `edutrack/web/static/styles.css`
- `edutrack/web/static/app.js`
- `edutrack/tests/egm_v6_features_test.py` (baru)
