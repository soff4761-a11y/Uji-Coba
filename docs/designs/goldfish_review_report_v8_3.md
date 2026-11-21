# Laporan Peninjauan Goldfish — Tugas Dinilai vs. Checklist & Modal EWS Tengah Anti-Slop (v8.3)

- **Status:** `resolved` (Auto accept oleh pengguna — seluruh PROPOSE FIX diterapkan pada Fase 5)
- **Dokumen Target:** `docs/designs/egm_v8_3_ungraded_tasks_ews_modal_spec.md`
- **Peninjau Terisolasi:** Comprehension & Zoom Out, Design Critic & Codebase Auditor, Implementation Readiness
- **Ringkasan Temuan (Setelah Deduplikasi):** `4 Blocker` | `6 Major` | `2 Nit` | `0 Escalate`

---

## Daftar Temuan & Kategorisasi Resolusi (`egm-resolve`)

### Blocker

#### Isu #1 — Isolasi `is_graded` Terlewat di `GradeService.get_class_gradebook` & `get_student_published_grades`
- **Persona Peninjau:** Codebase Auditor, Implementation Readiness
- **Severity:** `Blocker`
- **Affected Scope:** `edutrack/services/grade_service.py` (baris 268–302, 377–424), `edutrack/services/report_service.py` (`export_class_grades`, baris 644–686), Spesifikasi Bagian 3.2 & 6.4–6.5
- **Discrepancy Description:** `get_class_gradebook` dan `get_student_published_grades` belum menyaring `asmt.is_graded`, sehingga pada mode `UNWEIGHTED` (atau fallback saat belum ada nilai angka) checklist tercentang (`1.0 / 1.0`) terhitung sebagai `100.0` pada `final_score`, `material_averages`, `statistics`, dan ekspor nilai kelas.
- **Rationale:** Melanggar Goal 4 (isolasi 100% tugas checklist dari perhitungan nilai akhir/KKM).
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Temuan kritis terverifikasi langsung di `grade_service.py` dan `grading.py`.
- **Proposed Edit:** Saring `if not asmt.is_graded: continue` pada perhitungan `items`, `mat_buckets`, dan `statistics` di `get_class_gradebook`, `get_student_published_grades`, serta `export_class_grades` (`assessments = [a for a in gb["assessments"] if a.is_graded]`), sementara `get_class_gradebook` tetap mengembalikan seluruh `assessments` agar dropdown Buku Nilai guru menampilkan keduanya.

#### Isu #2 — Celah Sinkronisasi EWS Guru vs. Siswa & Pencemaran Grafik `AnalyticsService`
- **Persona Peninjau:** Design Critic / Codebase Auditor, Implementation Readiness
- **Severity:** `Blocker`
- **Affected Scope:** `edutrack/services/analytics_service.py` (`get_teacher_dashboard`, `_build_ews_summary_from_attention`, `get_early_warning_report`, `_build_student_analytics`), Spesifikasi Bagian 3.2 & 6.5
- **Discrepancy Description:** `_build_ews_summary_from_attention` masih menduplikasi logika EWS lama tanpa `evaluate_student_ews` maupun `unsubmitted_checklist_count`; `component_averages` dan `chrono_scores` belum disaring `is_graded = True`; serta penghitungan `unsubmitted_checklist_count` harus selalu lintas seluruh materi kelas (hanya `status == published` dan `is_graded == False`, bebas filter `material_id`).
- **Rationale:** Tanpa penyatuan ini, status EWS guru dan siswa akan divergen dan grafik rata-rata komponen tercemar angka `100.0`.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Temuan kritis terverifikasi langsung di `analytics_service.py`.
- **Proposed Edit:** Delegasikan evaluasi di `_build_ews_summary_from_attention` ke `evaluate_student_ews`, saring `is_graded = True` pada `component_averages` dan `chrono_scores`, hitung `unsubmitted_checklist_count` khusus dari asesmen kelas `published` & `is_graded == False` (mengabaikan filter `material_id`), dan perbarui panel EWS guru (`index.html`, `teacher.js`) untuk menampilkan pemicu tugas checklist.

#### Isu #3 — Transisi `is_graded`, Edit/Simpan/Reset Buku Nilai, dan Impor Excel pada Tugas Checklist
- **Persona Peninjau:** Comprehension / Zoom Out, Design Critic / Codebase Auditor, Implementation Readiness
- **Severity:** `Blocker`
- **Affected Scope:** `edutrack/services/grade_service.py` (`update_assessment`, `generate_grade_import_template`, `_parse_and_validate_grade_import`), `edutrack/web/static/js/teacher.js` (`loadGradesTab`, `form-assessment`, `btn-edit-assessment`, `btn-reset-grades`, `btn-save-grades`), Spesifikasi Bagian 3.1, 6.4 & 6.6
- **Discrepancy Description:** (a) Belum ada aturan mutabilitas jika `is_graded` diubah pada asesmen yang sudah memiliki data nilai; (b) `update_assessment` harus memakai `effective_is_graded = existing.is_graded if is_graded is None else bool(is_graded)`; (c) `#btn-save-grades` akan melempar `TypeError` jika `.score-input` diganti checkbox tanpa percabangan `.checklist-input`; (d) `e.target.reset()` tidak menghapus atribut `disabled` pada `#a-max`/`#a-weight`; (e) `#btn-edit-assessment`, `#btn-reset-grades`, dan impor Excel pada tugas checklist belum ditentukan.
- **Rationale:** Melanggar *Zero-Decision Rule* dan berisiko menimbulkan error runtime atau korupsi skor lama (`85.0` vs `1.0`).
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Seluruh celah terverifikasi langsung pada kode sumber.
- **Proposed Edit:** Tetapkan aturan eksplisit: (a) tolak perubahan `is_graded` dengan `ValidationError` jika asesmen sudah memiliki entri di `grades`; (b) gunakan `effective_is_graded` di `update_assessment`; (c) tolak unduh template & impor Excel pada tugas checklist dengan `ValidationError` yang jelas; (d) perbarui `#btn-save-grades` membaca `.checklist-input` (`checked ? 1.0 : null`), lewati prompt `max_score`/`weight` di `#btn-edit-assessment` untuk checklist, pertahankan `#btn-reset-grades` untuk mereset centang ke belum mengumpulkan, dan reset `disabled = false` pada `#a-max`/`#a-weight` pasca-submit `form-assessment`.

#### Isu #4 — Ketidaksesuaian Nama Simbol Codebase & Jumlah Berkas Allowlist (`15` vs `19`)
- **Persona Peninjau:** Codebase Auditor, Implementation Readiness
- **Severity:** `Blocker`
- **Affected Scope:** Bagian 3.2, Bagian 5 (`Target Scope & File Boundary`), Bagian 6 langkah 4–6
- **Discrepancy Description:** Subjudul Bagian 5 menulis `(15 berkas)` padahal daftarnya memuat 19 berkas eksisting; dokumen juga merujuk simbol fiktif `_serialize_assessment` (aktual: `_serialize`), `export_student_report` (aktual: `export_individual_progress`), `renderGradebook` (aktual: `loadGradesTab`), dan `el(...)` (aktual: `document.getElementById(...)`).
- **Rationale:** Allowlist dan nama simbol harus 100% akurat agar eksekusi Fase 5 tanpa ambiguitas.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Koreksi langsung berbasis verifikasi kode sumber.
- **Proposed Edit:** Pecah daftar Bagian 5 menjadi 19 berkas bernomor 1-ke-1 (`Berkas yang Diubah (19 berkas)` + `1 berkas baru`) dan perbaiki seluruh nama simbol ke nama aktual di codebase.

---

### Major

#### Isu #5 — Konsistensi Penutupan Modal EWS, Focus Trap/Restore, Deduplikasi Sesi, & Palet Kontras Lengkap
- **Persona Peninjau:** Comprehension, Design Critic, Implementation Readiness
- **Severity:** `Major`
- **Affected Scope:** Bagian 3.3, Bagian 6 langkah 7–8, Bagian 7, `edutrack/web/static/js/student.js`, `styles.css`, `egm_v8_2_corrections_ews_test.py`
- **Discrepancy Description:** (a) Klik *backdrop* luar bertentangan dengan arahan pemilik proyek agar siswa menutup modal secara sadar lewat tombol **Mengerti**; (b) belum ada *focus trap* `Tab`/`Shift+Tab`, pemulihan fokus (`previousFocus`), penguncian scroll latar, dan deduplikasi per sesi (agar ganti filter materi tidak memunculkan modal berulang); (c) nilai hex tombol `×`, `:focus-visible`, dan lencana checklist belum dicantumkan; (d) uji `egm_v8_2_corrections_ews_test.py` baris 150 masih mengecek `#student-ews-popup.ews-popup`.
- **Rationale:** Menjamin kepatuhan penuh pada keputusan pengguna dan Delivery Gate `anti-slop` (`R-25`, `R-32`, `R-34`).
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Perbaikan menyeluruh atas aksesibilitas dan perilaku modal.
- **Proposed Edit:** Nonaktifkan penutupan lewat klik *backdrop* (modal hanya ditutup via tombol **Mengerti**, tombol `×`, atau `Escape`), tambahkan *focus trap*, pemulihan fokus, scroll lock, deduplikasi `studentEwsShownInSession`, definisikan seluruh hex warna lencana checklist/tombol tutup/fokus terverifikasi `contrast_check.py`, dan rincikan pembaruan `egm_v8_2_corrections_ews_test.py` (mempertahankan kelas `.ews-popup` bersama `.ews-modal-backdrop` atau memperbarui asersi tes).

#### Isu #6 — Normalisasi Tipe Boolean `is_graded` antara SQLite (`0`/`1`) dan PostgreSQL (`True`/`False`)
- **Persona Peninjau:** Codebase Auditor
- **Severity:** `Major`
- **Affected Scope:** `edutrack/repositories/grade_repo.py` (`list_grades_for_class`, `list_grades_for_student`)
- **Discrepancy Description:** Driver SQLite mengembalikan `0`/`1` untuk `is_graded` sedangkan PostgreSQL mengembalikan `bool`; tanpa normalisasi eksplisit `bool(...)`, JSON dan pemeriksaan Python dapat divergen.
- **Rationale:** Menjamin paritas 100% SQLite lokal dan PostgreSQL/Supabase.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Penambahan `d["is_graded"] = bool(d.get("is_graded", 1))` di repositori menghilangkan seluruh kelas bug tipe data.
- **Proposed Edit:** Wajibkan konversi `bool(...)` pada `_row_to_assessment`, `list_grades_for_class`, dan `list_grades_for_student` di `grade_repo.py`.

#### Isu #7 — Akses Permintaan Koreksi Siswa untuk Tugas Checklist (`populateStudentCorrectionTargets`)
- **Persona Peninjau:** Design Critic / Codebase Auditor, Implementation Readiness
- **Severity:** `Major`
- **Affected Scope:** `edutrack/web/static/js/student.js` (`populateStudentCorrectionTargets`, baris 155–169)
- **Discrepancy Description:** Jika tugas checklist dipindah ke `checklist_tasks`, siswa tidak dapat memilih tugas checklist pada dropdown pengajuan koreksi padahal status belum mengumpulkan dapat memicu EWS.
- **Rationale:** Menjaga keadilan alur koreksi siswa terhadap seluruh tugas `published`.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Backend `submit_correction_request` sudah mendukungnya; cukup gabungkan `grade_timeline` dan `checklist_tasks` (dengan label `[Checklist]`) di dropdown koreksi siswa.
- **Proposed Edit:** Perbarui `populateStudentCorrectionTargets` di `student.js` agar menyertakan item `checklist_tasks` dengan label `[Checklist]`.

#### Isu #8 — Konsistensi Field Tanggal `checklist_tasks`, Filter `material_id`, dan Kasus Kelas Tanpa Tugas Dinilai
- **Persona Peninjau:** Comprehension, Implementation Readiness
- **Severity:** `Major`
- **Affected Scope:** Bagian 3.2 & Bagian 6 langkah 5 (`analytics_service.py`)
- **Discrepancy Description:** Nama field tanggal `checklist_tasks` (`assessment_date` vs `date` di `grade_timeline`), cakupan filter `material_id`, serta perilaku saat kelas hanya memiliki tugas checklist (0 tugas dinilai -> `final_score = None`, tidak memicu `below_kkm`) belum ditegaskan.
- **Rationale:** Menghilangkan ambiguitas kontrak JSON dan memastikan tidak ada error pembagian nol atau peringatan nilai rendah palsu.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Penetapan kontrak eksplisit memenuhi *Zero-Decision Rule*.
- **Proposed Edit:** Gunakan kunci `"date"` yang konsisten dengan `grade_timeline`, saring tampilan `checklist_tasks` mengikuti `material_id` bila dipilih (sementara hitungan EWS tetap lintas seluruh materi kelas), dan tegaskan bahwa 0 tugas dinilai menghasilkan `final_score = None` tanpa memicu `below_kkm`.

#### Isu #9 — Kejelasan Prosedur Rollback, Aturan Eskalasi EWS, & Definisi Istilah di `FeatureRange`
- **Persona Peninjau:** Comprehension / Zoom Out
- **Severity:** `Major`
- **Affected Scope:** Bagian 1, 3.2, 3.4 (`FeatureRange`)
- **Discrepancy Description:** Risiko downgrade ke v8.2.2 (v8.2.2 akan mengabaikan `is_graded`), definisi 2 pemicu EWS eksisting (`below_kkm`, `alpa_exceeded`) + eskalasi `kritis`, serta definisi istilah domain (`KKM`, `EWS`, `alpa`, `draft`/`published`) dan pemisahan detail implementasi dari `FeatureRange` perlu diperjelas.
- **Rationale:** Memperbaiki *Comprehension Gap* dan catatan operasional rollback.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Temuan pemahaman yang valid dan mudah dirapikan di Bagian 1–3.
- **Proposed Edit:** Tambahkan glosarium singkat, jelaskan 2 pemicu eksisting + pemicu ke-3 checklist, dan tuliskan prosedur rollback (termasuk risiko kompatibilitas mundur terhadap baris `is_graded = False`).

#### Isu #10 — Perintah Verifikasi `contrast_check.py` Tanpa Placeholder & Matriks Uji Lengkap
- **Persona Peninjau:** Implementation Readiness
- **Severity:** `Major`
- **Affected Scope:** Bagian 7
- **Discrepancy Description:** Perintah `contrast_check.py` masih mengandung `<skill_dir>` dan belum merinci pasangan hex lencana checklist serta skenario uji spesifik (`UNWEIGHTED`, migrasi v6 dari skema v5, `PATCH` parsial).
- **Rationale:** Perintah verifikasi harus siap eksekusi dan skenario uji harus deterministik.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Menyempurnakan kesiapan eksekusi Fase 5.
- **Proposed Edit:** Lengkapi Bagian 7 dengan daftar pasangan hex konkret dan matriks skenario uji `egm_v8_3_ungraded_tasks_ews_modal_test.py`.

---

### Nit

#### Isu #11 — Format Tampilan Riwayat Perubahan Nilai untuk Tugas Checklist & Fallback CSS Tema Default
- **Persona Peninjau:** Design Critic, Implementation Readiness
- **Severity:** `Nit`
- **Affected Scope:** `edutrack/web/static/js/teacher.js` (baris 487–488), `styles.css`, `egm_v8_bugfix_test.py` (baris 392)
- **Discrepancy Description:** Tabel riwayat perubahan nilai menampilkan angka mentah `1` alih-alih `Sudah Mengumpulkan` untuk checklist; gaya dasar `.ews-modal-dialog` sebaiknya langsung menargetkan tema gelap default sebelum override `[data-theme="light"]`; komentar `egm_v8_bugfix_test.py:392` diselaraskan ke `v8.3`.
- **Rationale:** Meningkatkan kejelasan UX guru dan ketahanan fallback CSS.
- **AI Suggestion:** `PROPOSE FIX`
- **Justification:** Perbaikan kecil bernilai tinggi tanpa menambah risiko.
- **Proposed Edit:** Terapkan ketiga penyempurnaan ini pada Fase 5.

#### Isu #12 — Penyebutan Nama Internal `EDUTRACK_` vs. Nama Tampilan `Bahasa Indonesia`
- **Persona Peninjau:** Comprehension
- **Severity:** `Nit`
- **Affected Scope:** Bagian 1 & Bagian 3.1
- **Discrepancy Description:** Prefiks env `EDUTRACK_` dipakai sementara nama tampilan aplikasi adalah `Bahasa Indonesia`.
- **Rationale:** Catatan satu kalimat mencegah kebingungan pembaca baru.
- **AI Suggestion:** `DECLINE` (atau catatan 1 baris di Bagian 1)
- **Justification:** Minor; dapat ditambah 1 catatan singkat saat menerapkan perbaikan lain.
