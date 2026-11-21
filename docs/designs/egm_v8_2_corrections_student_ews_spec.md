# Spesifikasi Desain EduTrack v8.2 — Perbaikan Penerimaan Koreksi Guru & Pop-up EWS Dashboard Siswa

- **Dokumen:** `docs/designs/egm_v8_2_corrections_student_ews_spec.md`
- **Status:** Draft untuk Review Goldfish
- **Tanggal:** 2026-11-20
- **Metodologi:** Elephant-Goldfish Model (EGM) + App Code Craft (Modular, Contract-First, Test-Driven)
- **Cakupan Semantik:**
  - `FeatureRange`: Bagian 1–4 (Overview & Akar Masalah, Goals/Non-Goals, Kontrak & Dekomposisi Modular, Risiko & Alternatif)
  - `DetailedRange`: Bagian 5–7 (`Target Scope & File Boundary`, Rencana Implementasi Rinci, Rencana Pengujian 3-Kategori)

---

## 1. Overview & Problem Statement

Ditemukan satu bug operasional pada alur permintaan koreksi siswa -> guru dan satu kebutuhan fitur baru pada dashboard siswa:

1. **Bug: Permintaan Koreksi Siswa Tidak Tampil di Dashboard Guru (`edutrack/web/static/js/teacher.js:690–735`)**:
   - Siswa berhasil mengirim permintaan koreksi melalui `POST /api/student/corrections` dan melihatnya di dashboard siswa (`GET /api/student/corrections`), serta angka `pending_corrections` bertambah di KPI guru.
   - Namun, ketika guru membuka tab **Laporan & Koreksi (`t-reports`)**, fungsi `loadReportsAndAuditTab()` menjalankan:
     ```js
     const [corrRes, auditRes, bakRes] = await Promise.all([
       api("/api/teacher/corrections"),
       api("/api/teacher/audit-logs?limit=40"),
       api("/api/teacher/backups"),
     ]);
     ```
   - Karena sejak v7 endpoint `GET /api/teacher/backups` dibatasi khusus `Role.ADMIN` (mengembalikan HTTP `403 Forbidden` bagi guru biasa), `Promise.all` langsung *reject* sebelum baris render `#t-corrections-tbody` dan `#t-audit-tbody` sempat dieksekusi. Akibatnya seluruh permintaan koreksi siswa tidak pernah tampil pada portal guru.
   - Selain itu, `window.resolveCorrection` belum memiliki blok `try/catch` dan belum menyegarkan `loadTeacherDashboard()` setelah menanggapi koreksi.

2. **Fitur Baru: Pop-up Peringatan EWS Auto-Dismiss 3 Detik di Dashboard Siswa (`analytics_service.py`, `student.js`, `styles.css`)**:
   - Ketika siswa membuka dashboard dan status akademiknya telah melewati ambang batas Early Warning System (EWS) — yaitu nilai akhir `< KKM` kelas dan/atau jumlah alpa `>= ews_alpa_threshold` — sistem harus menampilkan **pop-up peringatan** yang **otomatis hilang setelah 3 detik (`3000 ms`)**.

---

## 2. Goals & Non-Goals

### Goals
- Memastikan guru (`Role.TEACHER`) maupun admin (`Role.ADMIN`) selalu melihat seluruh permintaan koreksi siswa pada tab Laporan & Koreksi secara andal tanpa terhalang pembatasan akses backup admin.
- Memisahkan tanggung jawab evaluasi EWS siswa menjadi fungsi murni yang teruji (*contract-first*) di lapisan layanan/domain, konsisten 100% dengan ambang EWS guru (`final_score < KKM` dan/atau `alpa_count >= ews_alpa_threshold`).
- Menampilkan pop-up peringatan EWS di dashboard siswa saat batas EWS terlewati, yang hilang otomatis dalam 3 detik (3000 ms), aman terhadap XSS, dan tidak menumpuk jika dipicu ulang.
- Memperbarui cache-bust PWA ke `?v=20261120-v8.2` dan `edutrack-shell-v8.2`.
- Menyertakan unit test berpasangan (*happy path*, *edge/empty*, dan *error/invalid*) di backend Python maupun runtime Node untuk UI pop-up.

### Non-Goals
- Tidak mengubah kebijakan keamanan v7 bahwa backup/restore tetap khusus `Role.ADMIN`.
- Tidak menambah tabel atau migrasi basis data baru.
- Tidak menampilkan pop-up EWS secara berulang-ulang saat siswa mengganti filter materi (`material_id`), agar tidak mengganggu pengalaman membaca.

---

## 3. Kontrak & Dekomposisi Modular (App Code Craft)

### 3.1 Lapisan Backend — Evaluasi EWS Siswa (`edutrack/services/analytics_service.py`)
Tambahkan fungsi/helper murni `evaluate_student_ews(...)` dengan tanda tangan eksplisit:
```python
def evaluate_student_ews(
    final_score: Optional[float],
    mastery_threshold: float,
    alpa_count: int,
    alpa_threshold: int,
) -> Dict[str, Any]:
```
- **Kontrak Input**:
  - `final_score`: `Optional[float]` (skala 0..100, atau `None` jika belum ada nilai terpublikasi).
  - `mastery_threshold`: `float` (KKM kelas, 0..100).
  - `alpa_count`: `int` (`>= 0`).
  - `alpa_threshold`: `int` (`>= 1`).
- **Kontrak Output**:
  - `is_triggered: bool` (`below_kkm or alpa_over`)
  - `severity: str` (`"kritis"` jika keduanya terpicu, `"perhatian"` jika salah satu, `"aman"` jika tidak ada)
  - `kkm: float`, `alpa_threshold: int`, `final_score: Optional[float]`, `alpa_count: int`
  - `triggers: List[str]` (`"below_kkm"`, `"alpa_exceeded"`)
  - `reasons: List[str]` (kalimat alasan ringkas dalam bahasa Indonesia)
  - `message: str` (ringkasan satu kalimat siap tampil di pop-up, kosong `""` jika `is_triggered == False`)
- **Integrasi ke `_build_student_analytics(...)`**:
  - Kembalikan kunci baru `"early_warning"` di dalam dict respons `GET /api/student/dashboard`.
  - Ketika `material_id is not None`, evaluasi EWS tetap memakai data yang sedang dihitung pada `_build_student_analytics` atau (lebih akurat!) jika `material_id is not None`, frontend hanya memicu pop-up saat `material_id` kosong (tampilan awal dashboard keseluruhan).

### 3.2 Lapisan Frontend Guru — Isolasi Pemuatan Koreksi, Audit, & Backup (`edutrack/web/static/js/teacher.js`)
- Refaktor `loadReportsAndAuditTab()` agar memisahkan tiga pemanggilan API secara independen:
  1. **Koreksi (`/api/teacher/corrections`)**: dimuat di blok `try/catch` sendiri. Jika gagal, tampilkan baris galat pada `#t-corrections-tbody` dan `toast(err.message, true)`.
  2. **Audit Log (`/api/teacher/audit-logs?limit=40`)**: dimuat di blok `try/catch` sendiri. Jika gagal, tampilkan baris galat pada `#t-audit-tbody`.
  3. **Backup (`/api/teacher/backups`)**: hanya dipanggil apabila `state.user?.role === "admin"`. Jika bukan admin, tampilkan keterangan informatif di `#backup-list`: `"Fitur cadangan & pemulihan basis data hanya tersedia untuk akun Admin."` tanpa memanggil endpoint 403.
- Di `window.resolveCorrection(id, status)`: bungkus dalam `try/catch`, tampilkan `toast` galat bila gagal, dan panggil `await Promise.all([loadReportsAndAuditTab(), loadTeacherDashboard()])` agar KPI `pending_corrections` langsung diperbarui.

### 3.3 Lapisan Frontend Siswa — Pop-up EWS Auto-Dismiss 3 Detik (`edutrack/web/static/js/student.js`, `styles.css`)
- Tambahkan fungsi modular yang diekspor `export function showStudentEwsPopup(ews, durationMs = 3000)`:
  - **Kontrak Input**:
    - `ews`: objek `data.early_warning` (atau `null`/`undefined`).
    - `durationMs`: `number` (baku `3000` ms).
  - **Perilaku**:
    - Jika `!ews || !ews.is_triggered`, langsung kembalikan `null` tanpa memodifikasi DOM.
    - Bersihkan timer aktif sebelumnya (`clearTimeout`) dan hapus elemen `#student-ews-popup` lama jika masih ada (cegah tumpukan).
    - Buat elemen `<div id="student-ews-popup" class="ews-popup ews-popup--{kritis|perhatian}" role="alert" aria-live="assertive">` dan tempelkan ke `document.body`.
    - Isi konten memakai `escapeHtml(...)` pada seluruh field (`title`, `reasons`, `message`) agar 100% bebas XSS.
    - Jadwalkan `setTimeout(() => { el.remove(); ... }, durationMs)` tepat `3000` ms agar pop-up hilang otomatis.
    - Klik pada pop-up juga dapat menutupnya lebih awal sambil membersihkan timer.
    - Kembalikan referensi elemen `el`.
- Di `initStudentPortal(materialId = null)`:
  - Panggil `if (!hasMat && data.early_warning?.is_triggered) { showStudentEwsPopup(data.early_warning, 3000); }` setelah render dashboard siswa.

---

## 4. Risiko & Alternatif yang Dipertimbangkan

- **Alternatif untuk Koreksi Guru**: Membuka akses `GET /api/teacher/backups` bagi guru biasa -> **Ditolak** karena melanggar keputusan hardening keamanan v7 (backup hanya untuk Admin). Memisahkan pemuatan API di `loadReportsAndAuditTab()` menyelesaikan akar masalah tanpa melemahkan keamanan.
- **Alternatif untuk Pop-up EWS Siswa**: Memakai `toast()` biasa (durasi 4200 ms, warna merah generik) -> **Ditolak** karena pengguna meminta pop-up peringatan khusus yang hilang otomatis tepat dalam **3 detik** dan tampil jelas sebagai peringatan EWS (bukan sekadar toast error API).
- **Risiko Cache PWA**: Diatasi dengan menaikkan cache-bust ke `?v=20261120-v8.2` dan `CACHE_NAME = "edutrack-shell-v8.2"`.

---

## 5. Target Scope & File Boundary

### File yang Diubah
1. `edutrack/services/analytics_service.py` (`evaluate_student_ews` + `"early_warning"` di `_build_student_analytics`)
2. `edutrack/web/static/js/teacher.js` (isolasi `loadReportsAndAuditTab`, `try/catch` `resolveCorrection`, cache-bust `?v=20261120-v8.2`)
3. `edutrack/web/static/js/student.js` (`export function showStudentEwsPopup`, pemanggilan di `initStudentPortal`, cache-bust `?v=20261120-v8.2`)
4. `edutrack/web/static/styles.css` (gaya `.ews-popup`, `.ews-popup--kritis`, `.ews-popup--perhatian`)
5. `edutrack/web/static/app.js` (cache-bust `?v=20261120-v8.2`)
6. `edutrack/web/static/index.html` (cache-bust `?v=20261120-v8.2`)
7. `edutrack/web/static/sw.js` (`CACHE_NAME = "edutrack-shell-v8.2"` & `?v=20261120-v8.2`)
8. `edutrack/web/static/js/api.js` (cache-bust `?v=20261120-v8.2`)
9. `edutrack/web/static/js/charts.js` (cache-bust `?v=20261120-v8.2`)
10. `edutrack/tests/egm_v8_bugfix_test.py` (perbarui cek cache-bust v8.2)

### File Baru
11. `edutrack/tests/egm_v8_2_corrections_ews_test.py` (test suite khusus v8.2: happy path, edge/empty, error/invalid + uji runtime Node pop-up 3 detik)
12. `docs/designs/egm_v8_2_corrections_ews_spec.md` (atau `egm_v8_2_corrections_student_ews_spec.md` ini)
13. `docs/designs/goldfish_review_report_v8_2.md`

---

## 6. Detailed Implementation Plan

1. **`edutrack/services/analytics_service.py`**:
   - Tambahkan fungsi tingkat modul `evaluate_student_ews(final_score, mastery_threshold, alpa_count, alpa_threshold) -> Dict[str, Any]` dengan Google docstring & validasi `alpa_threshold < 1` -> `ValidationError`, `alpa_count < 0` -> `ValidationError`.
   - Di `_build_student_analytics(...)`: hitung `early_warning = evaluate_student_ews(final_score, classroom.mastery_threshold, att_summary.alpa, self._config.ews_alpa_threshold)` dan sertakan pada dict return.
2. **`edutrack/web/static/js/teacher.js`**:
   - Ubah `loadReportsAndAuditTab()` menjadi 3 blok `try/catch` terpisah (koreksi, audit log, dan backup khusus `state.user?.role === "admin"`).
   - Ubah `window.resolveCorrection` agar dibungkus `try/catch`, membatalkan jika `prompt` dibatalkan (`response === null`), dan memperbarui `loadReportsAndAuditTab()` + `loadTeacherDashboard()`.
3. **`edutrack/web/static/js/student.js` & `styles.css`**:
   - Tambahkan `export function showStudentEwsPopup(ews, durationMs = 3000)` dengan timer module-level `let ewsPopupTimer = null;`, escaping XSS via `escapeHtml`, klik-tutup, dan auto-remove tepat setelah `durationMs` (3000 ms).
   - Panggil `showStudentEwsPopup(data.early_warning, 3000)` di `initStudentPortal` saat `!hasMat && data.early_warning?.is_triggered`.
   - Tambahkan blok CSS `.ews-popup` di akhir `styles.css`.
4. **Cache-bust v8.2**:
   - Perbarui seluruh `?v=20261120-v8.1` -> `?v=20261120-v8.2` dan `edutrack-shell-v8.1` -> `edutrack-shell-v8.2` di 7 file statis (`index.html`, `sw.js`, `app.js`, `js/api.js`, `js/charts.js`, `js/student.js`, `js/teacher.js`) serta perbarui pola regex di `egm_v8_bugfix_test.py`.

---

## 7. Test Plan (3 Kategori App Code Craft)

Tambahkan `edutrack/tests/egm_v8_2_corrections_ews_test.py`:
1. **Happy Path**:
   - Siswa mengirim permintaan koreksi (`POST /api/student/corrections`) -> Guru (`Role.TEACHER`, bukan admin) memanggil `GET /api/teacher/corrections` dan menerima pesan koreksi siswa tersebut secara lengkap; verifikasi pula `teacher.js` tidak menggabungkan `/api/teacher/backups` dalam satu `Promise.all` dengan `/api/teacher/corrections` dan hanya memanggil `/api/teacher/backups` untuk role `"admin"`.
   - Siswa dengan nilai `< KKM` dan/atau `alpa >= 3` memanggil `GET /api/student/dashboard` -> `early_warning.is_triggered == True`, `severity` tepat (`"perhatian"` / `"kritis"`), `triggers` & `reasons` lengkap.
   - Uji runtime Node `showStudentEwsPopup(ews, 3000)`: memastikan elemen `#student-ews-popup` muncul di DOM dengan konten ter-escape, menjadwalkan `setTimeout` dengan durasi tepat `3000` ms, dan elemen terhapus saat callback timer dijalankan.
2. **Edge / Empty Cases**:
   - `evaluate_student_ews(final_score=None, mastery_threshold=75.0, alpa_count=0, alpa_threshold=3)` -> `is_triggered=False`, `severity="aman"`, `reasons=[]`, `message=""`.
   - Nilai tepat sama dengan KKM (`final_score=75.0`, `kkm=75.0`) dan `alpa_count=2` (`< 3`) -> `is_triggered=False`.
   - `showStudentEwsPopup({ is_triggered: false }, 3000)` -> tidak menambahkan elemen ke DOM (`null`).
   - Pemanggilan `showStudentEwsPopup` dua kali berturut-turut -> membersihkan timer & pop-up lama (tidak menumpuk).
   - Karakter XSS (`<script>`) di `reasons`/`message` di-escape dengan aman.
3. **Error / Invalid Cases**:
   - `evaluate_student_ews` dengan `alpa_threshold=0` atau `alpa_count=-1` melempar `ValidationError`.
   - Guru biasa memanggil `GET /api/teacher/backups` tetap mendapat `403`, sementara `GET /api/teacher/corrections` tetap mengembalikan `200` dengan koreksi siswa.

Perintah verifikasi:
- `node --check edutrack/web/static/sw.js && for f in edutrack/web/static/app.js edutrack/web/static/js/*.js; do node --input-type=module --check < "$f"; done`
- `python3 -m unittest discover -s edutrack/tests -p "*_test.py" -v`
- `python3 -O -m unittest edutrack/tests/egm_v8_2_corrections_ews_test.py -v`
