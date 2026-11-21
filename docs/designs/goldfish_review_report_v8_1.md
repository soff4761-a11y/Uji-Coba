# Laporan Peninjauan Goldfish — EduTrack v8.1 (`renderDonutChart` & Grafik Frontend)

- **Status:** resolved
- **Dokumen Target:** `docs/designs/egm_v8_1_frontend_chart_fix_spec.md`
- **Tanggal:** 2026-11-20
- **Peninjau Goldfish Terisolasi:** Comprehension Goldfish, Design Critic Goldfish, Codebase Auditor Goldfish, Implementation Readiness Goldfish

---

## Ringkasan Temuan & Resolusi

| # | Persona | Severity | Affected Scope | Keputusan | Ringkasan Resolusi |
|---|---|---|---|---|---|
| 1 | Design Critic | Blocker | `charts.js` (`renderLineChart`) | `PROPOSE FIX` (Diterapkan) | Wajibkan `escapeHtml(...)` pada setiap interpolasi `name`, `label`, dan `value` di `<title>`, label sumbu X, dan legenda. |
| 2 | Design Critic | Blocker | `charts.js` (`renderLineChart`) | `PROPOSE FIX` (Diterapkan) | Tetapkan fallback aman untuk `xLabels.length === 1` (`x = w / 2`) dan `rangeY === 0` (`pad = Math.max(5, Math.abs(rawMax) * 0.1 || 10)`, `rangeY = Math.max(1, maxY - minY)`). |
| 3 | Design Critic | Blocker | `charts.js` (`renderLineChart`) | `PROPOSE FIX` (Diterapkan) | Bangun union terurut `xLabels` lintas semua seri dan petakan titik tiap seri berdasarkan `label` ke indeks sumbu X (label absen diperlakukan sebagai `null`). |
| 4 | Implementation Readiness | Blocker | `egm_v8_bugfix_test.py` (`test_6`) | `PROPOSE FIX` (Diterapkan) | Jalankan uji runtime Node dengan menyalin `state.js` & `charts.js` ke `TemporaryDirectory` berisi `package.json` (`{"type":"module"}`) dan menghapus query `?v=...` pada salinan temporer. |
| 5 | Codebase Auditor, Implementation Readiness | Major | `charts.js` vs `styles.css` (`.chart-box`) | `PROPOSE FIX` (Diterapkan) | Bungkus legenda (di atas grafik, saat `seriesList.length > 1 || seriesList.some(s => s.name)`) dan `.chart-scroll` di dalam satu `<div style="width:100%;display:flex;flex-direction:column;gap:0.5rem;">` agar tetap vertikal di dalam `.chart-box` tanpa mengubah `styles.css`. |
| 6 | Design Critic, Comprehension, Implementation Readiness | Major | `charts.js`, `teacher.js` | `PROPOSE FIX` (Diterapkan) | Perketat validasi angka (tolak `""`, spasi, boolean), render label sumbu X sekali saja, gunakan `<path>` hanya untuk segmen `>= 2` titik valid sambil selalu merender `<circle>` untuk titik terisolasi, tampilkan label nilai statis hanya pada seri tunggal, dan jaga `att || {}` serta `Array.isArray(data)`. |
| 7 | Design Critic | Major | `egm_v8_bugfix_test.py` (`test_6`) | `PROPOSE FIX` (Diterapkan) | Tambahkan asersi bahwa tidak ada sisa `?v=20261120-v8` (tanpa `.1`) maupun `renderDonutChart` di seluruh `edutrack/web/static/`. |
| 8 | Codebase Auditor, Comprehension | Nit | Bagian 1.3, 5, 6.4 | `PROPOSE FIX` (Diterapkan) | Selaraskan catatan cache-bust pada Bagian 5 dan tegaskan `openAttSession` dideklarasikan sebagai `async function` lokal yang ditautkan ke `window.openAttSession`. |
