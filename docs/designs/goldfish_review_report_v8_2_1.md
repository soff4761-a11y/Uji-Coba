# Laporan Peninjauan Goldfish — Rebranding "Bahasa Indonesia" v8.2.1

- **Status:** `resolved` (Auto accept oleh pengguna — seluruh PROPOSE FIX diterapkan ke spesifikasi)
- **Dokumen Target:** `docs/designs/egm_v8_2_1_rebrand_bahasa_indonesia_spec.md`
- **Peninjau Terisolasi:** Comprehension & Zoom Out, Design Critic & Codebase Auditor, Implementation Readiness
- **Ringkasan Temuan (Setelah Deduplikasi):** `0 Blocker` | `7 Major` | `4 Nit`
- **Status Audit Codebase:** 100% seluruh 13 titik string `EduTrack`/`EDUTRACK` terlihat pengguna + 1 asersi tes (`database_pg_test.py:131`) terverifikasi cocok tanpa ada yang terlewat di JS/CSS/backend.

---

## Daftar Temuan & Kategorisasi Resolusi (`egm-resolve`)

### Major

#### Isu #1 — Geometri SVG `icon.svg` Bersinggungan (Celah 0 px) & Tidak Simetris
- **Persona Peninjau:** Design Critic / Codebase Auditor, Implementation Readiness
- **Severity:** `Major`
- **Affected Scope:** Bagian 3.2 & Bagian 6 Langkah 1 butir 3 (`edutrack/web/static/icon.svg`)
- **Discrepancy Description:** Huruf **I** (`x: 326..372`) dan titik hijau (`cx=394, r=22` -> `x: 372..416`) bersinggungan dengan celah 0 px, melampaui klaim `x: 112..400`, dan bergeser +10 px dari pusat kanvas `256`.
- **Rationale:** Pada ukuran favicon `16×16` dan `32×32`, huruf **I** dan titik hijau akan tampak menempel; melanggar *Zero-Decision Rule* jika pelaksana harus menggeser koordinat sendiri.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Temuan valid dan dapat diverifikasi secara matematis.
- **Proposed Edit:** Perbarui koordinat SVG agar tepat terpusat di `(256, 256)` (`x: 102..410`, `y: 148..364`) dengan celah 32 px antara **B** (`x: 102..266`) dan **I** (`x: 298..344`), serta celah 22 px antara **I** dan titik hijau (`cx=388, cy=342, r=22`, `x: 366..410`). Seluruh elemen berada di dalam lingkaran aman *maskable* W3C (`r = 204.8`, jarak terjauh titik sudut B = `188.1`, tepi luar lingkaran = `179.5`).

#### Isu #2 — Inkonsistensi Jumlah Berkas di Allowlist (7 vs 8) & Prosedur Rollback
- **Persona Peninjau:** Comprehension, Codebase Auditor, Implementation Readiness
- **Severity:** `Major`
- **Affected Scope:** Bagian 3.3 butir 4 & Bagian 5 (`Target Scope & File Boundary`)
- **Discrepancy Description:** Subjudul Bagian 5 menulis `(7 berkas)` padahal daftarnya memuat 8 berkas; Bagian 3.3 butir 4 hanya menyebut rollback 7 berkas tanpa `database_pg_test.py` dan penghapusan `egm_v8_2_1_rebrand_test.py`.
- **Rationale:** Allowlist Fase 5 adalah batas izin resmi; ketidaksinkronan angka menimbulkan ambiguitas dan rollback parsial dapat mematahkan test suite.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Temuan valid; perbaikan langsung menghilangkan kontradiksi internal.
- **Proposed Edit:** Ubah subjudul Bagian 5 menjadi `### Berkas yang Diubah (8 berkas)` dan perbarui Bagian 3.3 butir 4 agar mencantumkan pengembalian 8 berkas eksisting serta penghapusan berkas uji baru `edutrack/tests/egm_v8_2_1_rebrand_test.py`.

#### Isu #3 — Celah `Cache-Control` pada `/manifest.json` & Penjelasan Mekanisme Cache PWA
- **Persona Peninjau:** Comprehension, Design Critic / Codebase Auditor
- **Severity:** `Major`
- **Affected Scope:** Bagian 2.1 #3, Bagian 3.3 #1, & `edutrack/web/api.py:328–335`
- **Discrepancy Description:** Middleware `add_security_headers` di `api.py` belum menyertakan `path == "/manifest.json"` untuk `Cache-Control: no-cache, must-revalidate`, dan dokumen belum menjelaskan keberadaan `skipWaiting()`/`clients.claim()` serta keterbatasan propagasi ikon shortcut PWA yang sudah terpasang di OS.
- **Rationale:** Tanpa `Cache-Control: no-cache` pada `/manifest.json`, browser/CDN dapat menahan metadata nama/ikon lama secara heuristik.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** `edutrack/web/api.py` sudah termasuk di allowlist Fase 5 dan penambahan kondisi `path == "/manifest.json"` bersifat minimal serta menutup celah cache nyata.
- **Proposed Edit:** Tambahkan langkah di Bagian 6 (`edutrack/web/api.py`) untuk menyertakan `path == "/manifest.json"` pada header `Cache-Control: no-cache, must-revalidate`, dan tambahkan penjelasan singkat di Bagian 3.3 #1 mengenai `skipWaiting()`/`clients.claim()` pada `sw.js` serta perilaku pembaruan ikon home screen OS.

#### Isu #4 — Kelengkapan Kasus Uji Fallback & Tanda Tangan Metode di Test Plan
- **Persona Peninjau:** Implementation Readiness
- **Severity:** `Major`
- **Affected Scope:** Bagian 6 Langkah 3 butir 9 & Bagian 7
- **Discrepancy Description:** Cabang fallback `serve_index()` (`api.py:435`) belum masuk kasus uji, dan rincian pemanggilan `GradeService.generate_grade_import_template(teacher, assessment_id)` (dengan isolasi `tempfile.TemporaryDirectory()` + `openpyxl.load_workbook`) serta inspeksi/pemanggilan `_render_pdf` belum eksplisit.
- **Rationale:** Menyisakan keputusan implementasi uji bagi pelaksana (melanggar *Zero-Decision Rule*) dan berisiko membuat tes menyentuh `edutrack_data.db` lokal.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Temuan valid; melengkapi kontrak uji membuat eksekusi Fase 5 deterministik 100%.
- **Proposed Edit:** Rincikan di Bagian 6 butir 9: (a) uji fallback JSON `serve_index` saat `index.html` tidak ada, (b) setup `AppConfig(db_path=...)` di `TemporaryDirectory` + `GradeService.generate_grade_import_template` + `openpyxl.load_workbook(io.BytesIO(data))`, (c) `inspect.signature(_render_pdf).parameters["badge_text"].default` + pemanggilan `_render_pdf` menghasilkan `%PDF`, dan (d) verifikasi `GET /sw.js` serta perintah grep/JSON/XML deterministik di Bagian 7.

#### Isu #5 — Pelanggaran *Anti-Weeds* & Konteks Audit Permukaan Pengguna di `FeatureRange`
- **Persona Peninjau:** Comprehension, Zoom Out
- **Severity:** `Major`
- **Affected Scope:** Bagian 1–3 (`FeatureRange`)
- **Discrepancy Description:** Nomor baris kode berulang di `FeatureRange` (duplikasi dengan `DetailedRange`), serta belum dijelaskan bahwa JS frontend/nama file unduhan/caller `_render_pdf` sudah diaudit bersih dan `#st-header-name` ditimpa nama siswa saat runtime oleh `student.js`.
- **Rationale:** Meningkatkan keterbacaan bagi pembaca baru tanpa konteks proyek dan memisahkan abstraksi arsitektur dari detail baris kode.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Temuan *Comprehension Gap* dan *Altitude Control* valid.
- **Proposed Edit:** Hapus nomor baris spesifik dari Bagian 3.1 (pertahankan hanya di Bagian 6), tambahkan ringkasan hasil audit kebersihan permukaan (JS, `Content-Disposition`, caller `_render_pdf`), dan jelaskan peran runtime `#st-header-name` serta kondisi pemicu fallback `serve_index`.

#### Isu #6 — Panjang `"short_name": "Bahasa Indonesia"` (16 Karakter) di `manifest.json`
- **Persona Peninjau:** Comprehension, Design Critic
- **Severity:** `Major`
- **Affected Scope:** Bagian 3.1 & Bagian 4 (`manifest.json`)
- **Discrepancy Description:** `"short_name": "Bahasa Indonesia"` (16 karakter) melampaui rekomendasi Lighthouse/PWA (~12 karakter) sehingga berpotensi terpotong menjadi `"Bahasa Ind..."` di home screen ponsel.
- **Rationale:** Alternatif singkatan (`"B. Indonesia"` atau `"BI"`) belum didokumentasikan sebagai trade-off di Bagian 4.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Sesuai instruksi pemilik proyek agar nama aplikasi adalah `"Bahasa Indonesia"`, kita pertahankan `"Bahasa Indonesia"` dan catat secara eksplisit trade-off pemotongan label di Bagian 4 (kecuali pengguna memilih menyingkatnya pada gerbang resolusi).
- **Proposed Edit:** Tambahkan Alternatif C di Bagian 4 mengenai `short_name` singkat (`"B. Indonesia"`) dan catat keputusan mempertahankan `"Bahasa Indonesia"` demi konsistensi merek penuh.

#### Isu #7 — Penamaan Berkas Uji Berversi Patch (`egm_v8_2_1_rebrand_test.py`) & Cek `CACHE_NAME`
- **Persona Peninjau:** Zoom Out
- **Severity:** `Major`
- **Affected Scope:** Bagian 2.1 #4 & Bagian 6 Langkah 3 butir 9
- **Discrepancy Description:** Nama berkas uji terikat versi patch (`egm_v8_2_1_rebrand_test.py`) dan asersi literal `CACHE_NAME == "edutrack-shell-v8.2.1"` dinilai berpotensi menjadi *brittle test* pada rilis berikutnya.
- **Rationale:** Tes yang mengunci string versi spesifik bisa gagal saat versi dinaikkan di rilis selanjutnya.
- **AI Suggestion:** `CONTEST` (untuk penamaan berkas) + `PROPOSE FIX` (untuk fleksibilitas asersi `CACHE_NAME`)
- **Justification:** Bukti terverifikasi di codebase (`edutrack/tests/egm_v2_integration_test.py`, `egm_v3_integration_test.py`, `egm_v6_features_test.py`, `egm_v7_hardening_test.py`, `egm_v8_bugfix_test.py`, `egm_v8_2_corrections_ews_test.py`) menunjukkan seluruh uji integrasi EGM di repositori ini memang mengikuti konvensi penamaan berbasis versi `egm_v<versi>_<fitur>_test.py`. Namun, untuk `CACHE_NAME`, asersi dapat memeriksa `assertNotIn('edutrack-shell-v8.2"', sw_text)` + kecocokan pola `edutrack-shell-v8.2.1` (atau `re.search(r'edutrack-shell-v\d+\.\d+\.\d+', sw_text)`) agar tidak rapuh di masa depan.
- **Proposed Edit:** Pertahankan nama berkas `edutrack/tests/egm_v8_2_1_rebrand_test.py` sesuai konvensi repositori, dan ubah asersi `sw.js` agar memverifikasi cache v8.2 lama sudah diganti (`not in`) dan format `CACHE_NAME` valid.

---

### Nit

#### Isu #8 — `icon.svg` Memakai `rx="112"` dengan `"purpose": "any maskable"`
- **Persona Peninjau:** Design Critic
- **Severity:** `Nit` (diklasifikasikan Major oleh Design Critic; dipertahankan catatan risiko)
- **Affected Scope:** Bagian 3.2 & `manifest.json`
- **Discrepancy Description:** Sudut membulat `rx="112"` pada `icon.svg` dapat menampakkan sudut transparan bila peluncur Android memakai masker kotak dengan radius lebih kecil.
- **Rationale:** Menjaga 1 file `icon.svg` mengikuti struktur baseline v8.2; mengubah `rx="0"` akan membuat favicon tab browser menjadi kotak tajam.
- **AI Suggestion:** `PROPOSE FIX` (dokumentasikan trade-off baseline di Bagian 3.2)
- **Justification:** Tidak perlu menambah file ikon kedua (YAGNI), cukup mencatat keterbatasan baseline ini di spesifikasi.
- **Proposed Edit:** Tambahkan catatan di Bagian 3.2 bahwa `rx="112"` dipertahankan konsisten dengan baseline v8.2 agar tampilan favicon tetap membulat elegan.

#### Isu #9 — Pengecualian Eksplisit `README.md`, `edutrack/README.md`, dan `main.py:187` di Non-Goals
- **Persona Peninjau:** Codebase Auditor
- **Severity:** `Nit`
- **Affected Scope:** Bagian 2.2 butir 3
- **Discrepancy Description:** `README.md`, `edutrack/README.md`, dan deskripsi CLI `argparse` di `edutrack/main.py:187` belum disebut eksplisit di Non-Goals.
- **Rationale:** Mencegah ambiguitas saat audit grep pasca-implementasi.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Tambahan 1 baris yang meningkatkan kejelasan batas ruang lingkup.
- **Proposed Edit:** Tambahkan `README.md`, `edutrack/README.md`, dan `edutrack/main.py` (`argparse description`) secara eksplisit pada Bagian 2.2 butir 3.

#### Isu #10 — Catatan Risiko *Clipping* `.sidebar-brand-text` pada Skala Font Aksesibilitas `>= 125%`
- **Persona Peninjau:** Design Critic / Codebase Auditor
- **Severity:** `Nit`
- **Affected Scope:** Bagian 3.3 & `edutrack/web/static/styles.css`
- **Discrepancy Description:** Pada zoom `100%`, `"Bahasa Indonesia"` masih muat di sidebar `256px`, tetapi pada skala font aksesibilitas `>= 125%` teks bisa terpotong tanpa elipsis.
- **Rationale:** `styles.css` tidak masuk ruang lingkup perubahan minimal v8.2.1; cukup dicatat atau dibiarkan tanpa menyentuh CSS.
- **AI Suggestion:** `DECLINE`
- **Justification:** Risiko minor hanya pada skala font ekstrem dan menyentuh `styles.css` akan memaksa pembaruan cache-bust `?v=20261120-v8.2` di 7 berkas lain.

#### Isu #11 — Penyebutan `ContextVar` di `database.py` Tanpa Penjelasan Singkat
- **Persona Peninjau:** Comprehension
- **Severity:** `Nit`
- **Affected Scope:** Bagian 2.2 butir 1
- **Discrepancy Description:** `ContextVar di database.py` disebut tanpa menjelaskan nama variabel internalnya (`edutrack_pg_req_holder`).
- **Rationale:** Pembaca baru tidak langsung tahu kaitannya dengan merek `edutrack`.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Penambahan nama `edutrack_pg_req_holder` dalam tanda kurung memperjelas konteks secara instan.
- **Proposed Edit:** Ubah menjadi `ContextVar("edutrack_pg_req_holder")` di Bagian 2.2 butir 1.
