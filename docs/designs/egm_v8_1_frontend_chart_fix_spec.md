# Spesifikasi Desain EduTrack v8.1 — Perbaikan `renderDonutChart is not defined` & Kompatibilitas Grafik Frontend

- **Dokumen:** `docs/designs/egm_v8_1_frontend_chart_fix_spec.md`
- **Status:** Draft untuk Review Goldfish
- **Tanggal:** 2026-11-20
- **Cakupan Semantik:**
  - `FeatureRange`: Bagian 1–4 (Overview, Goals/Non-Goals, Kontrak Perilaku, Risiko & Alternatif)
  - `DetailedRange`: Bagian 5–7 (`Target Scope & File Boundary`, Rencana Implementasi Rinci, Test Plan)

---

## 1. Overview & Problem Statement

Setelah modularisasi ES Modules di v7/v8, saat guru membuka dashboard, browser menampilkan notifikasi galat runtime:

> `renderDonutChart is not defined`

Investigasi terhadap modul frontend (`edutrack/web/static/js/`) menemukan tiga akar masalah terkait pemanggilan grafik & referensi fungsi:
1. **`edutrack/web/static/js/teacher.js:200`**: Modul sudah mengimpor `renderDoughnutChart` dari `./charts.js`, tetapi fungsi `loadTeacherDashboard()` masih memanggil nama fungsi lama `renderDonutChart("chart-t-attendance", att)` yang telah dihapus saat penyatuan komponen donat di v7.
2. **`edutrack/web/static/js/charts.js:137` vs `teacher.js:231`**: `runStudentComparison()` di `teacher.js:231` memanggil `renderLineChart("chart-t-compare", data.series.map(...))` dengan payload **multi-seri** `[{ name, points: [{ label, value }] }]`, sedangkan `renderLineChart(containerId, points)` di `charts.js:137` hanya menerima array **satu seri datar** `[{ label, value }]`. Akibatnya grafik perbandingan siswa selalu menampilkan pesan kosong `"Belum ada nilai yang dapat digambarkan."`.
3. **`edutrack/web/static/js/teacher.js:580, 1400, 1426`**: Pemanggilan `openAttSession(...)` bergantung secara implisit pada properti global `window.openAttSession` di dalam ES module alih-alih deklarasi lokal yang ditautkan eksplisit ke `window`.

---

## 2. Goals & Non-Goals

### Goals
- Menghilangkan galat `ReferenceError: renderDonutChart is not defined` pada dashboard guru dengan memakai komponen tunggal `renderDoughnutChart` dari `js/charts.js`.
- Memastikan `renderLineChart` di `js/charts.js` mendukung payload multi-seri (`[{ name, points: [{ label, value }] }]`) maupun payload datar (`[{ label, value }]`) dengan skala sumbu Y dinamis dan legenda warna.
- Mendeklarasikan `openAttSession` secara eksplisit sebagai fungsi modul di `teacher.js` yang juga diekspos ke `window.openAttSession`.
- Memperbarui cache-bust PWA (`?v=20261120-v8.1` dan `edutrack-shell-v8.1`) agar browser langsung memuat bundel JS yang diperbaiki.
- Menambahkan uji regresi otomatis di `edutrack/tests/egm_v8_bugfix_test.py` untuk mencegah kemunculan ulang pemanggilan `renderDonutChart` dan memverifikasi kompatibilitas multi-seri `renderLineChart`.

### Non-Goals
- Tidak mengubah endpoint API backend maupun skema basis data.
- Tidak menambah pustaka grafik eksternal (tetap memakai SVG ringan native).

---

## 3. Kontrak Perilaku

1. **Diagram Donat Kehadiran Guru (`teacher.js:200`)**:
   - Mengganti `renderDonutChart("chart-t-attendance", att)` dengan:
     ```js
     renderDoughnutChart("chart-t-attendance", {
       centerValue: att.attendance_percentage != null ? `${att.attendance_percentage}%` : "-",
       centerLabel: "Kehadiran",
       centerBadge: att.total_recorded ? `${att.total_recorded} Catatan` : "",
       segments: [
         { label: "Hadir", value: att.hadir || 0, displayValue: `${att.hadir || 0}x`, color: "#34d399" },
         { label: "Sakit", value: att.sakit || 0, displayValue: `${att.sakit || 0}x`, color: "#fbbf24" },
         { label: "Izin", value: att.izin || 0, displayValue: `${att.izin || 0}x`, color: "#38bdf8" },
         { label: "Alpa", value: att.alpa || 0, displayValue: `${att.alpa || 0}x`, color: "#f87171" },
       ],
       emptyMessage: "Belum ada data kehadiran",
     });
     ```
2. **Grafik Garis Multi-Seri & Tunggal (`charts.js:137`)**:
   - `renderLineChart(containerId, data)` mendeteksi bentuk masukan:
     - Jika `Array.isArray(data)` dan elemen pertama memiliki `Array.isArray(data[0]?.points)` -> mode **multi-seri** (`seriesList = data`).
     - Selain itu -> bungkus menjadi 1 seri tunggal `[{ name: "", points: data || [] }]`.
   - Kumpulkan seluruh titik bernilai numerik valid (`value !== null && value !== undefined && Number.isFinite(Number(value))`) lintas semua seri untuk menghitung skala sumbu Y dinamis (`minY`, `maxY`, `rangeY`). Jika tidak ada satu pun titik valid, tampilkan `<p class="muted small">Belum ada nilai yang dapat digambarkan.</p>`.
   - Sumbu X menggunakan daftar label dari seri dengan jumlah titik terbanyak (atau indeks titik terpanjang). Untuk setiap seri, gambar polyline SVG terputus saat ada `null` (`M` pada segmen baru, `L` pada titik berurutan) dengan warna dari `DOUGHNUT_PALETTE[sIdx % DOUGHNUT_PALETTE.length]`, titik lingkaran dengan `<title>` berisi nama seri + label + nilai, serta legenda ringkas di atas/bawah grafik bila `seriesList.length > 1` (atau `name` tidak kosong).
3. **Deklarasi Eksplisit `openAttSession` (`teacher.js`)**:
   - Ubah `window.openAttSession = async (sessionId) => { ... };` menjadi `async function openAttSession(sessionId) { ... }` diikuti `window.openAttSession = openAttSession;`.

---

## 4. Risiko & Alternatif yang Dipertimbangkan

- **Alternatif yang Ditolak**: Menambahkan alias `export function renderDonutChart(...)` di `charts.js`. Ditolak karena melanggar tujuan penyatuan satu komponen donat (`renderDoughnutChart`) di v7 dan menyisakan dua tanda tangan fungsi yang tidak konsisten (`att` mentah vs objek konfigurasi `{ centerValue, segments, ... }`).
- **Risiko Cache Browser/PWA**: Browser mungkin masih mengeksekusi `teacher.js?v=20261120-v8` dari cache Service Worker. Mitigasi: naikkan cache-bust ke `?v=20261120-v8.1` dan `CACHE_NAME = "edutrack-shell-v8.1"` di `sw.js`.

---

## 5. Target Scope & File Boundary

### File yang Diubah
1. `edutrack/web/static/js/teacher.js`
2. `edutrack/web/static/js/charts.js`
3. `edutrack/web/static/app.js` (cache-bust `?v=20261120-v8.1`)
4. `edutrack/web/static/index.html` (cache-bust `?v=20261120-v8.1`)
5. `edutrack/web/static/sw.js` (`CACHE_NAME = "edutrack-shell-v8.1"` & `?v=20261120-v8.1`)
6. `edutrack/web/static/js/api.js` (cache-bust `?v=20261120-v8.1`)
7. `edutrack/web/static/js/student.js` (cache-bust `?v=20261120-v8.1`)
8. `edutrack/tests/egm_v8_bugfix_test.py` (tambah uji regresi frontend chart & referensi tak terdefinisi)

### File Baru
9. `docs/designs/egm_v8_1_frontend_chart_fix_spec.md`
10. `docs/designs/goldfish_review_report_v8_1.md`

---

## 6. Detailed Implementation Plan

1. Di `edutrack/web/static/js/teacher.js`:
   - Baris 200: ganti `renderDonutChart("chart-t-attendance", att);` menjadi pemanggilan `renderDoughnutChart("chart-t-attendance", { ... })` sesuai Bagian 3.1.
   - Baris 592: ubah `window.openAttSession = async (sessionId) => {` menjadi `async function openAttSession(sessionId) {` dan tambahkan `window.openAttSession = openAttSession;` setelah blok fungsi.
2. Di `edutrack/web/static/js/charts.js`:
   - Perbarui `renderLineChart(containerId, data)` sesuai Bagian 3.2 agar mendukung format multi-seri `[{ name, points: [{ label, value }] }]` maupun format datar `[{ label, value }]`, menangani nilai `null` di tengah seri (memutus path SVG), serta menampilkan legenda warna bila multi-seri.
3. Perbarui seluruh query string `?v=20261120-v8` -> `?v=20261120-v8.1` pada `index.html`, `sw.js` (termasuk `edutrack-shell-v8` -> `edutrack-shell-v8.1`), `app.js`, `js/api.js`, `js/charts.js`, `js/student.js`, `js/teacher.js`.
4. Di `edutrack/tests/egm_v8_bugfix_test.py`:
   - Tambahkan `test_6_frontend_charts_no_renderDonutChart_and_multiseries_line_chart`:
     - Pastikan tidak ada string `renderDonutChart` di seluruh folder `edutrack/web/static/`.
     - Pastikan `teacher.js` memanggil `renderDoughnutChart("chart-t-attendance"` dan mengekspor/mendeklarasikan `openAttSession`.
     - Uji runtime `renderLineChart` dan `renderDoughnutChart` dengan `node --input-type=module` menggunakan DOM mock minimal (verifikasi output `<svg>`, `<path>`, `<circle>` untuk multi-seri termasuk nilai `null`, single-seri, dan input kosong).

---

## 7. Test Plan & Verification Commands

- `node --check edutrack/web/static/sw.js`
- `for f in edutrack/web/static/app.js edutrack/web/static/js/*.js; do node --input-type=module --check < "$f"; done`
- `python3 -m unittest discover -s edutrack/tests -p "*_test.py" -v`
- `python3 -O -m unittest edutrack/tests/egm_v8_bugfix_test.py -v`
