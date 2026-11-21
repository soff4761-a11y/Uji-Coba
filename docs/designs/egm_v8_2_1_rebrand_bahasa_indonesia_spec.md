# Spesifikasi Desain Teknis v8.2.1 — Penggantian Identitas Terlihat Pengguna ke "Bahasa Indonesia" & Pembaruan Ikon PWA (EGM)

- **Status:** Disetujui (`resolved` pasca tinjauan Goldfish — siap Fase 5)
- **Baseline:** `uji-coba-v8.2-fixed.zip`
- **Tanggal:** 2026-11-21
- **Batas Semantik Dokumen:**
  - `FeatureRange`: Bagian 1 sampai Bagian 4 (Arsitektur, Ruang Lingkup, Desain, Risiko & Alternatif)
  - `DetailedRange`: Bagian 5 sampai Bagian 7 (Target Scope & File Boundary, Rencana Implementasi Zero-Decision, Rencana Pengujian & Fase)

---

## 1. Overview & Problem Statement

### 1.1 Ringkasan
Spesifikasi ini menetapkan perubahan identitas aplikasi yang terlihat oleh pengguna akhir dari **EduTrack** menjadi **Bahasa Indonesia**, beserta pembaruan ikon Progressive Web App (PWA) dari siluet huruf **E** menjadi monogram vektor **BI** pada codebase baseline `uji-coba-v8.2-fixed.zip`.

### 1.2 Pernyataan Masalah
Saat ini, aplikasi web administrasi pembelajaran menampilkan merek **EduTrack** pada antarmuka web (tab browser, halaman login, halaman aktivasi akun, sidebar guru, sidebar siswa, dan topbar siswa sebelum ditimpa nama siswa saat runtime), metadata instalasi PWA (`manifest.json`), ikon aplikasi (`icon.svg` berbentuk huruf **E**), tajuk template impor nilai Excel (`grade_service.py`), badge default laporan PDF (`report_service.py`), serta judul aplikasi FastAPI dan respons JSON fallback saat `index.html` tidak ditemukan (`api.py`). Pemilik proyek menginginkan seluruh permukaan yang terlihat oleh pengguna tampil dengan nama **Bahasa Indonesia** tanpa mengubah infrastruktur teknis internal yang sedang berjalan di produksi.

---

## 2. Goals & Non-Goals

### 2.1 Goals (Masuk Cakupan)
1. Mengganti seluruh kemunculan tulisan `EduTrack` / `EDUTRACK` yang terlihat oleh pengguna akhir menjadi **Bahasa Indonesia** / **BAHASA INDONESIA** pada `index.html`, `manifest.json`, template impor Excel (`grade_service.py`), badge default PDF (`report_service.py`), serta judul dan respons fallback FastAPI (`api.py`).
2. Memperbarui `edutrack/web/static/icon.svg` dari siluet huruf **E** menjadi monogram vektor **BI** yang simetris, memiliki celah antar-elemen yang jelas, konsisten dengan palet gradien aplikasi, dan berada 100% di dalam lingkaran aman *maskable icon* W3C (diameter 80% / radius 204,8 unit dari pusat kanvas 512×512).
3. Memastikan browser dan instalasi PWA menarik metadata dan aset terbaru dengan menaikkan `CACHE_NAME` Service Worker (`sw.js`) ke `"edutrack-shell-v8.2.1"` serta menambahkan `/manifest.json` ke middleware `Cache-Control: no-cache, must-revalidate` di `api.py`.
4. Memperbarui asersi lama di `edutrack/tests/database_pg_test.py` dan menambahkan uji regresi lengkap di `edutrack/tests/egm_v8_2_1_rebrand_test.py` (mencakup permukaan UI, manifest, SVG, Excel, PDF, fallback API, SW cache, serta invarian konfigurasi internal).

### 2.2 Non-Goals (Di Luar Cakupan)
1. **Tidak mengubah identifier internal & konfigurasi runtime**:
   - Variabel lingkungan `EDUTRACK_*` (`.env.example`, `app_config.py`, `main.py`).
   - Nama cookie autentikasi dan CSRF (`edutrack_session`, `edutrack_csrf`) di `app_config.py` dan `js/api.js`.
   - Kunci `localStorage` (`edutrack_theme`, `edutrack_sidebar_collapsed`, `edutrack_student_sidebar_collapsed`, `edutrack_offline_u*`) di `app.js`, `js/state.js`, `js/teacher.js`.
   - Nama berkas default database/backup (`edutrack_data.db`, `edutrack_backups/`) dan `ContextVar("edutrack_pg_req_holder")` di `database.py`.
2. **Tidak mengubah struktur paket Python & konfigurasi deploy**: folder `edutrack/`, seluruh pernyataan `import edutrack...`, `api/index.py`, dan `vercel.json`.
3. **Tidak mengubah dokumentasi internal, CLI, & komentar kode**: `README.md`, `edutrack/README.md`, deskripsi CLI `argparse` di `edutrack/main.py`, arsip desain historis di `docs/designs/egm_v2..v8_2*.md`, docstring Python, maupun komentar header JS/SW.
4. **Tidak mengubah `styles.css` maupun query string `?v=20261120-v8.2`** pada aset JS/CSS (`app.js`, `styles.css`, `js/*.js`) karena berkas JS/CSS tersebut tidak dimodifikasi; perubahan aset statis hanya terjadi pada `index.html`, `manifest.json`, dan `icon.svg`.

---

## 3. High-Level Architecture & Surface Mapping

Perubahan bersifat murni presentasional pada lapisan tepi (edge presentation layer) tanpa mengubah skema basis data, kontrak endpoint REST, alur autentikasi/CSRF, maupun logika perhitungan nilai/kehadiran. Audit menyeluruh terhadap seluruh codebase mengonfirmasi tidak ada string `EduTrack`/`EDUTRACK` terlihat pengguna di `app.js`, `js/*.js`, `styles.css`, header `Content-Disposition` unduhan, maupun *caller* `_render_pdf` (seluruh *caller* di `ReportService` sudah meneruskan `badge_text` berbahasa Indonesia: `"LAPORAN NILAI KELAS"`, `"REKAP KEHADIRAN"`, `"LAPORAN INDIVIDU"`).

### 3.1 Pemetaan Permukaan Terlihat Pengguna

| Permukaan / Berkas | Elemen / Peran | Teks Baru (Final) |
| :--- | :--- | :--- |
| `edutrack/web/static/index.html` | Judul tab (`<title>`), nama aplikasi di kartu Login & Aktivasi Akun, judul brand Sidebar Guru & Siswa, serta nilai awal `#st-header-name` (yang akan ditimpa nama siswa saat runtime oleh `student.js`) | `Bahasa Indonesia — Login &amp; Portal Pembelajaran` (tab) dan `Bahasa Indonesia` (5 elemen brand) |
| `edutrack/web/static/manifest.json` | `name`, `short_name`, dan `description` PWA | `"Bahasa Indonesia — Portal Pembelajaran"`, `"Bahasa Indonesia"`, `"Aplikasi administrasi nilai, kehadiran offline, dan pengumuman kelas Bahasa Indonesia."` |
| `edutrack/services/grade_service.py` | Tajuk baris pertama (`A1`) template impor nilai Excel | `"TEMPLATE IMPOR NILAI PESERTA DIDIK — BAHASA INDONESIA"` |
| `edutrack/services/report_service.py` | Nilai parameter default `badge_text` pada `_render_pdf` | `"BAHASA INDONESIA • LAPORAN"` |
| `edutrack/web/api.py` | Judul aplikasi FastAPI (`title`) & pesan JSON fallback `serve_index` (hanya dikembalikan bila berkas `index.html` tidak ditemukan di disk) | `"Bahasa Indonesia — Sistem Administrasi Pembelajaran"` dan `"Bahasa Indonesia API aktif."` |

### 3.2 Desain Ikon PWA (`edutrack/web/static/icon.svg`)
- Mempertahankan kanvas `viewBox="0 0 512 512"`, latar belakang persegi membulat `rx="112"` (konsisten dengan baseline v8.2 agar tampilan favicon tab browser tetap membulat elegan; keterbatasan *maskable* pada peluncur kotak tajam diterima sebagai trade-off baseline agar tidak menambah berkas ikon kedua), dan gradien `#0f172a` -> `#1e3a8a` -> `#0284c7`.
- Mengganti siluet huruf **E** menjadi monogram vektor murni (`<path>` dan `<rect>`, tanpa `<text>` agar tidak bergantung pada font OS) yang menampilkan huruf **B** dan **I** (`#f8fafc`) beserta titik aksen hijau zamrud (`#34d399`), terpusat tepat pada `(256, 256)` dengan celah 32 px (**B**–**I**) dan 22 px (**I**–titik). Seluruh titik terluar berada di dalam lingkaran aman *maskable* W3C (`r = 204,8` unit dari pusat `(256, 256)`).

### 3.3 Failure Modes, Security & Operational Risks
1. **Stale PWA & HTTP Cache**: Browser atau edge CDN dapat menahan `index.html`, `manifest.json`, dan `icon.svg` versi `v8.2`.
   - *Mitigasi*: Menaikkan `CACHE_NAME` di `sw.js` ke `"edutrack-shell-v8.2.1"` (memanfaatkan `skipWaiting()`, `clients.claim()`, dan pembersihan cache lama di event `activate` yang sudah ada) serta menambahkan `path == "/manifest.json"` ke middleware `add_security_headers` di `api.py` agar `/manifest.json` menerima `Cache-Control: no-cache, must-revalidate`.
   - *Keterbatasan Platform yang Diterima*: Untuk PWA yang sudah terpasang di layar beranda Android/iOS, propagasi ikon/nama shortcut mengikuti jadwal penyegaran berkala OS/browser masing-masing.
2. **Regresi Pengujian Eksisting**: `edutrack/tests/database_pg_test.py` memeriksa keberadaan teks merek di respons `GET /`.
   - *Mitigasi*: Memperbarui asersi ke `"Bahasa Indonesia"` dan menambahkan asersi negatif terhadap `"EduTrack"`.
3. **Risiko Keamanan & Kompatibilitas Sesi**: Tidak ada perubahan pada cookie `edutrack_session`/`edutrack_csrf`, header `X-CSRF-Token`, maupun `localStorage`, sehingga sesi aktif dan antrean absensi offline tetap utuh.
4. **Rollback**: Mengembalikan 8 berkas eksisting yang dimodifikasi dan menghapus 1 berkas uji baru (`edutrack/tests/egm_v8_2_1_rebrand_test.py`) tanpa migrasi database.

---

## 4. Alternatives Considered

1. **Alternatif A — Rebranding Total Hingga Lapisan Internal (`edutrack/` -> `bahasa_indonesia/`, env `BAHASA_INDONESIA_*`, cookie & `localStorage` baru):**
   - *Alasan Ditolak*: Menyentuh >200 titik kode termasuk 134 baris import, `vercel.json`, dan environment variables Vercel; berisiko memutus sesi aktif, menghilangkan antrean absensi offline, dan di luar batasan pemilik proyek.
2. **Alternatif B — Menggunakan Elemen `<text>BI</text>` di `icon.svg`:**
   - *Alasan Ditolak*: Bergantung pada ketersediaan font OS/browser sehingga posisi dan proporsi huruf dapat bergeser atau terpotong saat dipakai sebagai ikon PWA.
3. **Alternatif C — Mempersingkat `"short_name"` di `manifest.json` Menjadi `"B. Indonesia"` (<= 12 Karakter):**
   - *Alasan Ditolak (Trade-off Diterima)*: Meski `"Bahasa Indonesia"` (16 karakter) berpotensi disingkat dengan elipsis oleh beberapa peluncur ponsel, pemilik proyek menetapkan nama aplikasi secara eksplisit sebagai `"Bahasa Indonesia"` demi konsistensi merek penuh.

---

## 5. Target Scope & File Boundary (Allowlist Fase 5)

Hanya berkas berikut yang diizinkan diubah atau dibuat pada Fase 5:

### Berkas yang Diubah (8 berkas)
1. `edutrack/web/static/index.html`
2. `edutrack/web/static/manifest.json`
3. `edutrack/web/static/icon.svg`
4. `edutrack/web/static/sw.js`
5. `edutrack/services/grade_service.py`
6. `edutrack/services/report_service.py`
7. `edutrack/web/api.py`
8. `edutrack/tests/database_pg_test.py`

### Berkas Baru (1 berkas)
9. `edutrack/tests/egm_v8_2_1_rebrand_test.py`

*(Total 8 berkas diubah + 1 berkas uji baru)*

---

## 6. Actionable Steps (Zero-Decision Implementation Plan)

### Langkah 1 — Pembaruan Antarmuka Web & PWA
1. **`edutrack/web/static/index.html`**:
   - Baris 6: `<title>EduTrack — Login &amp; Portal Pembelajaran</title>` -> `<title>Bahasa Indonesia — Login &amp; Portal Pembelajaran</title>`.
   - Baris 30 & 67: `<p class="auth-app-name">EduTrack</p>` -> `<p class="auth-app-name">Bahasa Indonesia</p>`.
   - Baris 92 & 622: `<strong>EduTrack</strong>` -> `<strong>Bahasa Indonesia</strong>`.
   - Baris 673: `<h2 id="st-header-name">EduTrack</h2>` -> `<h2 id="st-header-name">Bahasa Indonesia</h2>`.
2. **`edutrack/web/static/manifest.json`**:
   - `"name"`: `"Bahasa Indonesia — Portal Pembelajaran"`
   - `"short_name"`: `"Bahasa Indonesia"`
   - `"description"`: `"Aplikasi administrasi nilai, kehadiran offline, dan pengumuman kelas Bahasa Indonesia."`
3. **`edutrack/web/static/icon.svg`**:
   - Ganti seluruh isi dengan SVG vektor monogram **BI** terpusat di `(256, 256)` (`x: 102..410`, `y: 148..364`; jarak terjauh dari pusat = `188.1 < 204.8`):
     ```xml
     <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
       <defs>
         <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
           <stop offset="0%" stop-color="#0f172a"/>
           <stop offset="55%" stop-color="#1e3a8a"/>
           <stop offset="100%" stop-color="#0284c7"/>
         </linearGradient>
       </defs>
       <rect width="512" height="512" rx="112" fill="url(#bg)"/>
       <!-- Huruf B (x: 102..266, y: 148..364) -->
       <path fill="#f8fafc" fill-rule="evenodd" d="M102 148h90c42 0 66 22 66 54 0 22-11 38-31 46 25 7 39 25 39 54 0 38-28 62-72 62H102V148zm44 36v46h42c18 0 28-8 28-23s-10-23-28-23h-42zm0 82v60h46c20 0 31-10 31-30s-11-30-31-30h-46z"/>
       <!-- Huruf I (x: 298..344, y: 148..364; celah 32px dari B) -->
       <rect x="298" y="148" width="46" height="216" rx="10" fill="#f8fafc"/>
       <!-- Aksen titik hijau zamrud (x: 366..410, y: 320..364; celah 22px dari I) -->
       <circle cx="388" cy="342" r="22" fill="#34d399"/>
     </svg>
     ```
4. **`edutrack/web/static/sw.js`**:
   - Baris 2: `const CACHE_NAME = "edutrack-shell-v8.2";` -> `const CACHE_NAME = "edutrack-shell-v8.2.1";`.

### Langkah 2 — Pembaruan Ekspor Excel, PDF & API
5. **`edutrack/services/grade_service.py`**:
   - Baris 447: `ws.append(["TEMPLATE IMPOR NILAI PESERTA DIDIK — EDUTRACK"])` -> `ws.append(["TEMPLATE IMPOR NILAI PESERTA DIDIK — BAHASA INDONESIA"])`.
6. **`edutrack/services/report_service.py`**:
   - Baris 553: `badge_text: str = "EDUTRACK • LAPORAN",` -> `badge_text: str = "BAHASA INDONESIA • LAPORAN",`.
7. **`edutrack/web/api.py`**:
   - Baris 303: `app = FastAPI(title="EduTrack — Sistem Administrasi Pembelajaran", version="1.0.0")` -> `app = FastAPI(title="Bahasa Indonesia — Sistem Administrasi Pembelajaran", version="1.0.0")`.
   - Middleware `add_security_headers` (sekitar baris 328–335): tambahkan `path == "/manifest.json"` ke cabang `Cache-Control: no-cache, must-revalidate`.
   - Baris 435: `return JSONResponse({"status": "ok", "message": "EduTrack API aktif."})` -> `return JSONResponse({"status": "ok", "message": "Bahasa Indonesia API aktif."})`.

### Langkah 3 — Pembaruan & Penambahan Pengujian Otomatis
8. **`edutrack/tests/database_pg_test.py`**:
   - Baris 131: ubah `self.assertIn("EduTrack", res_home.text)` -> `self.assertIn("Bahasa Indonesia", res_home.text)` dan tambahkan `self.assertNotIn("EduTrack", res_home.text)`.
9. **`edutrack/tests/egm_v8_2_1_rebrand_test.py`** (baru, menggunakan `tempfile.TemporaryDirectory()` + `AppConfig(db_path=..., backup_dir=...)` agar 100% terisolasi dari DB lokal):
   - **UI & Manifest & Cache-Control**:
     - `GET /` -> status 200, berisi `"Bahasa Indonesia"` pada `<title>`, `.auth-app-name`, sidebar, `#st-header-name`, dan 0 kemunculan `"edutrack"` (case-insensitive).
     - `GET /manifest.json` -> status 200, header `Cache-Control` mengandung `no-cache`, JSON valid dengan `name`, `short_name`, `description` berisi `"Bahasa Indonesia"`, dan 0 kemunculan `"edutrack"` (case-insensitive).
   - **Ikon SVG (`GET /static/icon.svg`)**:
     - Valid XML (`xml.etree.ElementTree.fromstring`), `viewBox == "0 0 512 512"`, tanpa elemen `<text>`, memuat `<path>` (B), `<rect x="298" ...>` (I), dan `<circle cx="388" ...>` (titik aksen).
   - **Service Worker (`GET /sw.js`)**:
     - Status 200, tidak lagi memakai `"edutrack-shell-v8.2"`, dan memakai pola versi `edutrack-shell-v8.2.1`.
   - **API Title & Fallback Edge Case**:
     - `app.title == "Bahasa Indonesia — Sistem Administrasi Pembelajaran"`.
     - Cabang fallback `serve_index` saat `index.html` tidak ditemukan (menggunakan `unittest.mock.patch.object(Path, "exists", return_value=False)` pada path index) mengembalikan `{"status": "ok", "message": "Bahasa Indonesia API aktif."}`.
   - **Ekspor Excel & PDF**:
     - Setup `AppContainer` + `seed_initial_data` di DB sementara -> panggil `container.grade_service.generate_grade_import_template(teacher, assessment_id)` -> baca dengan `openpyxl.load_workbook(io.BytesIO(data))` -> verifikasi `ws["A1"].value == "TEMPLATE IMPOR NILAI PESERTA DIDIK — BAHASA INDONESIA"`.
     - Verifikasi `inspect.signature(_render_pdf).parameters["badge_text"].default == "BAHASA INDONESIA • LAPORAN"` dan pemanggilan `_render_pdf("Judul", "Sub", ["Kolom"], [["Isi"]])` mengembalikan bytes yang diawali `b"%PDF"`.
   - **Invarian Internal**:
     - `AppConfig().cookie_name == "edutrack_session"`, `AppConfig().csrf_cookie_name == "edutrack_csrf"`, `AppConfig().db_path == "edutrack_data.db"`.

---

## 7. Test Plan, Phasing & Checkpoints

### Fase Inkremental
- **Fase A (Statis & PWA):** Perbarui `index.html`, `manifest.json`, `icon.svg`, `sw.js`. Validasi sintaks JS, JSON, dan XML.
- **Fase B (Backend & Ekspor):** Perbarui `grade_service.py`, `report_service.py`, `api.py`.
- **Fase C (Pengujian & Verifikasi Penuh):** Perbarui `database_pg_test.py`, buat `egm_v8_2_1_rebrand_test.py`, jalankan seluruh test suite dan audit grep.

### Perintah Verifikasi Wajib
1. `node --check edutrack/web/static/sw.js`
2. `python3 -c 'import json, xml.etree.ElementTree as ET; json.load(open("edutrack/web/static/manifest.json")); ET.parse("edutrack/web/static/icon.svg"); print("JSON & SVG OK")'`
3. `! grep -in "edutrack" edutrack/web/static/index.html edutrack/web/static/manifest.json`
4. `python3 -m unittest discover -s edutrack/tests -p "*_test.py" -v`
5. `python3 -O -m unittest edutrack/tests/egm_v8_2_1_rebrand_test.py -v`
