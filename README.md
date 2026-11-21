# EduTrack — Siap Jalankan Lokal (SQLite/PostgreSQL) & Online di Vercel (PostgreSQL)

Aplikasi web administrasi pembelajaran untuk **Guru** dan **Peserta Didik** dengan arsitektur modular (*contract-first*, *test-driven*), penegakan RBAC sisi server, grafik perkembangan interaktif, serta ekspor laporan Excel (`.xlsx`), CSV, dan PDF.

## Prasyarat

- **Python 3.11+**

## 1. Deploy Gratis ke Vercel + Database PostgreSQL (Neon / Supabase)

Aplikasi ini memprioritaskan `DATABASE_URL` (lalu `POSTGRES_URL`) untuk terhubung ke PostgreSQL. Jika variabel tersebut disetel di Vercel, seluruh tabel akan dibuat otomatis saat pertama kali dibuka dan data tersimpan permanen di cloud.

> **Penting untuk Pengguna Supabase:** Koneksi langsung (*Direct Connection*) Supabase bersifat **IPv6-only** dan akan gagal di runtime serverless Vercel. Pastikan Anda menyalin **Transaction/Session Pooler URL (IPv4)** dari dashboard Supabase.
>
> **Catatan Fitur Cadangan (Backup/Restore):** Fitur backup/restore file SQLite hanya aktif pada mode lokal SQLite dan dinonaktifkan pada mode PostgreSQL cloud (gunakan fitur backup/snapshot bawaan Neon atau Supabase).

### Langkah A: Buat Database PostgreSQL Gratis (Pilih Neon atau Supabase)
1. Daftar gratis di **Neon** (`neon.tech`) atau **Supabase** (`supabase.com`).
2. Buat proyek baru, lalu salin **Connection String** PostgreSQL (untuk Supabase, pilih tab **Pooler / IPv4**, format `postgresql://user:password@host:6543/postgres?sslmode=require`).

### Langkah B: Unggah ke GitHub
1. Pastikan seluruh berkas repositori (termasuk `api/`, `edutrack/`, `vercel.json`, dan `requirements.txt`) sudah siap di direktori proyek Anda.
2. Push ke repositori GitHub:
   ```bash
   git init
   git add .
   git commit -m "Deploy EduTrack ke Vercel"
   git branch -M main
   git remote add origin https://github.com/<USERNAME>/<NAMA_REPO>.git
   git push -u origin main
   ```

### Langkah C: Hubungkan & Deploy di Vercel
1. Masuk ke `vercel.com` -> klik **Add New... -> Project** -> pilih repositori GitHub Anda.
2. Sebelum klik Deploy, buka bagian **Environment Variables** dan tambahkan:
   - `DATABASE_URL` = *(tempel Connection String IPv4 Pooler dari Neon/Supabase)*
   - `EDUTRACK_COOKIE_SECURE` = `true`
   - `EDUTRACK_SEED_DEMO` = `true` *(catatan: pastikan akun guru awal sudah tersedia di database sebelum mengubah ini ke `false`)*
3. Klik **Deploy**. Setelah selesai, buka URL Vercel Anda dan cek `/api/health` untuk memastikan `database_backend: "postgresql"` dan `database_connected: true`.

> **Alternatif tanpa GitHub:** Instal Vercel CLI (`npm i -g vercel`), setel `DATABASE_URL` di dashboard proyek Vercel sebelum produksi, lalu jalankan `vercel --prod`.

## 2. Menjalankan di Laptop/PC Lokal (SQLite atau `.env` PostgreSQL)
```bash
pip install -r requirements.txt
python3 -m edutrack.main --host 127.0.0.1 --port 8000
```
Buka `http://127.0.0.1:8000`. Untuk menguji PostgreSQL di lokal, salin `.env.example` menjadi `.env` dan isi `DATABASE_URL`.

### Akun Contoh Awal
- **Guru:** `guru_budi` / `GuruPassword123!`
- **Peserta Didik Aktif:** `alya_001` / `SiswaPass123!` (juga `dimas_002`, `citra_003`, `fajar_004`)
- **Peserta Didik Belum Aktivasi:** `nadia_005` / `SiswaPass123!`

## 3. Menjalankan Pengujian Otomatis
```bash
python3 -m unittest discover -s edutrack/tests -p '*_test.py' -v
```
