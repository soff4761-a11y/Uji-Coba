# Spesifikasi Desain EduTrack v8 — Perbaikan CSRF, Konsistensi Logika Perhitungan, & Validasi Kasus Tepi

- **Dokumen:** `docs/designs/egm_v8_csrf_logic_validation_spec.md`
- **Status:** Resolved — Siap Implementasi (Zero-Decision Passed)
- **Tanggal:** 2026-11-20
- **Laporan Review:** `docs/designs/goldfish_review_report_v8.md` (`Status: resolved`)

---

## 1. Ringkasan Kontrak Final (Hasil Resolusi Goldfish)

1. **Double-Submit CSRF (`api.py`, `js/api.js`, `sw.js`, `index.html`, modul JS)**:
   - `_set_auth_cookies` memakai `path="/"` eksplisit pada `edutrack_session` dan `edutrack_csrf`.
   - `GET /api/auth/me` menerima query opsional `refresh_csrf: bool = False`. Jika cookie `edutrack_session` hadir dan (`not request.cookies.get(cfg.csrf_cookie_name)` atau `refresh_csrf=True`), server menerbitkan cookie `edutrack_csrf` baru (`path="/"`).
   - `js/api.js`:
     - `getCsrfToken()` mengambil nilai terakhir `edutrack_csrf` dari `document.cookie`.
     - `ensureCsrfCookie(forceRefresh = false)` memakai *shared in-flight promise* (`csrfRefreshPromise`) dengan `fetch(..., { credentials: "same-origin", cache: "no-store" })` agar request paralel tidak saling menimpa token, dan mengembalikan `res.ok`.
     - Pada mutasi (`POST/PUT/PATCH/DELETE`, bukan `/api/auth/login`): jika token kosong, panggil `ensureCsrfCookie(false)` sekali. Jika respons tetap `403 csrf_failed` dan `!_csrfRetried`, panggil `ensureCsrfCookie(true)` dan lakukan retry tunggal hanya jika `ok && getCsrfToken()`.
   - Cache-bust PWA diperbarui ke `v=20261120-v8` dan `CACHE_NAME = "edutrack-shell-v8"`.
2. **Konsistensi Logika Perhitungan (`analytics_service.py`, `grade_service.py`, `report_service.py`)**:
   - `get_teacher_dashboard`: kumpulkan `ews_candidates` untuk seluruh siswa (bukan hanya `attention_students`) lalu umpankan ke `_build_ews_summary_from_attention`; urutkan asesmen berdasarkan `(a.assessment_date, a.id)` sebelum membangun `chrono_scores`; hitung `mastery_count` & `mastery_percentage` per siswa berdasarkan `cls.mastery_threshold` masing-masing kelas. Urutkan `grade_rows` berdasarkan `(str(r["assessment_date"]), int(r["assessment_id"]))` di `_build_student_analytics`.
   - `get_class_gradebook`: `final_score` (dan `is_mastered`, `statistics`) hanya memasukkan asesmen berstatus `AssessmentStatus.PUBLISHED` agar identik dengan `material_averages` (jika hanya ada `DRAFT`, `final_score` dan `is_mastered` bernilai `None`). `export_class_grades` memberi label `(Draft)` pada kolom asesmen non-published.
   - `save_grades_bulk`: pra-validasi seluruh baris terlebih dahulu (`student_id` integer valid, tolak duplikat `student_id`, otorisasi kepemilikan guru, parsing `score` termasuk string spasi -> `None`, `math.isfinite()`, `normalize_score`) sebelum memanggil `upsert_grade`.
   - `_build_kkm_distribution(scores, kkm)` di `report_service.py`: bucket distribusi dinamis mengikuti `cls.mastery_threshold`, menangani `kkm <= 0`, `kkm >= 100`, KKM desimal (`f"{v:g}"`), dan fallback 2-bucket untuk KKM ekstrem (`low_cut <= 0` atau `high_cut >= 100`).
3. **Validasi Input & Kasus Tepi (`app_config.py`, `grade_service.py`, `academic_repo.py`, `attendance_service.py`, `student_service.py`, `classroom_service.py`)**:
   - `AppConfig.__post_init__`: tolak `session_idle_timeout_minutes <= 0`.
   - `create_assessment` & `update_assessment`: cek `math.isfinite()` untuk `max_score` & `weight`; tolak string kosong pada `category` & `assessment_date` di `update_assessment`.
   - `_parse_and_validate_grade_import` (serta `import_students` & `_parse_student_import_rows` di `student_service.py`): bungkus `openpyxl.load_workbook(...)` dan pembacaan `ws.iter_rows(...)` dalam `try/except Exception` -> `ValidationError` dengan `finally: wb.close()` dan cek `ws is None`.
   - `academic_repo.list_student_enrollments`: sertakan kolom `c.period_id`.
   - `grade_service.get_student_published_grades`: resolusi `classroom` secara deterministik (untuk `period_id`: `records[-1]["class_id"]`, lalu enrollment dengan `period_id`, else `None`; untuk `period_id is None`: `current_class_id`, lalu `records[-1]["class_id"]`, else `None`), gunakan `CalculationMode.WEIGHTED` bila `classroom is None`.
   - `attendance_service.py`: validasi ketat `YYYY-MM-DD` (`re.fullmatch` + `datetime.strptime`) pada `create_session` dan `update_session` (meneruskan nilai ter-strip).
   - `student_service._slugify_username`: bersihkan seluruh karakter non-alfanumerik (`re.sub(r"[^a-zA-Z0-9]+", "", ...)`), dan gunakan ulang helper yang sama di `reset_student_credentials`.
   - Ganti `assert ... is not None` dengan `if ... is None: raise NotFoundError(...)` di `classroom_service.py`, `grade_service.py`, dan `student_service.py`.

---

## 2. Target Scope & File Boundary (Final Allowlist Fase 5)

### File yang Diubah
1. `edutrack/web/api.py`
2. `edutrack/web/static/js/api.js`
3. `edutrack/web/static/app.js`
4. `edutrack/web/static/index.html`
5. `edutrack/web/static/sw.js`
6. `edutrack/web/static/js/charts.js`
7. `edutrack/web/static/js/teacher.js`
8. `edutrack/web/static/js/student.js`
9. `edutrack/services/analytics_service.py`
10. `edutrack/services/grade_service.py`
11. `edutrack/services/report_service.py`
12. `edutrack/configs/app_config.py`
13. `edutrack/repositories/academic_repo.py`
14. `edutrack/services/attendance_service.py`
15. `edutrack/services/student_service.py`
16. `edutrack/services/classroom_service.py`

### File Baru
17. `edutrack/tests/egm_v8_bugfix_test.py`
18. `docs/designs/egm_v8_csrf_logic_validation_spec.md`
19. `docs/designs/goldfish_review_report_v8.md`

---

## 3. Verifikasi Akhir
- `node --check edutrack/web/static/app.js edutrack/web/static/sw.js edutrack/web/static/js/*.js`
- `python3 -m unittest discover -s edutrack/tests -p "*_test.py" -v`
- `python3 -O -m unittest edutrack/tests/egm_v8_bugfix_test.py -v`
