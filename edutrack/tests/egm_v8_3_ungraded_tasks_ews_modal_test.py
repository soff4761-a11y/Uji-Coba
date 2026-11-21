"""Pengujian komprehensif v8.3: Tugas Dinilai vs Checklist, EWS Checklist, Migrasi v6, & Modal EWS Anti-Slop."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from edutrack.configs.app_config import AppConfig
from edutrack.domain.models import AssessmentStatus, CalculationMode
from edutrack.main import seed_initial_data
from edutrack.repositories.database import Database
from edutrack.services.analytics_service import evaluate_student_ews
from edutrack.web.api import create_app


class UngradedChecklistAndEwsModalV83Test(unittest.TestCase):
  """Menguji isolasi tugas checklist, pemicu EWS checklist, migrasi v6, dan modal EWS tengah anti-slop."""

  def setUp(self) -> None:
    self._tmpdir = tempfile.TemporaryDirectory()
    self._cfg = AppConfig(
        db_path=os.path.join(self._tmpdir.name, "v8_3.db"),
        backup_dir=os.path.join(self._tmpdir.name, "backups"),
        cookie_secure=False,
    )
    self._app = create_app(self._cfg)
    seed_initial_data(self._app.state.container)

  def tearDown(self) -> None:
    self._tmpdir.cleanup()

  def _client_for_user(self, user) -> TestClient:
    container = self._app.state.container
    raw_token = container.auth_service.issue_session(user, user_agent="unittest")["token"]
    c = TestClient(self._app)
    c.cookies.set(self._cfg.cookie_name, raw_token)
    res_me = c.get("/api/auth/me?refresh_csrf=true")
    self.assertEqual(res_me.status_code, 200, res_me.text)
    c.headers["X-CSRF-Token"] = c.cookies.get(self._cfg.csrf_cookie_name, "")
    return c

  def _get_seeded_actors(self):
    container = self._app.state.container
    with container.db.connection() as conn:
      t_row = conn.execute("SELECT id FROM users WHERE role = 'teacher' ORDER BY id ASC LIMIT 1").fetchone()
      s_row = conn.execute("SELECT id, user_id, current_class_id FROM students ORDER BY id ASC LIMIT 1").fetchone()
    teacher = container.user_repo.get_by_id(int(t_row["id"]))
    student_user = container.user_repo.get_by_id(int(s_row["user_id"]))
    return teacher, student_user, int(s_row["id"]), int(s_row["current_class_id"])

  def test_1_checklist_isolated_from_final_score_even_in_unweighted_mode(self) -> None:
    teacher, student_user, student_id, class_id = self._get_seeded_actors()
    container = self._app.state.container
    # Buat kelas baru bermode UNWEIGHTED tanpa nilai angka agar mudah uji kontaminasi 100.0
    cls = container.classroom_service.create_classroom(
        teacher,
        name="X-Bahasa-Unweighted",
        education_level="SMA",
        academic_year="2026/2027",
        period_id=1,
        mastery_threshold=75.0,
        calculation_mode=CalculationMode.UNWEIGHTED,
    )
    stu_res = container.student_service.create_student_with_account(
        teacher,
        class_id=cls.id,
        full_name="Siswa Uji Checklist",
        student_code="NIS9981",
    )
    stu = stu_res["student"]
    guru = self._client_for_user(teacher)
    try:
      # Buat 1 tugas checklist (is_graded=False) & publikasikan
      res_c = guru.post(
          f"/api/teacher/classes/{cls.id}/assessments",
          json={
              "title": "Kumpul Buku Catatan Bab 1",
              "category": "Tugas",
              "assessment_date": "2026-11-21",
              "max_score": 100,
              "weight": 25,
              "status": "published",
              "is_graded": False,
          },
      )
      self.assertEqual(res_c.status_code, 201, res_c.text)
      asmt = res_c.json()["assessment"]
      self.assertFalse(asmt["is_graded"])
      self.assertEqual(asmt["max_score"], 1.0)
      self.assertEqual(asmt["weight"], 0.0)

      # Centang sudah mengumpulkan (score = 1)
      res_save = guru.post(
          f"/api/teacher/assessments/{asmt['id']}/grades",
          json={"entries": [{"student_id": stu.id, "score": 1, "feedback": "Lengkap"}], "reason": "Checklist"},
      )
      self.assertEqual(res_save.status_code, 200, res_save.text)

      # Cek buku nilai: final_score HARUS tetap None (bukan 100.0!)
      gb = container.grade_service.get_class_gradebook(teacher, cls.id)
      row = next(r for r in gb["rows"] if r["student_id"] == stu.id)
      self.assertIsNone(row["final_score"])

      # Nilai tidak valid (mis. 0.5 atau 85) pada tugas checklist harus ditolak 400
      res_bad = guru.post(
          f"/api/teacher/assessments/{asmt['id']}/grades",
          json={"entries": [{"student_id": stu.id, "score": 0.5, "feedback": ""}], "reason": "Invalid"},
      )
      self.assertEqual(res_bad.status_code, 400)

      # Mengubah jenis is_graded saat sudah ada data pengumpulan harus ditolak 400
      res_flip = guru.patch(f"/api/teacher/assessments/{asmt['id']}", json={"is_graded": True})
      self.assertEqual(res_flip.status_code, 400)

      # PATCH parsial judul saja pada checklist tetap menjaga max_score=1.0, weight=0.0
      res_patch = guru.patch(
          f"/api/teacher/assessments/{asmt['id']}",
          json={"title": "Kumpul Buku Catatan Bab 1 Revisi", "max_score": 100, "weight": 20},
      )
      self.assertEqual(res_patch.status_code, 200, res_patch.text)
      self.assertEqual(res_patch.json()["assessment"]["max_score"], 1.0)
      self.assertEqual(res_patch.json()["assessment"]["weight"], 0.0)

      # Template impor Excel pada tugas checklist ditolak 400
      res_tpl = guru.get(f"/api/teacher/assessments/{asmt['id']}/import-template")
      self.assertEqual(res_tpl.status_code, 400)

      # Cek dashboard siswa: checklist_tasks terpisah dari grade_timeline & final_score tetap None
      stu_user = container.user_repo.get_by_id(stu.user_id)
      dash = container.analytics_service.get_student_dashboard(stu_user)
      self.assertEqual(len(dash["grade_timeline"]), 0)
      self.assertEqual(len(dash["checklist_tasks"]), 1)
      self.assertTrue(dash["checklist_tasks"][0]["submitted"])
      self.assertIsNone(dash["grade_summary"]["final_score"])
      self.assertFalse(dash["early_warning"]["is_triggered"])
    finally:
      guru.close()

  def test_2_unsubmitted_checklist_triggers_ews_on_teacher_and_student(self) -> None:
    teacher, _, _, _ = self._get_seeded_actors()
    container = self._app.state.container
    cls = container.classroom_service.create_classroom(
        teacher,
        name="XI-Bahasa-EWS",
        education_level="SMA",
        academic_year="2026/2027",
        period_id=1,
        mastery_threshold=75.0,
    )
    stu = container.student_service.create_student_with_account(
        teacher, class_id=cls.id, full_name="Siswa Lalai Catatan", student_code="NIS9982"
    )["student"]
    stu_user = container.user_repo.get_by_id(stu.user_id)

    # Buat 1 tugas bernilai dengan nilai tinggi (90 >= KKM 75)
    graded = container.grade_service.create_assessment(
        teacher,
        class_id=cls.id,
        title="Ulangan Teks Eksposisi",
        category="Ulangan",
        assessment_date="2026-11-10",
        max_score=100.0,
        weight=10.0,
        status=AssessmentStatus.PUBLISHED,
        is_graded=True,
    )
    container.grade_service.save_grades_bulk(
        teacher, graded.id, [{"student_id": stu.id, "score": 90.0, "feedback": "Bagus"}]
    )

    # Buat 3 tugas checklist dipublikasikan (belum dikumpulkan semua) + 1 draft (tidak dihitung)
    for i in range(1, 4):
      container.grade_service.create_assessment(
          teacher,
          class_id=cls.id,
          title=f"Buku Catatan #{i}",
          category="Tugas",
          assessment_date=f"2026-11-1{i}",
          status=AssessmentStatus.PUBLISHED,
          is_graded=False,
      )
    container.grade_service.create_assessment(
        teacher,
        class_id=cls.id,
        title="Catatan Draft",
        category="Tugas",
        assessment_date="2026-11-15",
        status=AssessmentStatus.DRAFT,
        is_graded=False,
    )

    # Siswa memiliki nilai 90 (>= KKM) & 0 alpa, tapi 3 checklist belum dikumpulkan -> EWS terpicu!
    dash_stu = container.analytics_service.get_student_dashboard(stu_user)
    self.assertEqual(dash_stu["grade_summary"]["final_score"], 90.0)
    self.assertEqual(len(dash_stu["grade_timeline"]), 1)
    self.assertEqual(len(dash_stu["checklist_tasks"]), 3)
    ews_stu = dash_stu["early_warning"]
    self.assertTrue(ews_stu["is_triggered"])
    self.assertEqual(ews_stu["severity"], "perhatian")
    self.assertIn("unsubmitted_checklist", ews_stu["triggers"])
    self.assertEqual(ews_stu["unsubmitted_checklist_count"], 3)

    # Sinkron 100% dengan EWS guru
    ews_teacher = container.analytics_service.get_early_warning_report(teacher, class_id=cls.id)
    self.assertEqual(ews_teacher["total_flagged"], 1)
    self.assertEqual(ews_teacher["students"][0]["student_id"], stu.id)
    self.assertIn("unsubmitted_checklist", ews_teacher["students"][0]["triggers"])

    # Evaluasi kombinasi 2 pemicu (nilai < KKM + 3 checklist) -> kritis
    ev_crit = evaluate_student_ews(60.0, 75.0, 0, 3, unsubmitted_checklist_count=3, unsubmitted_checklist_threshold=3)
    self.assertEqual(ev_crit["severity"], "kritis")
    self.assertEqual(set(ev_crit["triggers"]), {"below_kkm", "unsubmitted_checklist"})

  def test_3_migration_v6_idempotent_from_v5_schema(self) -> None:
    db_file = os.path.join(self._tmpdir.name, "legacy_v5.db")
    db = Database(db_path=db_file, backup_dir=os.path.join(self._tmpdir.name, "bak_v5"))
    db.initialize()
    # Verifikasi versi 6 tercatat dan kolom is_graded hadir
    with db.connection() as conn:
      cols = [r["name"] for r in conn.execute("PRAGMA table_info(assessments)").fetchall()]
      self.assertIn("is_graded", cols)
      m6 = conn.execute("SELECT version FROM schema_migrations WHERE version = 6").fetchone()
      self.assertIsNotNone(m6)
    # Panggil initialize() ulang -> harus tetap idempoten tanpa error
    db.initialize()

  def test_4_anti_slop_modal_and_ui_invariants(self) -> None:
    static_dir = Path(__file__).resolve().parent.parent / "web" / "static"
    index_html = (static_dir / "index.html").read_text(encoding="utf-8")
    styles_css = (static_dir / "styles.css").read_text(encoding="utf-8")
    student_js = (static_dir / "js" / "student.js").read_text(encoding="utf-8")

    # UI pemisahan tugas bernilai & checklist
    self.assertIn('id="a-is-graded"', index_html)
    self.assertIn('id="s-checklist-tbody"', index_html)
    # Anti-slop: tanpa emoji peringatan di modal EWS, ada ikon SVG, tombol Mengerti, dialog ARIA, reduced-motion
    self.assertNotIn("⚠️", student_js)
    self.assertIn("btn-ews-ack", student_js)
    self.assertIn("Mengerti", student_js)
    self.assertIn('role="dialog"', student_js)
    self.assertIn('aria-modal="true"', student_js)
    self.assertIn("prefers-reduced-motion", styles_css)
    self.assertIn("ews-modal-dialog", styles_css)


if __name__ == "__main__":
  unittest.main()
