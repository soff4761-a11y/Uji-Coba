# Spesifikasi Desain v8.4.2: Penyempurnaan Tata Letak Dashboard Guru & Siswa, Hapus Semua Sesi Pertemuan, dan Pembersihan Teks

- **Status**: `resolved` (Auto accept oleh pengguna)
- **Target Versi**: `v8.4.2` (`20261120-v8.4.2` / `edutrack-shell-v8.4.2`)
- **Metodologi**: Elephant-Goldfish Model (EGM) + Anti-Slop Mode 1 (`during`)

## 1. Ringkasan 9 Perubahan yang Diminta

### Dashboard Guru
1. **Distribusi Nilai Akhir Kelas dapat digulir**: Bungkus `#chart-t-distribution` dalam wadah tinggi tetap yang dapat digulir vertikal (`height: 290px; overflow-y: auto; overflow-x: hidden; scrollbar-gutter: stable;`) agar legenda dan grafik tidak memanjang ke bawah.
2. **Rata-Rata Antarkomponen Penilaian diperbesar (ruang penuh)**: Pindahkan kartu **Rata-Rata Antarkomponen Penilaian** (`#chart-t-components`) keluar dari grid 3 kolom menjadi kartu lebar penuh (100% width) tersendiri, sementara **Distribusi Nilai Akhir Kelas** dan **Proporsi Status Kehadiran** ditempatkan berdampingan dalam grid 2 kolom (`.two-col`) yang simetris. Dengan lebar penuh, diagram batang antarkomponen memiliki ruang hampir 3x lebih lega sehingga label kategori terbaca jelas dan nyaman dilihat.
3. **Tombol "Pilih Semua" & "Hapus Semua" pada Perbandingan Peserta Didik**: Tambahkan dua tombol cepat (`#btn-compare-select-all` = **"Pilih Semua"** dan `#btn-compare-clear-all` = **"Hapus Semua"**) pada bilah kontrol kartu **Analisis Tren Individual & Perbandingan Peserta Didik** (`min-height: 44px`, target sentuh ramah mobile).
   - Klik **Pilih Semua**: memilih seluruh `<option>` di `#select-compare-students` lalu langsung menjalankan `runStudentComparison(ids)`.
   - Klik **Hapus Semua**: membatalkan seluruh pilihan di `#select-compare-students` dan mengosongkan kedua grafik perbandingan (`#chart-t-compare` dan `#chart-t-compare-right`).
   - Saat kelas belum dipilih ("Semua Kelas"), kedua tombol dinonaktifkan (`disabled = true`).
4. **Hapus Semua Sesi Pertemuan Sekaligus (Hard Delete Permanen)**:
   - **Backend**: Tambahkan `DELETE /api/teacher/classes/{class_id}/attendance/sessions` (dilindungi auth guru + kepemilikan kelas anti-IDOR + CSRF) yang memanggil `AttendanceService.delete_all_sessions_for_class(teacher, class_id)` -> `AttendanceRepository.delete_all_sessions_for_class(class_id)`.
   - **Hard Delete Tanpa Sisa**: Dalam satu transaksi, hapus permanen seluruh `correction_requests` (`target_type = 'attendance'` terkait `attendance_records` pada sesi-sesi kelas tersebut), `attendance_history`, `attendance_records`, dan `attendance_sessions` untuk `class_id` tersebut; kembalikan `{"status": "deleted", "deleted_sessions": count}`.
   - **Frontend**: Tambahkan tombol `#btn-delete-all-sessions` (**"Hapus Semua"**) pada header kartu **Daftar Sesi Pertemuan** (dengan konfirmasi eksplisit `confirm(...)`, menonaktifkan tombol bila tidak ada sesi, lalu memuat ulang daftar sesi & membersihkan formulir editor kehadiran).
5. **Judul Bagian Peringatan**: Ubah judul `#ews-card` dari `Sistem Peringatan Dini (EWS) & Peserta Didik Memerlukan Perhatian` menjadi **`Peserta Didik Memerlukan Perhatian`**.
6. **Judul Panel Perbandingan**: Hapus awalan label `Panel Kiri:` dan `Panel Kanan:` pada `#t-compare-left-title` dan `#t-compare-right-title` (di `index.html` maupun `teacher.js`), sehingga yang tampil hanya nama materinya (mis. `Semua Materi` atau `Materi 1 Teks LHO`).
7. **Teks yang Dihapus dari Dashboard Guru**:
   - Hapus `#ews-summary` (teks ringkasan `"1 peserta didik memerlukan perhatian (1 Kritis, 0 Perhatian) | Alpa >= 3x | Belum Kumpul >= 3 tugas checklist."` beserta teks bawaannya di HTML dan pengisian teks di `renderEarlyWarningSystem()`).
   - Hapus `<p class="small muted">Komunikasi searah permanen untuk jadwal ujian, perubahan materi, dan tenggat tugas (hanya hilang jika dihapus guru).</p>`.
   - Hapus `<p class="muted small" id="teacher-page-subtitle">Pusat pengelolaan pembelajaran, nilai, dan kehadiran</p>`.
   - Hapus teks petunjuk `"Pilih peserta didik dan materi pada panel kiri serta kanan untuk membandingkan tren nilai secara berdampingan."` dari `#t-compare-hint` (biarkan kosong/tersembunyi saat kelas sudah dipilih; tetap jaga kebersihan layout).

### Dashboard Siswa
8. **Teks yang Dihapus dari Dashboard Siswa**:
   - Pastikan tidak ada teks `"Pilih peserta didik dan materi pada panel kiri serta kanan untuk membandingkan tren nilai secara berdampingan."` di dashboard siswa.
   - Hapus `<p class="small muted">Bandingkan perkembangan nilai Anda antara dua materi atau seluruh materi secara berdampingan.</p>` pada kartu **Perbandingan Tren Nilai Antarmateri**.
   - Hapus `<p class="small muted">Tugas berbentuk checklist pengumpulan (seperti buku catatan) tidak masuk hitungan nilai akhir, tetapi tetap dipantau pada peringatan dini.</p>` pada tab Nilai Siswa.
9. **Penggantian Label di Dashboard Siswa**:
   - Ganti judul `Tugas Pengumpulan (Tanpa Nilai)` menjadi **`Catatan`**.
   - Ganti judul `Tugas dan Penilaian Bernilai` menjadi **`Penilaian`**.

## 2. Target Scope & File Boundary

1. `edutrack/repositories/attendance_repo.py` — Tambah `delete_all_sessions_for_class(class_id: int) -> int` (hapus permanen `correction_requests`, `attendance_history`, `attendance_records`, `attendance_sessions` dalam satu transaksi, kompatibel SQLite & PostgreSQL).
2. `edutrack/services/attendance_service.py` — Tambah `delete_all_sessions_for_class(teacher: User, class_id: int) -> int` (cek `Role.TEACHER`, kepemilikan kelas anti-IDOR, audit log).
3. `edutrack/web/api.py` — Tambah endpoint `DELETE /api/teacher/classes/{class_id}/attendance/sessions`.
4. `edutrack/web/static/index.html` — Layout kartu grafik dashboard guru (full-width `#chart-t-components` + `.two-col` untuk `#chart-t-distribution` dalam `.student-panel-scroll` & `#chart-t-attendance`), tombol `#btn-compare-select-all`, `#btn-compare-clear-all`, `#btn-delete-all-sessions`, pembaruan judul/label, penghapusan 7 teks yang diminta, serta bump `?v=20261120-v8.4.2`.
5. `edutrack/web/static/styles.css` — Pastikan `.student-panel-scroll` (atau kelas bersama `.panel-scroll-fixed`) mendukung tinggi tetap `290px` di dashboard guru & siswa, serta pastikan tombol aksi baru (`#btn-compare-select-all`, `#btn-compare-clear-all`, `#btn-delete-all-sessions`) memenuhi target sentuh `>= 44px` dan kontras WCAG AA.
6. `edutrack/web/static/js/teacher.js` — Handler **Pilih Semua** / **Hapus Semua** perbandingan siswa, handler **Hapus Semua** sesi pertemuan (`DELETE /api/teacher/classes/{class_id}/attendance/sessions`), hapus awalan `Panel Kiri:` / `Panel Kanan:`, hapus pengisian teks `#ews-summary` dan `#t-compare-hint`, bump `?v=20261120-v8.4.2`.
7. `edutrack/web/static/js/student.js`, `edutrack/web/static/app.js`, `edutrack/web/static/sw.js`, `edutrack/web/static/js/api.js`, `edutrack/web/static/js/charts.js` — Bump `?v=20261120-v8.4.2` dan `edutrack-shell-v8.4.2`.
8. `edutrack/tests/egm_v8_bugfix_test.py`, `edutrack/tests/egm_v8_2_1_rebrand_test.py`, `edutrack/tests/egm_v8_3_ungraded_tasks_ews_modal_test.py` (hanya jika ada asersi teks lama yang perlu diselaraskan), dan `edutrack/tests/egm_v8_4_dashboard_ux_hard_delete_test.py` — Tambah pengujian `DELETE /api/teacher/classes/{class_id}/attendance/sessions` (termasuk anti-IDOR & zero leftover rows) serta invarian UI v8.4.2.

## 3. Rencana Verifikasi

1. `node --input-type=module --check` pada semua modul ES + `node --check sw.js`.
2. Audit kontras WCAG AA melalui `contrast_check.py`.
3. Seluruh unit test (`python3 -m unittest discover -s edutrack/tests -p "*_test.py" -v`) + `python3 -O -m unittest edutrack/tests/egm_v8_4_dashboard_ux_hard_delete_test.py -v`.
