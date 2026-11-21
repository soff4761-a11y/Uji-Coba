# Concepts Brief — Tugas Dinilai vs. Checklist Pengumpulan & Modal EWS Tengah Anti-Slop (v8.3)

- **Fitur:** Pemisahan Tugas Dinilai (Angka) vs. Tugas Tidak Dinilai (Checklist Pengumpulan) pada Dashboard Guru & Siswa, Peringatan EWS untuk Checklist yang Belum Dikumpulkan Berulang, serta Redesain Modal EWS Tengah berbasis `anti-slop` (Mode 1: During)
- **Author:** Elephant (atas keputusan pemilik proyek)
- **Date:** 2026-11-21
- **Baseline:** `uji-coba-v8.2.2-bahasa-indonesia.zip`

## Overview
Menambahkan dukungan tugas bertipe **Tidak Dinilai (Checklist Pengumpulan)** di samping tugas **Dinilai (Angka)** agar guru dapat mencatat pengumpulan buku catatan/tugas non-skor hanya dengan centang, siswa melihat kedua kategori tugas secara terpisah, EWS tetap memberi peringatan jika siswa beberapa kali tidak mengumpulkan tugas checklist, serta memperbesar dan memusatkan dialog EWS siswa di tengah layar dengan koreksi desain `anti-slop` yang baru tertutup saat siswa menekan tombol **Mengerti**.

## Problem Statement
1. Saat ini seluruh komponen di `assessments` wajib memiliki skor angka dan masuk ke perhitungan nilai akhir, sehingga tugas pengumpulan sederhana (seperti buku catatan yang cukup dicentang) bercampur dengan nilai angka dan mendistorsi rata-rata/KKM.
2. Di dashboard siswa, semua penilaian tergabung dalam satu tabel bernilai sehingga siswa tidak dapat membedakan tugas bernilai dan tugas pengumpulan tanpa nilai.
3. Pop-up EWS siswa saat ini berupa banner kecil (`460px`) di tepi atas layar yang hilang otomatis dalam 3 detik, masih memakai emoji dekoratif `⚠️`, dan belum memenuhi standar aksesibilitas modal `anti-slop` (target sentuh 44px, tema terang/gelap penuh, kontrol keyboard `Escape`).

## Goals
1. Menambahkan kolom `is_graded` (migrasi v6 aditif untuk SQLite & PostgreSQL/Supabase) pada tabel `assessments`.
2. Menyediakan pilihan **Dinilai (Angka)** vs. **Tidak Dinilai (Checklist Pengumpulan)** di form guru dan tampilan centang (**Sudah Mengumpulkan** / **Belum Mengumpulkan**) di Buku Nilai.
3. Memisahkan tabel **Tugas & Penilaian Bernilai** dan **Tugas Pengumpulan / Checklist (Tanpa Nilai)** pada dashboard siswa, serta mengecualikan tugas checklist 100% dari nilai akhir, KKM, statistik, dan grafik nilai.
4. Memicu peringatan EWS (baik di dashboard guru maupun modal siswa) apabila jumlah tugas checklist dipublikasikan yang belum dikumpulkan mencapai ambang batas (`ews_unsubmitted_checklist_threshold = 3`).
5. Mengubah pop-up EWS siswa menjadi dialog modal besar di tengah layar yang baru menutup ketika siswa mengklik tombol **Mengerti** (atau tombol tutup / `Escape`), lolos Delivery Gate `anti-slop` Mode 1 (*During*) termasuk verifikasi kontras WCAG AA `contrast_check.py`.

## Non-Goals
- Tidak mengubah rumus perhitungan `compute_final_score` untuk tugas bernilai yang sudah ada.
- Tidak menghapus data nilai historis; seluruh asesmen lama otomatis berstatus `is_graded = true`.
- Tidak mengubah arsitektur autentikasi, CSRF, atau skema tabel selain penambahan kolom `is_graded` pada `assessments`.
