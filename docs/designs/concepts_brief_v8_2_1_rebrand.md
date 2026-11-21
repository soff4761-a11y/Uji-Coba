# Concepts Brief — Rebranding Antarmuka Pengguna ke "Bahasa Indonesia" (v8.2.1)

- **Fitur:** Penggantian Identitas Aplikasi Terlihat Pengguna (`EduTrack` -> `Bahasa Indonesia`) & Pembaruan Ikon PWA
- **Author:** Elephant (atas keputusan pemilik proyek)
- **Date:** 2026-11-21
- **Baseline:** `uji-coba-v8.2-fixed.zip`

## Overview
Mengubah seluruh nama aplikasi yang tampil di hadapan pengguna akhir (guru, admin, siswa, dan keluaran dokumen ekspor) dari **EduTrack** menjadi **Bahasa Indonesia**, sekaligus memperbarui ikon PWA (`icon.svg`) dari siluet huruf **E** menjadi monogram **BI** yang serasi dengan palet visual aplikasi.

## Problem Statement
Aplikasi saat ini masih menampilkan nama merek generik **EduTrack** dan ikon huruf **E** pada halaman login, aktivasi akun, sidebar portal guru/siswa, manifest PWA, template impor Excel, badge default PDF, dan judul API. Pemilik proyek membutuhkan aplikasi tampil dengan identitas mata pelajaran **Bahasa Indonesia** secara konsisten tanpa mengganggu infrastruktur deployment (Vercel/Supabase) maupun sesi pengguna aktif.

## Goals
1. Mengganti seluruh kemunculan tulisan `EduTrack` / `EDUTRACK` yang terlihat oleh pengguna akhir menjadi **Bahasa Indonesia** / **BAHASA INDONESIA**.
2. Memperbarui `edutrack/web/static/icon.svg` menjadi monogram **BI** yang tajam, proporsional, dan aman pada area *maskable* PWA.
3. Memperbarui versi cache Service Worker (`sw.js`) agar browser/PWA pengguna langsung menarik `index.html`, `manifest.json`, dan `icon.svg` terbaru.
4. Memperbarui asersi pengujian terkait dan menambahkan uji regresi branding agar tidak ada sisa teks `EduTrack` pada lapisan terlihat pengguna.

## Non-Goals
- Tidak mengubah variabel lingkungan (`EDUTRACK_*`), nama cookie (`edutrack_session`, `edutrack_csrf`), kunci `localStorage` (`edutrack_theme`, `edutrack_sidebar_collapsed`, `edutrack_offline_*`), nama berkas default SQLite/backup (`edutrack_data.db`, `edutrack_backups/`), atau struktur paket Python (`edutrack/`, `api/index.py`, `vercel.json`).
- Tidak mengubah dokumen desain historis di `docs/designs/egm_v2..v8_2*.md` maupun komentar internal kode.

## Key Trade-offs & Risk Mitigation
- **Stabilitas Deployment vs. Kebersihan Internal:** Menjaga seluruh identifier internal (`edutrack`, `EDUTRACK_*`) menghindari risiko kegagalan deploy Vercel, putusnya sesi login pengguna aktif, dan hilangnya antrean kehadiran offline di `localStorage`.
- **Stale PWA Cache:** Diatasi dengan menaikkan `CACHE_NAME` di `edutrack/web/static/sw.js` dari `"edutrack-shell-v8.2"` ke `"edutrack-shell-v8.2.1"`.
- **Pemotongan Teks di Mobile/PWA:** Nama `"Bahasa Indonesia"` lebih panjang daripada `"EduTrack"`; di `manifest.json`, `short_name` menggunakan `"Bahasa Indonesia"` (atau `"B. Indonesia"` bila terlalu panjang — ditetapkan di spesifikasi desain) serta teks sidebar dicek agar tidak merusak tata letak.
