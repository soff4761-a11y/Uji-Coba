"""Pengujian regresi & kasus tepi menyeluruh untuk EduTrack v8 (EGM)."""

from __future__ import annotations

import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from edutrack.configs.app_config import AppConfig
from edutrack.domain.errors import NotFoundError, ValidationError
from edutrack.domain.models import AssessmentStatus, CalculationMode, StudentProfile
from edutrack.services.report_service import _build_kkm_distribution
from edutrack.services.student_service import _slugify_username
from edutrack.web.api import create_app


class EgmV8BugfixTest(unittest.TestCase):
  """Memverifikasi perbaikan CSRF, konsistensi logika perhitungan, dan validasi kasus tepi."""

  def setUp(self) -> None:
    self._tmpdir = tempfile.TemporaryDirectory()
    self._db_path = os.path.join(self._tmpdir.name, "edutrack_v8.db")
    self._cfg = AppConfig(
        db_path=self._db_path,
        backup_dir=os.path.join(self._tmpdir.name, "backups"),
        pbkdf2_iterations=10_000,
        seed_demo_data=False,
        high_absence_threshold_pct=20.0,
        ews_alpa_threshold=3,
    )
    self._app = create_app(self._cfg)
    self._container = self._app.state.container
    self._teacher = self._container.auth_service.register_teacher(
        "guru_v8", "PasswordGuru123!", "Guru V8"
    )

  def tearDown(self) -> None:
    self._tmpdir.cleanup()

  def _login(self, username: str, password: str) -> TestClient:
    client = TestClient(self._app)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    self.assertEqual(res.status_code, 200, res.text)
    csrf = client.cookies.get("edutrack_csrf", "")
    self.assertTrue(len(csrf) >= 16)
    client.headers["X-CSRF-Token"] = csrf
    return client

  # 1. CSRF Hydration, Refresh, & Path Consistency
  def test_1_csrf_hydration_on_auth_me_and_refresh_csrf(self) -> None:
    guru = self._login("guru_v8", "PasswordGuru123!")
    initial_csrf = guru.cookies.get("edutrack_csrf")

    # GET /api/auth/me normal TIDAK menimpa cookie CSRF yang sudah ada
    me_keep = guru.get("/api/auth/me")
    self.assertEqual(me_keep.status_code, 200)
    self.assertEqual(guru.cookies.get("edutrack_csrf"), initial_csrf)

    # Simulasi sesi pra-v7: edutrack_session ada, edutrack_csrf hilang
    guru.cookies.delete("edutrack_csrf")
    guru.headers.pop("X-CSRF-Token", None)
    blocked = guru.post("/api/teacher/classes", json={"name": "Gagal", "education_level": "SMA"})
    self.assertEqual(blocked.status_code, 403)
    self.assertEqual(blocked.json()["code"], "csrf_failed")

    # Memuat ulang /api/auth/me otomatis menerbitkan cookie edutrack_csrf baru
    me_hydrate = guru.get("/api/auth/me")
    self.assertEqual(me_hydrate.status_code, 200)
    hydrated_csrf = guru.cookies.get("edutrack_csrf", "")
    self.assertTrue(len(hydrated_csrf) >= 16)
    set_cookie_hdr = me_hydrate.headers.get("set-cookie", "")
    self.assertIn("Path=/", set_cookie_hdr)

    # Mutasi dengan token hasil hidrasi langsung sukses
    guru.headers["X-CSRF-Token"] = hydrated_csrf
    ok_cls = guru.post("/api/teacher/classes", json={"name": "Sukses CSRF", "education_level": "SMA"})
    self.assertEqual(ok_cls.status_code, 201, ok_cls.text)

    # refresh_csrf=1 memaksa rotasi cookie baru untuk pemulihan token mismatch
    me_rot = guru.get("/api/auth/me?refresh_csrf=1")
    self.assertEqual(me_rot.status_code, 200)
    rotated_csrf = guru.cookies.get("edutrack_csrf", "")
    self.assertTrue(len(rotated_csrf) >= 16)
    self.assertNotEqual(rotated_csrf, hydrated_csrf)

    # Verifikasi js/api.js memiliki auto-hydration + single retry + deduplikasi promise
    api_js = (
        Path(__file__).resolve().parent.parent / "web" / "static" / "js" / "api.js"
    ).read_text(encoding="utf-8")
    self.assertIn("csrfRefreshPromise", api_js)
    self.assertIn("/api/auth/me?refresh_csrf=1", api_js)
    self.assertIn("_csrfRetried", api_js)

  # 2. EWS Dashboard vs EWS Report Alignment
  def test_2_ews_dashboard_matches_ews_report_for_low_absence_pct_high_alpa(self) -> None:
    cls = self._container.classroom_service.create_classroom(
        self._teacher, name="X-EWS", education_level="SMA", mastery_threshold=75.0
    )
    stu = self._container.student_service.create_student_with_account(
        self._teacher, cls.id, "Bima Sakti", "2026101"
    )["student"]

    # Nilai tuntas (90 >= 75) dan tren stabil
    a1 = self._container.grade_service.create_assessment(
        self._teacher, cls.id, "UH 1", "UH", "2026-10-01", status=AssessmentStatus.PUBLISHED
    )
    a2 = self._container.grade_service.create_assessment(
        self._teacher, cls.id, "UH 2", "UH", "2026-10-10", status=AssessmentStatus.PUBLISHED
    )
    self._container.grade_service.save_grades_bulk(
        self._teacher, a1.id, [{"student_id": stu.id, "score": 90}]
    )
    self._container.grade_service.save_grades_bulk(
        self._teacher, a2.id, [{"student_id": stu.id, "score": 90}]
    )

    # 20 pertemuan: 17 hadir, 3 alpa -> absence_pct = 15% (< 20%) tetapi alpa_count = 3 (>= 3)
    for i in range(1, 21):
      ses = self._container.attendance_service.create_session(
          self._teacher, cls.id, f"2026-10-{i:02d}", i
      )["session"]
      status = "alpa" if i <= 3 else "hadir"
      self._container.attendance_service.save_session_attendance(
          self._teacher, ses.id, [{"student_id": stu.id, "status": status}]
      )

    dash = self._container.analytics_service.get_teacher_dashboard(self._teacher, class_id=cls.id)
    ews_rep = self._container.analytics_service.get_early_warning_report(self._teacher, class_id=cls.id)

    # Siswa TIDAK masuk attention_students (nilai 90, absensi 15% < 20%, tren stabil)
    self.assertEqual(len(dash["attention_students"]), 0)
    # Namun WAJIB masuk early_warning di dashboard DAN identik dengan get_early_warning_report
    self.assertEqual(dash["early_warning"]["total_flagged"], 1)
    self.assertEqual(ews_rep["total_flagged"], 1)
    self.assertEqual(dash["early_warning"]["students"][0]["student_id"], stu.id)
    self.assertEqual(dash["early_warning"]["students"][0]["triggers"], ["alpa_exceeded"])

  # 3. Gradebook Published-Only Consistency & Save Grades Bulk Pre-Validation
  def test_3_gradebook_published_only_and_save_grades_bulk_no_partial_commit(self) -> None:
    cls = self._container.classroom_service.create_classroom(
        self._teacher, name="X-GB", education_level="SMA", mastery_threshold=75.0
    )
    s1 = self._container.student_service.create_student_with_account(
        self._teacher, cls.id, "Citra Dewi", "2026201"
    )["student"]
    s2 = self._container.student_service.create_student_with_account(
        self._teacher, cls.id, "Dedi Kurnia", "2026202"
    )["student"]
    mat = self._container.grade_service.create_material(self._teacher, cls.id, "Bab 1")

    a_pub = self._container.grade_service.create_assessment(
        self._teacher, cls.id, "UH Pub", "UH", "2026-10-05", status=AssessmentStatus.PUBLISHED, material_id=mat.id
    )
    a_draft = self._container.grade_service.create_assessment(
        self._teacher, cls.id, "UH Draft", "UH", "2026-10-06", status=AssessmentStatus.DRAFT, material_id=mat.id
    )

    # save_grades_bulk: baris ke-2 invalid (nilai > max_score) -> baris ke-1 TIDAK boleh tersimpan!
    with self.assertRaises(ValidationError):
      self._container.grade_service.save_grades_bulk(
          self._teacher,
          a_pub.id,
          [
              {"student_id": s1.id, "score": 88},
              {"student_id": s2.id, "score": 150},
          ],
      )
    self.assertEqual(self._container.grade_repo.list_grades_for_assessment(a_pub.id), [])

    # Duplikat student_id juga ditolak sebelum menulis apa pun
    with self.assertRaises(ValidationError):
      self._container.grade_service.save_grades_bulk(
          self._teacher,
          a_pub.id,
          [
              {"student_id": s1.id, "score": 88},
              {"student_id": s1.id, "score": 90},
          ],
      )
    self.assertEqual(self._container.grade_repo.list_grades_for_assessment(a_pub.id), [])

    # Simpan valid: published = 90, draft = 20
    self._container.grade_service.save_grades_bulk(
        self._teacher, a_pub.id, [{"student_id": s1.id, "score": 90}]
    )
    self._container.grade_service.save_grades_bulk(
        self._teacher, a_draft.id, [{"student_id": s1.id, "score": 20}]
    )
    gb = self._container.grade_service.get_class_gradebook(self._teacher, cls.id)
    row_s1 = next(r for r in gb["rows"] if r["student_id"] == s1.id)
    # final_score & material_averages keduanya hanya memakai PUBLISHED (90.0, bukan 55.0)
    self.assertEqual(row_s1["final_score"], 90.0)
    self.assertEqual(row_s1["material_averages"][str(mat.id)], 90.0)
    # Kolom draft tetap tampil di scores agar guru bisa mengeditnya
    self.assertEqual(row_s1["scores"][a_draft.id]["score"], 20.0)

  # 4. Dynamic KKM Multi-Class, Chronological Trend, & Dynamic Report Buckets
  def test_4_dynamic_kkm_multiclass_chrono_trend_and_report_buckets(self) -> None:
    cls_a = self._container.classroom_service.create_classroom(
        self._teacher, name="Kelas KKM 70", education_level="SMA", mastery_threshold=70.0
    )
    cls_b = self._container.classroom_service.create_classroom(
        self._teacher, name="Kelas KKM 85", education_level="SMA", mastery_threshold=85.0
    )
    sa = self._container.student_service.create_student_with_account(
        self._teacher, cls_a.id, "Eka Putra", "2026301"
    )["student"]
    sb = self._container.student_service.create_student_with_account(
        self._teacher, cls_b.id, "Fani Lestari", "2026302"
    )["student"]

    # Input asesmen tidak urut tanggal (tgl belakangan dibuat duluan)
    a_late = self._container.grade_service.create_assessment(
        self._teacher, cls_a.id, "Ujian Akhir", "UAS", "2026-11-20", status=AssessmentStatus.PUBLISHED
    )
    a_early = self._container.grade_service.create_assessment(
        self._teacher, cls_a.id, "Ujian Awal", "UH", "2026-11-01", status=AssessmentStatus.PUBLISHED
    )
    # Eka: awal 60, akhir 84 -> rata-rata 72 (>= KKM 70 -> TUNTAS), tren Meningkat (+24)
    self._container.grade_service.save_grades_bulk(
        self._teacher, a_early.id, [{"student_id": sa.id, "score": 60}]
    )
    self._container.grade_service.save_grades_bulk(
        self._teacher, a_late.id, [{"student_id": sa.id, "score": 84}]
    )

    # Fani di kelas KKM 85: nilai 80 (< 85 -> BELUM TUNTAS, padahal >= default 75)
    ab = self._container.grade_service.create_assessment(
        self._teacher, cls_b.id, "UH B", "UH", "2026-11-10", status=AssessmentStatus.PUBLISHED
    )
    self._container.grade_service.save_grades_bulk(
        self._teacher, ab.id, [{"student_id": sb.id, "score": 80}]
    )

    # Dashboard gabungan (class_id=None) harus mengevaluasi KKM masing-masing kelas:
    # Eka tuntas (72 >= 70), Fani tidak tuntas (80 < 85) -> mastery_count=1, mastery_percentage=50.0
    combined = self._container.analytics_service.get_teacher_dashboard(
        self._teacher, class_id=None
    )
    self.assertEqual(combined["grade_statistics"]["mastery_count"], 1)
    self.assertEqual(combined["grade_statistics"]["mastery_percentage"], 50.0)
    # Eka tidak boleh masuk attention_students sebagai "Menurun" karena urutan kronologisnya 60 -> 84 (Meningkat)
    self.assertFalse(any(x["student_id"] == sa.id for x in combined["attention_students"]))

    # Distribusi bucket dinamis di report_service
    self.assertEqual(
        _build_kkm_distribution([55, 70, 80, 95], 75.0),
        {"<60": 1, "60-74": 1, "75-89": 1, "90-100": 1},
    )
    self.assertEqual(
        _build_kkm_distribution([50, 70, 85, 95], 80.0),
        {"<64": 1, "64-79": 1, "80-91": 1, "92-100": 1},
    )
    self.assertEqual(
        _build_kkm_distribution([50, 75.0, 80.0, 95.0], 75.5),
        {"<60.4": 1, "60.4..<75.5": 1, "75.5..<90.2": 1, "90.2-100": 1},
    )
    self.assertEqual(
        _build_kkm_distribution([0.05, 50.0], 0.1),
        {"<0.1": 1, "0.1-100": 1},
    )
    self.assertEqual(
        _build_kkm_distribution([50, 70, 85, 95], 0.0),
        {"0-59": 1, "60-79": 1, "80-89": 1, "90-100": 1},
    )
    self.assertEqual(
        _build_kkm_distribution([50, 70, 95, 100], 100.0),
        {"<60": 1, "60-79": 1, "80-99": 1, "100": 1},
    )
    pdf_bytes, mime, _ = self._container.report_service.export_class_grades(
        self._teacher, cls_b.id, "pdf"
    )
    self.assertEqual(mime, "application/pdf")
    self.assertTrue(pdf_bytes.startswith(b"%PDF"))

  # 5. Edge Cases & Input Validation
  def test_5_config_assessment_excel_historical_date_slugify_and_no_assert(self) -> None:
    # AppConfig session_idle_timeout_minutes <= 0
    with self.assertRaises(ValueError):
      AppConfig(session_idle_timeout_minutes=0)
    with self.assertRaises(ValueError):
      AppConfig(session_idle_timeout_minutes=-10)

    p1 = self._container.classroom_service.create_period(
        self._teacher, "2025/2026 Ganjil", "2025/2026", "Ganjil", is_active=True
    )
    cls1 = self._container.classroom_service.create_classroom(
        self._teacher, period_id=p1.id, name="X-1", education_level="SMA", calculation_mode=CalculationMode.UNWEIGHTED
    )
    # create_assessment menolak NaN & Inf
    for bad in (float("nan"), float("inf"), float("-inf")):
      with self.assertRaises(ValidationError):
        self._container.grade_service.create_assessment(
            self._teacher, cls1.id, "A", "UH", "2026-10-01", max_score=bad
        )
      with self.assertRaises(ValidationError):
        self._container.grade_service.create_assessment(
            self._teacher, cls1.id, "A", "UH", "2026-10-01", weight=bad
        )

    asmt = self._container.grade_service.create_assessment(
        self._teacher, cls1.id, "UH 1", "UH", "2026-10-01", status=AssessmentStatus.PUBLISHED
    )
    # update_assessment menolak category / assessment_date kosong
    with self.assertRaises(ValidationError):
      self._container.grade_service.update_assessment(self._teacher, asmt.id, category="   ")
    with self.assertRaises(ValidationError):
      self._container.grade_service.update_assessment(self._teacher, asmt.id, assessment_date="")

    # _parse_and_validate_grade_import berkas .xlsx korup -> ValidationError (bukan 500)
    with self.assertRaises(ValidationError):
      self._container.grade_service.preview_grade_import(
          self._teacher, asmt.id, "rusak.xlsx", b"bukan-berkas-xlsx-valid"
      )

    # get_student_published_grades untuk period_id historis setelah pindah kelas + current_class_id None
    created_stu = self._container.student_service.create_student_with_account(
        self._teacher, cls1.id, "Gita Savitri", "2026/001-A!"
    )
    self.assertEqual(created_stu["username"], "2026001A")
    self.assertEqual(_slugify_username("Budi", "2026/001-A!"), "2026001A")
    self.assertEqual(_slugify_username("Budi", "###"), "nis000")

    stu = created_stu["student"]
    self._container.grade_service.save_grades_bulk(
        self._teacher, asmt.id, [{"student_id": stu.id, "score": 88}]
    )
    p2 = self._container.classroom_service.create_period(
        self._teacher, "2026/2027 Ganjil", "2026/2027", "Ganjil", is_active=True
    )
    cls2 = self._container.classroom_service.create_classroom(
        self._teacher, period_id=p2.id, name="XI-1", education_level="SMA", calculation_mode=CalculationMode.WEIGHTED
    )
    self._container.student_service.move_student(self._teacher, stu.id, cls2.id)

    stu_user = self._container.user_repo.get_by_id(stu.user_id)
    assert stu_user is not None
    hist = self._container.grade_service.get_student_published_grades(stu_user, period_id=p1.id)
    self.assertEqual(hist["classroom"].id, cls1.id)
    self.assertEqual(hist["final_score"], 88.0)

    # Simulasi profile.current_class_id = None pada periode kosong -> tidak crash
    fake_profile = StudentProfile(
        id=stu.id,
        user_id=stu.user_id,
        teacher_id=stu.teacher_id,
        current_class_id=None,  # type: ignore[arg-type]
        student_code=stu.student_code,
        full_name=stu.full_name,
        username=stu.username,
        account_status=stu.account_status,
        notes="",
        created_at=stu.created_at,
    )
    with patch.object(self._container.academic_repo, "get_student_by_user_id", return_value=fake_profile):
      res_none = self._container.grade_service.get_student_published_grades(stu_user, period_id=9999)
      self.assertIsNone(res_none["classroom"])
      self.assertIsNone(res_none["final_score"])

    # Validasi format tanggal YYYY-MM-DD di attendance_service
    with self.assertRaises(ValidationError):
      self._container.attendance_service.create_session(self._teacher, cls2.id, "20-11-2026", 1)
    with self.assertRaises(ValidationError):
      self._container.attendance_service.create_session(self._teacher, cls2.id, "2026-02-30", 1)
    ok_ses = self._container.attendance_service.create_session(self._teacher, cls2.id, "2026-11-20", 1)["session"]
    with self.assertRaises(ValidationError):
      self._container.attendance_service.update_session(self._teacher, ok_ses.id, session_date="2026/11/21")

    # update_period_state & update_classroom aman terhadap python -O (raise NotFoundError, bukan assert)
    with patch.object(self._container.academic_repo, "set_period_state", return_value=None):
      with self.assertRaises(NotFoundError):
        self._container.classroom_service.update_period_state(self._teacher, p2.id, is_active=True)
    with patch.object(self._container.academic_repo, "update_classroom", return_value=None):
      with self.assertRaises(NotFoundError):
        self._container.classroom_service.update_classroom(self._teacher, cls2.id, name="Baru")


  # 6. Frontend Charts Regression (renderDonutChart removed, multi-series renderLineChart, cache-bust v8.1)
  def test_6_frontend_charts_no_renderDonutChart_and_multiseries_line_chart(self) -> None:
    static_dir = Path(__file__).resolve().parent.parent / "web" / "static"
    for fpath in static_dir.rglob("*"):
      if fpath.is_file() and fpath.suffix in (".js", ".html"):
        txt = fpath.read_text(encoding="utf-8")
        self.assertNotIn("renderDonutChart", txt, f"Masih ada renderDonutChart di {fpath.name}")
        # Pastikan seluruh penanda cache-bust seragam ke 20261120-v8.2
        for ver in re.findall(r"20261120-v[\d.]+", txt):
          self.assertEqual(ver, "20261120-v8.4.2", f"Versi cache-bust usang {ver} di {fpath.name}")

    teacher_js = (static_dir / "js" / "teacher.js").read_text(encoding="utf-8")
    self.assertIn('renderDoughnutChart("chart-t-attendance"', teacher_js)
    self.assertIn("async function openAttSession(", teacher_js)
    self.assertIn("window.openAttSession = openAttSession;", teacher_js)

    # Uji runtime renderLineChart (multi-series, null gap, 1 titik, semua 0, XSS) & renderDoughnutChart di Node
    with tempfile.TemporaryDirectory() as tmp:
      tmp_dir = Path(tmp)
      (tmp_dir / "package.json").write_text('{"type": "module"}', encoding="utf-8")
      (tmp_dir / "state.js").write_text(
          (static_dir / "js" / "state.js").read_text(encoding="utf-8"), encoding="utf-8"
      )
      charts_src = (static_dir / "js" / "charts.js").read_text(encoding="utf-8")
      charts_src = re.sub(r'\./state\.js\?v=[^"\x27]+', "./state.js", charts_src)
      (tmp_dir / "charts.js").write_text(charts_src, encoding="utf-8")

      runner = tmp_dir / "run_chart_test.mjs"
      runner.write_text(
          """
const boxes = { c1: { innerHTML: "" }, c2: { innerHTML: "" }, c3: { innerHTML: "" }, c4: { innerHTML: "" } };
globalThis.document = { getElementById: (id) => boxes[id] || null };
import { renderLineChart, renderDoughnutChart } from "./charts.js";

// Multi-series dengan null gap & karakter XSS
renderLineChart("c1", [
  { name: "Andi <script>", points: [{ label: "UH1", value: 70 }, { label: "UH2", value: null }, { label: "UH3", value: 90 }] },
  { name: "Budi", points: [{ label: "UH1", value: 80 }, { label: "UH2", value: 85 }, { label: "UH3", value: 95 }] },
]);
if (!boxes.c1.innerHTML.includes("<svg") || !boxes.c1.innerHTML.includes("<path") || !boxes.c1.innerHTML.includes("<circle")) {
  throw new Error("Multi-series SVG gagal dirender");
}
if (boxes.c1.innerHTML.includes("<script>") || boxes.c1.innerHTML.includes("NaN")) {
  throw new Error("XSS atau NaN terdeteksi pada multi-series");
}

// Single point & nilai 0 (uji pembagian nol)
renderLineChart("c2", [{ label: "UH1", value: 0 }]);
if (!boxes.c2.innerHTML.includes("<circle") || boxes.c2.innerHTML.includes("NaN")) {
  throw new Error("Single-point zero gagal atau menghasilkan NaN");
}

// String kosong & null harus dianggap tidak ada data
renderLineChart("c3", [{ label: "UH1", value: "" }, { label: "UH2", value: null }]);
if (!boxes.c3.innerHTML.includes("Belum ada nilai")) {
  throw new Error("Empty/null values harus menampilkan pesan kosong");
}

// Doughnut chart kehadiran guru
renderDoughnutChart("c4", {
  centerValue: "85%",
  centerLabel: "Kehadiran",
  centerBadge: "20 Catatan",
  segments: [{ label: "Hadir", value: 17, displayValue: "17x", color: "#34d399" }],
});
if (!boxes.c4.innerHTML.includes("<svg") || !boxes.c4.innerHTML.includes("85%")) {
  throw new Error("renderDoughnutChart gagal dirender");
}
console.log("NODE_CHARTS_OK");
""",
          encoding="utf-8",
      )
      proc = subprocess.run(
          ["node", str(runner)],
          capture_output=True,
          text=True,
          check=False,
      )
      self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
      self.assertIn("NODE_CHARTS_OK", proc.stdout)

if __name__ == "__main__":
  unittest.main()
