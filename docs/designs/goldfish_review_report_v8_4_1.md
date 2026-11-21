# Laporan Sintesis Review Goldfish v8.4.1

- **Dokumen Target**: `docs/designs/egm_v8_4_1_popup_theme_donut_distribution_spec.md`
- **Status**: `resolved` (Auto accept oleh pengguna)

## Ringkasan Temuan & Usulan Resolusi (`PROPOSE FIX`)

### Blocker (3)
1. **[B-1 | Regresi Tes v8.2] Selector `#student-ews-popup.ews-popup` wajib tetap literal di `styles.css`**: `egm_v8_2_corrections_ews_test.py:150` memeriksa string literal tersebut.
   - **Usulan (`PROPOSE FIX`)**: Pertahankan selector `#student-ews-popup.ews-popup`, `.ews-modal-dialog`, dan `#student-reveal-popup` secara eksplisit di `styles.css` saat menyatukan tema glassmorphism kedua modal.
2. **[B-2 | Regresi Tes Node v8.2] Guard `typeof` pada mock DOM minimal**: `egm_v8_2_corrections_ews_test.py:178-206` menggunakan mock DOM tanpa `el.querySelector` / `document.body.style` / `document.addEventListener`.
   - **Usulan (`PROPOSE FIX`)**: Pertahankan seluruh guard `typeof ... === "function"` di `showStudentEwsPopup` dan terapkan pola defensif yang sama di `showStudentRevealPopup`.
3. **[B-3 | WCAG 1.4.11 & Anti-Slop `R-25`/`R-34`] Warna 5 segmen donat `#chart-t-distribution` gagal kontras non-teks di mode terang**: Palet gelap (`#34d399`, `#38bdf8`, `#818cf8`, `#fbbf24`, `#f87171`) hanya `1.67:1–2.98:1` pada latar `#ffffff`.
   - **Usulan (`PROPOSE FIX`)**: Buat palet segmen donat distribusi nilai peka tema (dark: `#34d399`, `#38bdf8`, `#818cf8`, `#fbbf24`, `#f87171`; light: `#059669` `3.77:1`, `#0284c7` `4.10:1`, `#4f46e5` `6.29:1`, `#b45309` `5.02:1`, `#dc2626` `4.83:1`) dan re-render saat tema diganti bila diperlukan.

### Major (8)
4. **[M-1]** Pertahankan seluruh selector yang diuji tes v8.3/v8.4 (`ews-modal-dialog`, `#student-reveal-popup`, `prefers-reduced-motion`) secara literal di `styles.css`.
5. **[M-2]** Tambahkan null-guard `const dist = (gs && gs.distribution) || {};` di `teacher.js` dan tegaskan bahwa bucket bernilai `0 siswa` otomatis disembunyikan di legenda `renderDoughnutChart` (selaras dengan `#chart-t-attendance`).
6. **[M-3]** Pastikan `js/student.js` dan `js/teacher.js` juga ikut di-bump ke `?v=20261120-v8.4.1` (agar lulus scan rekursif `egm_v8_bugfix_test.py`).
7. **[M-4]** Perkuat border & latar tombol tutup `×` agar mencapai `>= 3.0:1` di kedua tema (dark: border `rgba(255, 255, 255, 0.40)`; light: latar `#f1f5f9` + border `#64748b`).
8. **[M-5]** Gunakan warna hex solid eksplisit pada aksen atas `3px` tiap modal per tema (`#fbbf24`/`#f87171`/`#14b8a6` di gelap; `#d97706`/`#dc2626`/`#0d9488` di terang) agar kontras jelas.
9. **[M-6]** Wajibkan `outline-offset: 2px` pada `:focus-visible` di kedua modal (mencegah konflik `1.00:1` pada tombol `#0369a1` di mode terang).
10. **[M-7]** Lengkapi kontrak aksesibilitas modal secara eksplisit (initial focus ke tombol utama, pengembalian fokus ke opener saat ditutup, kunci scroll body, serta `role="dialog"`, `aria-modal="true"`, `aria-labelledby`).
11. **[M-8]** Tambahkan `-webkit-backdrop-filter` untuk Safari/iOS, seragamkan lebar dialog `min(520px, 100%)` dan `max-height: calc(100dvh - 2rem)`, serta warna `:hover` lebih gelap (`#075985`, `#991b1b`, `#115e59`).

### Nit (5)
- Definisikan token `--modal-muted`, gabungkan blok `@media (prefers-reduced-motion: reduce)` menjadi satu blok, pertahankan `flex-wrap: wrap` pada footer modal, pertahankan ikon SVG EWS `.ews-popup-icon` bersama badge status, dan masukkan `egm_v8_2_corrections_ews_test.py` serta `egm_v8_3_ungraded_tasks_ews_modal_test.py` dalam rencana verifikasi.
