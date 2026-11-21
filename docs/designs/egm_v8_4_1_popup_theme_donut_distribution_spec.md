# Spesifikasi Desain v8.4.1: Unifikasi Tema Pop-up Dashboard Siswa & Diagram Donat Distribusi Nilai Akhir Kelas

- **Status**: `resolved` (Auto accept oleh pengguna)
- **Target Versi**: `v8.4.1` (`20261120-v8.4.1` / `edutrack-shell-v8.4.1`)
- **Metodologi**: Elephant-Goldfish Model (EGM) + Anti-Slop Mode 1 (`during`)

## 1. Latar Belakang & Tujuan

1. **Unifikasi UI Pop-up Dashboard Siswa**:
   - Saat ini dua pop-up pada dashboard siswa (`#student-ews-popup` untuk peringatan dini EWS dan `#student-reveal-popup` untuk kejutan nilai `Ujian` / `Asesmen Sumatif`) memakai blok CSS terpisah dengan latar solid datar (`#0f172a`, `border-radius: 16px`), sehingga terasa terpisah dari bahasa desain dashboard **Spatial Glassmorphism** (`--glass-card`, `--glass-border`, `--glass-highlight`, `--radius: 20px`, `--shadow-lg`, tombol kapsul `.btn-pill`).
   - Tujuan: Menyatukan struktur UI kedua pop-up ke satu desain dialog yang seragam dengan tema dashboard (baik mode gelap maupun mode terang), sambil mempertahankan pembedaan warna aksen semantik sesuai fungsinya (EWS Perhatian, EWS Kritis, dan Kejutan Nilai Ujian/Asesmen Sumatif).

2. **Diagram Donat untuk "Distribusi Nilai Akhir Kelas"**:
   - Pada dashboard guru, kartu **Distribusi Nilai Akhir Kelas** (`#chart-t-distribution`) saat ini dirender dengan diagram batang (`renderBarChart`), sedangkan kartu sebelahnya **Proporsi Status Kehadiran** (`#chart-t-attendance`) menggunakan diagram donat (`renderDoughnutChart`).
   - Tujuan: Mengubah `#chart-t-distribution` menjadi diagram donat menggunakan `renderDoughnutChart` agar selaras secara visual dengan **Proporsi Status Kehadiran** dan mudah dipindai proporsinya.

## 2. Target Scope & File Boundary

File yang diizinkan untuk diubah pada Fase 5 (Implementasi):
1. `edutrack/web/static/styles.css` — Menyatukan gaya dasar kedua pop-up siswa ke bahasa desain glassmorphism dashboard (tema gelap & terang) dengan aksen warna semantik terpisah, tetap mempertahankan kelas/ID kompatibel dan memenuhi WCAG AA + `prefers-reduced-motion`.
2. `edutrack/web/static/js/student.js` — Menyelaraskan markup header/badge/tombol kedua pop-up agar berbagi struktur visual seragam (`student-modal-*`) sambil mempertahankan seluruh ID dan kelas lama (`#student-ews-popup`, `.ews-modal-dialog`, `#btn-ews-ack`, `#btn-ews-close`, `#student-reveal-popup`, `.reveal-modal-dialog`, `#btn-reveal-action`, `#btn-reveal-close`).
3. `edutrack/web/static/js/teacher.js` — Mengubah rendering `#chart-t-distribution` dari `renderBarChart` menjadi `renderDoughnutChart` dengan 5 segmen bucket terurut dan fallback kosong.
4. `edutrack/web/static/index.html`, `edutrack/web/static/app.js`, `edutrack/web/static/sw.js`, `edutrack/web/static/js/api.js`, `edutrack/web/static/js/charts.js` — Bump cache-bust `20261120-v8.4.1` & `edutrack-shell-v8.4.1`.
5. `edutrack/tests/egm_v8_bugfix_test.py`, `edutrack/tests/egm_v8_2_1_rebrand_test.py`, `edutrack/tests/egm_v8_4_dashboard_ux_hard_delete_test.py` — Memperbarui asersi versi cache-bust dan menambahkan verifikasi untuk unifikasi tema pop-up & diagram donat distribusi nilai.

**Di luar cakupan (Out of Scope)**:
- Tidak ada perubahan skema database, migrasi, atau kontrak API backend (`gs.distribution` sudah mengembalikan 5 bucket tetap: `"90-100"`, `"80-89"`, `"70-79"`, `"60-69"`, `"<60"`).

## 3. Desain Detail

### 3.1. Unifikasi Tema Pop-up Dashboard Siswa (`#student-ews-popup` & `#student-reveal-popup`)

- **Struktur Visual Bersama (Satu Tema Dashboard)**:
  - **Backdrop**: `background: rgba(11, 15, 25, 0.68); backdrop-filter: blur(8px);` (mode terang: `rgba(15, 23, 42, 0.42)`), posisi tetap `inset: 0`, `z-index: 9999`, terpusat (`display: flex; align-items: center; justify-content: center; padding: 1rem;`).
  - **Dialog Surface**: Mewarisi bahasa desain `.card` dashboard:
    - `border-radius: var(--radius)` (`20px`)
    - `backdrop-filter: blur(22px) saturate(140%)`
    - `box-shadow: var(--shadow-lg), var(--glass-highlight)`
    - **Dark Theme**: `background: rgba(22, 25, 37, 0.92)` (berbasis `#161925` dari `--bg-gradient` dashboard, opasitas `0.92` agar tetap terasa seperti kaca dashboard namun menjaga kontras teks tinggi), teks `#f8fafc`, teks sekunder `#cbd5e1`.
    - **Light Theme**: `background: rgba(255, 255, 255, 0.94)` (berbasis putih glassmorphism dashboard), teks `#0f172a`, teks sekunder `#334155`.
  - **Header & Close Button**: Struktur identik (badge status/kategori di atas judul `h2`, tombol tutup `×` berbentuk lingkaran/kapsul lembut berukuran minimal `44x44px` dengan latar `var(--glass-input)` dan border `var(--glass-border)`).
  - **Inner Content Box**: Kedua modal memakai kotak konten berbingkai kaca (`background: rgba(255, 255, 255, 0.055)` pada gelap / `rgba(15, 23, 42, 0.035)` pada terang, `border: 1px solid var(--glass-border)`, `border-radius: 14px`, `padding: 1rem 1.15rem`).
    - Pada EWS: memuat daftar indikator pemicu peringatan.
    - Pada Kejutan Nilai: memuat tampilan skor terkunci (`?`) atau skor terbuka (`tabular-nums`).
  - **Footer & Primary CTA**: Garis pemisah `border-top: 1px solid var(--glass-border)`, tombol aksi berbentuk kapsul (`border-radius: 999px` selaras `.btn-pill`), `min-height: 44px`, `min-width: 132px`.

- **Penyesuaian Warna Semantik per Modal (Terverifikasi WCAG AA)**:
  1. **EWS Perhatian (`#student-ews-popup.ews-popup--perhatian`)**:
     - Border dialog: `rgba(251, 191, 36, 0.50)` (dark) / `rgba(217, 119, 6, 0.45)` (light) + aksen atas `3px` amber.
     - Badge: `#fde68a` pada `#78350f` (dark, 7.28:1) / `#92400e` pada `#fffbeb` (light, 6.84:1).
     - Tombol **Mengerti**: `#0369a1` teks `#ffffff` (5.93:1).
  2. **EWS Kritis (`#student-ews-popup.ews-popup--kritis`)**:
     - Border dialog: `rgba(248, 113, 113, 0.55)` (dark) / `rgba(220, 38, 38, 0.45)` (light) + aksen atas `3px` merah.
     - Badge: `#fecaca` pada `#7f1d1d` (dark) / `#991b1b` pada `#fef2f2` (light).
     - Tombol **Mengerti**: `#b91c1c` teks `#ffffff`.
  3. **Kejutan Nilai Ujian & Asesmen Sumatif (`#student-reveal-popup`)**:
     - Border dialog: `rgba(20, 184, 166, 0.55)` (dark, selaras `--student-accent`) / `rgba(13, 148, 136, 0.45)` (light) + aksen atas `3px` teal.
     - Badge: `#99f6e4` pada `#134e4a` (dark) / `#115e59` pada `#f0fdfa` (light).
     - Tombol **Lihat / Nilai Berikutnya / Selesai**: `#0f766e` teks `#ffffff` (selaras aksen teal portal siswa).

- **Aksesibilitas & Invarian**:
  - Fokus keyboard (`Tab` / `Shift+Tab` trap & `Escape` dismiss) dan `:focus-visible` (`3px solid #38bdf8` dark / `#0369a1` light).
  - `@media (prefers-reduced-motion: reduce)` menonaktifkan transisi/animasi pada kedua modal.
  - Tanpa em dash (`—`) dan tanpa emoji dekoratif pada copy modal.

### 3.2. Diagram Donat "Distribusi Nilai Akhir Kelas" (`#chart-t-distribution`)

- Mengganti `renderBarChart("chart-t-distribution", ...)` di `edutrack/web/static/js/teacher.js` menjadi `renderDoughnutChart("chart-t-distribution", ...)`:
  - Urutan segmen deterministik mengikuti 5 bucket `gs.distribution`:
    1. `"90-100"` -> warna `#34d399` (Emerald)
    2. `"80-89"` -> warna `#38bdf8` (Sky)
    3. `"70-79"` -> warna `#818cf8` (Indigo)
    4. `"60-69"` -> warna `#fbbf24` (Amber)
    5. `"<60"` -> warna `#f87171` (Red)
  - Properti `renderDoughnutChart`:
    - `centerValue`: `gs.average != null ? String(gs.average) : "-"`
    - `centerLabel`: `"Rata-Rata"`
    - `centerBadge`: `gs.graded_count ? `${gs.graded_count} Siswa` : ""`
    - `segments`: memetakan 5 bucket di atas dengan `label: k`, `value: Number(dist[k] || 0)`, `displayValue: `${Number(dist[k] || 0)} siswa``, `color`.
    - `emptyMessage`: `"Belum ada data distribusi nilai"`
  - Menangani kasus `gs.distribution` kosong atau semua bucket `0` secara aman (menampilkan `emptyMessage` bawaan `renderDoughnutChart`).

## 4. Rencana Verifikasi

1. `node --input-type=module --check` pada seluruh modul ES frontend + `node --check sw.js`.
2. Audit kontras WCAG AA via `contrast_check.py` untuk seluruh pasangan warna baru (termasuk `#fecaca:#7f1d1d`, `#991b1b:#fef2f2`, `#ffffff:#b91c1c`, `#99f6e4:#134e4a`, `#115e59:#f0fdfa`, `#ffffff:#0f766e`, `#f8fafc:#161925`, `#cbd5e1:#161925`).
3. Seluruh unit test (`python3 -m unittest discover -s edutrack/tests -p "*_test.py" -v`) lulus 100%, termasuk verifikasi invarian UI baru di `egm_v8_4_dashboard_ux_hard_delete_test.py`.
