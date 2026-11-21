# Laporan Peninjauan Goldfish — EduTrack v8

- **Status:** resolved
- **Dokumen Target:** `docs/designs/egm_v8_csrf_logic_validation_spec.md`
- **Tanggal:** 2026-11-20
- **Peninjau Goldfish Terisolasi:** Comprehension Goldfish, Design Critic Goldfish, Codebase Auditor Goldfish, Implementation Readiness Goldfish

---

## Ringkasan Temuan & Resolusi

| # | Persona | Severity | Affected Scope | Keputusan | Ringkasan Resolusi |
|---|---|---|---|---|---|
| 1 | Codebase Auditor, Implementation Readiness | Blocker | `academic_repo.py`, `grade_service.py` (`get_student_published_grades`), Bagian 6 | `PROPOSE FIX` (Diterapkan) | Tambahkan `c.period_id` pada `list_student_enrollments`, masukkan `academic_repo.py` ke `Target Scope`, gunakan `records[-1]["class_id"]` / enrollment `period_id`, dan kembalikan `"classroom": None` jika periode historis kosong tanpa fallback ke kelas periode lain. |
| 2 | Design Critic, Implementation Readiness | Blocker | `api.py` (`GET /api/auth/me`), `js/api.js` | `PROPOSE FIX` (Diterapkan) | Tambahkan parameter `refresh_csrf: bool = False` pada `GET /api/auth/me` untuk pemulihan cookie mismatch/residu, deduplikasi *in-flight promise* di `js/api.js`, `cache: "no-store"`, dan cek `res.ok` sebelum single retry. |
| 3 | Design Critic, Implementation Readiness | Blocker | `grade_service.py` (`save_grades_bulk`), Bagian 4 | `PROPOSE FIX` (Diterapkan) | Klarifikasi batas atomisitas pra-validasi, tolak `student_id` duplikat/non-integer dengan `ValidationError`, tangani string spasi sebagai `None`, dan validasi `float` + `math.isfinite()`. |
| 4 | Codebase Auditor, Comprehension | Major | `grade_service.py` (`get_class_gradebook`), `report_service.py` (`export_class_grades`) | `PROPOSE FIX` (Diterapkan) | Tetapkan perilaku tepi saat hanya ada asesmen `DRAFT` (`final_score=None`, `is_mastered=None`), dan beri tanda `(Draft)` pada header kolom asesmen draf di `export_class_grades`. |
| 5 | Design Critic, Implementation Readiness, Codebase Auditor | Major | `report_service.py` (`_build_kkm_distribution`) | `PROPOSE FIX` (Diterapkan) | Tetapkan rumus batas eksplisit untuk `kkm <= 0`, `kkm >= 100`, KKM desimal, serta fallback 2-bucket untuk KKM ekstrem (`0.1`, `99.9`), dan rapikan format label tunggal `.. <`. |
| 6 | Codebase Auditor, Comprehension | Major | `classroom_service.py`, `grade_service.py`, `student_service.py` | `PROPOSE FIX` (Diterapkan) | Ganti seluruh `assert ... is not None` produksi pada ketiga file layanan target dengan `if ... is None: raise NotFoundError(...)`, selaraskan `_slugify_username` di `reset_student_credentials`, dan tambahkan `try/except` + `wb.close()` pada impor `.xlsx` siswa. |
| 7 | Codebase Auditor, Implementation Readiness | Major | Bagian 6, 7.4, 7.7 | `PROPOSE FIX` (Diterapkan) | Hapus `js/state.js` dari `Target Scope`, tetapkan `js/charts.js` secara pasti, cantumkan impor `CalculationMode`, `re`, `datetime`, cek `ws is None` di `try/finally: wb.close()`, dan teruskan tanggal ter-strip di `update_session`. |
| 8 | Implementation Readiness | Major | Bagian 8 & 9 (Test Plan & Phasing) | `PROPOSE FIX` (Diterapkan) | Lengkapi skenario uji untuk seluruh cabang baru (`refresh_csrf`, non-overwrite CSRF, KKM desimal/ekstrem, fallback `classroom=None`, `update_session`, `python3 -O`) serta perintah `node --check`. |
| 9 | Design Critic | Major | `analytics_service.py` (`get_teacher_dashboard`, `get_early_warning_report`) | `CONTEST` | Kedua fungsi sudah berbagi fungsi evaluasi kanonik tunggal `_build_ews_summary_from_attention` (berbasis `final_score < kkm` dan `alpa_count >= alpa_threshold`); celah sebelumnya semata karena `get_teacher_dashboard` mengumpankan subset `attention_students` alih-alih seluruh siswa. |
| 10 | Design Critic | Nit | `grade_service.py` (`create_assessment` date format) | `DECLINE` | Validasi ketat `YYYY-MM-DD` dibatasi pada `attendance_service.py` sesuai permintaan guna menghindari regresi kompatibilitas input tanggal historis pada asesmen. |
