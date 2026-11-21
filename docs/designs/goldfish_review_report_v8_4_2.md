# Laporan Sintesis Review Goldfish v8.4.2

- **Dokumen Target**: `docs/designs/egm_v8_4_2_dashboard_refinements_spec.md`
- **Status**: `resolved` (Auto accept oleh pengguna)

## Ringkasan Temuan & Usulan Resolusi (`PROPOSE FIX`)

### Blocker (5)
1. **[B-1 | Layout SVG `#chart-t-components`]** `renderBarChart()` (`charts.js:101-127`) memakai basis `w = 440` dengan `width:100%;height:auto;` dan memotong label pada 10 karakter; saat dipindah ke kartu lebar penuh, grafik akan membengkak vertikal ~540–635px.
   - **Usulan (`PROPOSE FIX`)**: Tambahkan dukungan mode lebar penuh pada `renderBarChart()` (basis `w = Math.max(820, items.length * 104 + padL + padR)`, tinggi `250`, batas `max-height: 290px`, dan label kategori hingga 20 karakter).
2. **[B-2 | Anti-Slop `R-26`/`R-39`]** `styles.css` belum memiliki aturan `.btn:disabled`, sehingga tombol nonaktif tetap memakai `cursor: pointer` dan animasi hover.
   - **Usulan (`PROPOSE FIX`)**: Tambahkan `.btn:disabled { opacity: 0.48; cursor: not-allowed; pointer-events: none; transform: none; }`.
3. **[B-3 | WCAG AA & Anti-Slop `R-03`]** `.btn-danger` (`rgba(239, 68, 68, 0.85)`) gagal kontras 4.5:1 pada mode terang (~3.76:1) dan tinggi `.btn-sm` untuk `#btn-delete-all-sessions` < 44px.
   - **Usulan (`PROPOSE FIX`)**: Gunakan warna danger WCAG AA (`#b91c1c` / `:hover #991b1b`, rasio 6.47:1 / 8.31:1) serta `min-height: 44px` pada `#btn-delete-all-sessions`, `#btn-compare-select-all`, dan `#btn-compare-clear-all`.
4. **[B-4 & B-5 | Regresi Tes Versi]** `egm_v8_bugfix_test.py:394` dan `egm_v8_2_1_rebrand_test.py:78` meng-assert versi `20261120-v8.4.1` dan `edutrack-shell-v8.4.1`; wajib diperbarui ke `v8.4.2`.

### Major (8)
1. **[M-1 | Hard Delete SQL]** `delete_all_sessions_for_class` wajib menghapus `correction_requests` dengan filter gabungan `student_id` + (`target_id IN session_ids OR target_id IN record_ids`) sebelum menghapus `attendance_history`, `attendance_records`, dan `attendance_sessions` dalam satu transaksi portabel SQLite+PostgreSQL.
2. **[M-2 | Idempotensi `0` Sesi]** Hitung `COUNT(*)` sesi kelas di awal transaksi; jika `0`, langsung `return 0` (tanpa `IN ()` kosong dan tanpa `rowcount == -1`).
3. **[M-3 | Simetri `.two-col` & Mobile]** Pertahankan nama kelas `.student-panel-scroll` (diuji tes v8.4), bungkus `#chart-t-attendance` juga dengan `.student-panel-scroll` agar simetris dengan `#chart-t-distribution`, dan ubah `.two-col` menjadi `minmax(min(300px, 100%), 1fr)` untuk mencegah overflow di layar 320px.
4. **[M-4 | State Perbandingan Siswa]** Tandai hanya 3 siswa awal sebagai `selected` saat muat awal; nonaktifkan tombol **Pilih Semua**, **Hapus Semua**, dan **Bandingkan** saat daftar siswa kosong; pastikan judul panel tetap sinkron saat 0 siswa terpilih.
5. **[M-5 | Reset Editor Kehadiran]** Handler `#btn-delete-all-sessions` harus mereset `state.selectedSessionId = null`, `state.activeSessionDetail = null`, `state.sessions = []`, memperbarui `disabled` di kedua cabang `loadAttendanceTab()`, mencegah klik ganda saat proses `DELETE`, dan membungkus `#att-session-count` + `#btn-delete-all-sessions` dalam `<div class="row gap-sm">`.
6. **[M-6 | `#t-compare-hint` & Label A11y]** Sembunyikan `#t-compare-hint` dengan `.hidden` saat kelas sudah dipilih (tampil hanya saat "Semua Kelas"); isi default `<label>` panel perbandingan dengan `Semua Materi` (bukan kosong) dan reset saat pindah kelas.
7. **[M-7 | Kontras Batang Dark Mode]** Ganti warna batang hardcoded `#1e3a8a` pada `#chart-t-components` menjadi warna peka tema (`#38bdf8` di gelap, `#1d4ed8` di terang) agar lulus kontras WCAG AA di kedua mode.
8. **[M-8 | Audit & Null Safety]** Pastikan `delete_all_sessions_for_class` memanggil `_get_owned_class` + `log_audit`, dan bersihkan dead code `#ews-summary` (`chkThr`/`alpaThr`) di `teacher.js`.

### Nit (5)
- Selaraskan pesan empty state tabel **Catatan** siswa di `student.js` menjadi `"Belum ada catatan pada pilihan materi ini."`; tidak ada regresi unit test dari penghapusan/penggantian teks pada butir 5–9.
