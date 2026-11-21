# Concepts Brief — Pembaruan Dashboard Guru & Siswa, Hard Delete, Perbandingan Materi & Pop-up Kejutan Ujian (v8.4)

- **Fitur:** Penggabungan EWS & Perhatian Khusus Guru, Sesi Pertemuan & Panel Siswa Scrollable, Hard Delete Permanen, Perbandingan Materi Berdampingan Kanan-Kiri (Guru & Siswa), Agregasi Rata-Rata per Kategori Penilaian, dan Pop-up Kejutan Nilai Ujian/Asesmen Sumatif (EGM + `anti-slop` Mode 1: During)
- **Author:** Elephant (atas keputusan pemilik proyek)
- **Date:** 2026-11-21
- **Baseline:** `uji-coba-v8.3-bahasa-indonesia.zip`

## Overview
Merampingkan dan memperkuat pengalaman dashboard guru serta siswa dengan 7 peningkatan terpadu: menyatukan kartu EWS dan Perhatian Khusus di dashboard guru, membatasi tampilan daftar sesi pertemuan (maks 5) dan 3 panel grafik siswa ke tinggi tetap yang dapat digulir, memastikan penghapusan siswa/pertemuan/nilai bersifat permanen menyeluruh di database, menghadirkan perbandingan tren nilai antar materi berdampingan kanan-kiri untuk guru & siswa, mengelompokkan grafik rata-rata komponen berdasarkan kategori penilaian, serta menambahkan pop-up kejutan klik **"Lihat"** untuk nilai **Ujian** dan **Asesmen Sumatif** di dashboard siswa (status tersimpan di kolom `grades.revealed_at` via migrasi v7).

## Goals
1. Menggabungkan kartu **Peserta Didik yang Memerlukan Perhatian** dan **Early Warning System (EWS)** menjadi satu kartu terpadu di dashboard guru.
2. Menjadikan daftar sesi pertemuan (`#att-sessions-list`) scrollable dengan batas tampilan maksimal 5 sesi sekaligus.
3. Menjamin *hard delete* permanen menyeluruh saat menghapus siswa (satuan/massal), sesi pertemuan, asesmen, maupun reset nilai/sesi tanpa menyisakan baris yatim di database.
4. Menerapkan tinggi tetap + *scrollable* berstandar `anti-slop` pada 3 panel grafik dashboard siswa (**Perkembangan Nilai Pribadi**, **Capaian per Kategori Penilaian**, **Ringkasan Kehadiran Pribadi**).
5. Menyediakan filter materi & perbandingan tren nilai **Materi Kiri vs. Materi Kanan** berdampingan pada dashboard guru maupun siswa.
6. Mengubah grafik **Rata-Rata Antarkomponen Penilaian** agar menghitung rata-rata berdasarkan kelompok kategori (`Tugas`, `Kuis`, `Proyek`, `Latihan`, `Ujian`, dll.).
7. Menambahkan modal kejutan nilai khusus kategori **Ujian** dan **Asesmen Sumatif** di dashboard siswa dengan tombol **"Lihat"** yang menyimpan status `revealed_at` di DB (migrasi v7) lalu menampilkan nilai normal di tabel.

## Non-Goals
- Tidak mengubah mekanisme autentikasi, CSRF, atau identitas nama aplikasi **Bahasa Indonesia**.
- Tidak menghapus fitur tugas checklist (`is_graded`) maupun modal EWS tengah dari v8.3.
