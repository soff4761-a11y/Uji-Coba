# EduTrack — Aplikasi Web Administrasi Pembelajaran

Aplikasi web terintegrasi untuk membantu **Guru** mengelola kelas, peserta didik, nilai, kehadiran, analisis perkembangan belajar, dan laporan akademik (Excel, CSV, PDF), serta menyediakan portal pribadi bagi **Peserta Didik** untuk memantau capaian dan kehadiran secara mandiri dengan penegakan keamanan **Role-Based Access Control (RBAC)** di sisi server dan basis data.

## Arsitektur Modular (Contract-First & Test-Driven)

```
edutrack/
├── configs/         # Konfigurasi bertipe eksplisit (AppConfig)
├── domain/          # Logika domain murni (nilai, statistik, kehadiran, kriptografi, error)
├── repositories/    # Adaptor basis data SQLite & PostgreSQL (Vercel/Neon/Supabase) + skema relasional
├── services/        # Layanan bisnis, otorisasi kepemilikan, impor CSV/XLSX, ekspor PDF/XLSX/CSV
├── web/             # REST API FastAPI & antarmuka responsif Mode Terang/Gelap + grafik SVG
├── tests/           # Unit test, service test, dan E2E security/IDOR test (*_test.py)
└── main.py          # Entrypoint server CLI/ASGI beserta data contoh awal
```

## Cara Menjalankan Aplikasi

1. Pastikan Python 3.11+ terpasang dan instal dependensi:
   ```bash
   pip install -r edutrack/requirements.txt
   ```
2. Jalankan server web (dari direktori induk yang memuat folder `edutrack/`):
   ```bash
   python3 -m edutrack.main --host 127.0.0.1 --port 8000
   ```
3. Buka `http://127.0.0.1:8000` di browser.

### Akun Contoh Awal (Otomatis Terbuat Saat Pertama Kali Dijalankan)
- **Guru:** `guru_budi` / `GuruPassword123!`
- **Peserta Didik Aktif:** `alya_001` / `SiswaPass123!` (juga `dimas_002`, `citra_003`, `fajar_004`)
- **Peserta Didik Belum Aktivasi (uji wajib ganti sandi pertama kali):** `nadia_005` / `SiswaPass123!`

## Menjalankan Pengujian Otomatis

Dari direktori induk yang memuat paket `edutrack/`:
```bash
python3 -m unittest discover -s edutrack/tests -p '*_test.py' -v
```
