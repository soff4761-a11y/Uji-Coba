"""Pengujian komprehensif v8.4: Penggabungan EWS, Hard Delete Permanen, Rata-Rata per Kategori,
Perbandingan Antarmateri, Panel Gulir, dan Pop-up Kejutan Nilai Ujian/Asesmen Sumatif.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from edutrack.configs.app_config import AppConfig
from edutrack.main import seed_initial_data
from edutrack.web.api import create_app


class EgmV84DashboardUxHardDeleteTest(unittest.TestCase):
  def setUp(self) -> None:
    self._tmpdir = tempfile.TemporaryDirectory()
    db_path = Path(self._tmpdir.name) / "v84_test.db"
    cfg = AppConfig(
        db_path=str(db_path),
        backup_dir=str(Path(self._tmpdir.name) / "backups"),
        cookie_secure=False,
    )
    self.app = create_app(cfg)
    seed_initial_data(self.app.state.container)
    self.container = self.app.state.container
    self.client = TestClient(self.app)
    self.teacher_client = TestClient(self.app)
    self.student_client = TestClient(self.app)
    self.student2_client = TestClient(self.app)

    # Login seeded teacher via session + CSRF
    with self.container.db.connection() as conn:
      t_row = conn.execute("SELECT id FROM users WHERE role = 'teacher' ORDER BY id ASC LIMIT 1").fetchone()
    teacher_user = self.container.user_repo.get_by_id(int(t_row["id"]))
    tok = self.container.auth_service.issue_session(teacher_user, user_agent="unittest")["token"]
    self.teacher_client.cookies.set(cfg.cookie_name, tok)
    me = self.teacher_client.get("/api/auth/me?refresh_csrf=1")
    self.assertEqual(me.status_code, 200, me.text)
    self.csrf_t = self.teacher_client.cookies.get("edutrack_csrf", "")

    # Setup period & class
    res_p = self._t_post("/api/teacher/periods", {"name": "2027/2028 Ganjil", "academic_year": "2027/2028", "semester": "Ganjil", "is_active": True})
    self.period_id = res_p.json()["period"]["id"]
    res_c = self._t_post(
        "/api/teacher/classes",
        {
            "name": "X Bahasa 1",
            "education_level": "SMA",
            "period_id": self.period_id,
            "mastery_threshold": 75.0,
        },
    )
    self.class_id = res_c.json()["classroom"]["id"]

    # Create 2 students and issue sessions directly
    s1 = self._t_post(
        "/api/teacher/students",
        {"full_name": "Budi Santoso", "student_code": "NIS8401", "class_id": self.class_id},
    ).json()
    self.s1_id = s1["student"]["id"]
    s2 = self._t_post(
        "/api/teacher/students",
        {"full_name": "Siti Aminah", "student_code": "NIS8402", "class_id": self.class_id},
    ).json()
    self.s2_id = s2["student"]["id"]

    with self.container.db.connection() as conn:
      u1_id = conn.execute("SELECT user_id FROM students WHERE id = ?", (self.s1_id,)).fetchone()[0]
      u2_id = conn.execute("SELECT user_id FROM students WHERE id = ?", (self.s2_id,)).fetchone()[0]
    u1 = self.container.user_repo.get_by_id(int(u1_id))
    u2 = self.container.user_repo.get_by_id(int(u2_id))
    self.student_client.cookies.set(cfg.cookie_name, self.container.auth_service.issue_session(u1, user_agent="unittest")["token"])
    self.student_client.get("/api/auth/me?refresh_csrf=1")
    self.csrf_s1 = self.student_client.cookies.get("edutrack_csrf", "")

    self.student2_client.cookies.set(cfg.cookie_name, self.container.auth_service.issue_session(u2, user_agent="unittest")["token"])
    self.student2_client.get("/api/auth/me?refresh_csrf=1")
    self.csrf_s2 = self.student2_client.cookies.get("edutrack_csrf", "")

  def tearDown(self) -> None:
    self._tmpdir.cleanup()

  def _t_headers(self) -> dict[str, str]:
    return {"X-CSRF-Token": self.teacher_client.cookies.get("edutrack_csrf", self.csrf_t)}

  def _s1_headers(self) -> dict[str, str]:
    return {"X-CSRF-Token": self.student_client.cookies.get("edutrack_csrf", self.csrf_s1)}

  def _s2_headers(self) -> dict[str, str]:
    return {"X-CSRF-Token": self.student2_client.cookies.get("edutrack_csrf", self.csrf_s2)}

  def _t_post(self, url: str, payload: dict):
    res = self.teacher_client.post(url, json=payload, headers=self._t_headers())
    self.assertIn(res.status_code, (200, 201), res.text)
    return res

  def _login_student(self, client: TestClient, username: str, temp_pw: str, new_pw: str) -> None:
    r = client.post("/api/auth/login", json={"username": username, "password": temp_pw})
    self.assertEqual(r.status_code, 200, r.text)
    csrf = client.cookies.get("edutrack_csrf", "")
    r2 = client.post(
        "/api/auth/change-password",
        json={"old_password": temp_pw, "new_password": new_pw},
        headers={"X-CSRF-Token": csrf},
    )
    self.assertEqual(r2.status_code, 200, r2.text)

  def test_01_category_grouped_component_averages(self) -> None:
    """Rata-rata antarkomponen dikelompokkan berdasarkan kategori bernilai dan mengabaikan checklist."""
    a1 = self._t_post(
        f"/api/teacher/classes/{self.class_id}/assessments",
        {"title": "Tugas 1", "category": "Tugas", "max_score": 100, "weight": 1, "assessment_date": "2026-10-01", "status": "published", "is_graded": True},
    ).json()["assessment"]["id"]
    a2 = self._t_post(
        f"/api/teacher/classes/{self.class_id}/assessments",
        {"title": "Tugas 2", "category": "Tugas", "max_score": 100, "weight": 1, "assessment_date": "2026-10-02", "status": "published", "is_graded": True},
    ).json()["assessment"]["id"]
    a3 = self._t_post(
        f"/api/teacher/classes/{self.class_id}/assessments",
        {"title": "Kuis 1", "category": "Kuis", "max_score": 100, "weight": 1, "assessment_date": "2026-10-03", "status": "published", "is_graded": True},
    ).json()["assessment"]["id"]
    # Checklist should NOT appear in component_averages
    self._t_post(
        f"/api/teacher/classes/{self.class_id}/assessments",
        {"title": "Catatan", "category": "Tugas", "max_score": 1, "weight": 0, "assessment_date": "2026-10-04", "status": "published", "is_graded": False},
    )

    self._t_post(f"/api/teacher/assessments/{a1}/grades", {"entries": [{"student_id": self.s1_id, "score": 80}, {"student_id": self.s2_id, "score": 90}]})
    self._t_post(f"/api/teacher/assessments/{a2}/grades", {"entries": [{"student_id": self.s1_id, "score": 70}]})
    self._t_post(f"/api/teacher/assessments/{a3}/grades", {"entries": [{"student_id": self.s1_id, "score": 95}]})

    dash = self.teacher_client.get(f"/api/teacher/dashboard?class_id={self.class_id}").json()
    comps = dash["component_averages"]
    self.assertEqual([c["category"] for c in comps], ["Tugas", "Kuis"])
    # Pooled Tugas mean: (80 + 90 + 70) / 3 = 80.0
    self.assertEqual(comps[0]["average"], 80.0)
    self.assertEqual(comps[0]["assessment_count"], 2)
    self.assertEqual(comps[0]["graded_count"], 3)
    self.assertEqual(comps[1]["average"], 95.0)

  def test_02_teacher_compare_material_filter(self) -> None:
    """Endpoint compare guru mendukung filter material_id dan mengabaikan checklist."""
    m1 = self._t_post(f"/api/teacher/classes/{self.class_id}/materials", {"title": "Materi 1 Teks LHO"}).json()["material"]["id"]
    m2 = self._t_post(f"/api/teacher/classes/{self.class_id}/materials", {"title": "Materi 2 Teks Anekdot"}).json()["material"]["id"]

    a1 = self._t_post(
        f"/api/teacher/classes/{self.class_id}/assessments",
        {"title": "Latihan LHO", "category": "Latihan", "material_id": m1, "max_score": 100, "weight": 1, "assessment_date": "2026-10-05", "status": "published", "is_graded": True},
    ).json()["assessment"]["id"]
    a2 = self._t_post(
        f"/api/teacher/classes/{self.class_id}/assessments",
        {"title": "Latihan Anekdot", "category": "Latihan", "material_id": m2, "max_score": 100, "weight": 1, "assessment_date": "2026-10-06", "status": "published", "is_graded": True},
    ).json()["assessment"]["id"]
    self._t_post(f"/api/teacher/assessments/{a1}/grades", {"entries": [{"student_id": self.s1_id, "score": 82}]})
    self._t_post(f"/api/teacher/assessments/{a2}/grades", {"entries": [{"student_id": self.s1_id, "score": 94}]})

    r_all = self.teacher_client.get(f"/api/teacher/classes/{self.class_id}/compare?student_ids={self.s1_id}").json()
    self.assertEqual(len(r_all["assessments"]), 2)

    r_m1 = self.teacher_client.get(f"/api/teacher/classes/{self.class_id}/compare?student_ids={self.s1_id}&material_id={m1}").json()
    self.assertEqual(len(r_m1["assessments"]), 1)
    self.assertEqual(r_m1["assessments"][0]["title"], "Latihan LHO")
    self.assertEqual(r_m1["selected_material_id"], m1)

    r_m2 = self.teacher_client.get(f"/api/teacher/classes/{self.class_id}/compare?student_ids={self.s1_id}&material_id={m2}").json()
    self.assertEqual(len(r_m2["assessments"]), 1)
    self.assertEqual(r_m2["assessments"][0]["title"], "Latihan Anekdot")

  def test_03_surprise_reveal_ujian_sumatif_lifecycle(self) -> None:
    """Nilai Ujian & Asesmen Sumatif memerlukan reveal, tersimpan di DB, menolak kategori lain/draft."""
    a_ujian = self._t_post(
        f"/api/teacher/classes/{self.class_id}/assessments",
        {"title": "PTS Bahasa Indonesia", "category": "Ujian", "max_score": 100, "weight": 2, "assessment_date": "2026-10-10", "status": "published", "is_graded": True},
    ).json()["assessment"]["id"]
    a_sum = self._t_post(
        f"/api/teacher/classes/{self.class_id}/assessments",
        {"title": "Sumatif Bab 1", "category": "Asesmen Sumatif", "max_score": 100, "weight": 2, "assessment_date": "2026-10-11", "status": "published", "is_graded": True},
    ).json()["assessment"]["id"]
    a_tugas = self._t_post(
        f"/api/teacher/classes/{self.class_id}/assessments",
        {"title": "Tugas Harian", "category": "Tugas", "max_score": 100, "weight": 1, "assessment_date": "2026-10-12", "status": "published", "is_graded": True},
    ).json()["assessment"]["id"]
    a_draft = self._t_post(
        f"/api/teacher/classes/{self.class_id}/assessments",
        {"title": "Ujian Draft", "category": "Ujian", "max_score": 100, "weight": 1, "assessment_date": "2026-10-13", "status": "draft", "is_graded": True},
    ).json()["assessment"]["id"]

    self._t_post(f"/api/teacher/assessments/{a_ujian}/grades", {"entries": [{"student_id": self.s1_id, "score": 88}]})
    self._t_post(f"/api/teacher/assessments/{a_sum}/grades", {"entries": [{"student_id": self.s1_id, "score": 92}]})
    self._t_post(f"/api/teacher/assessments/{a_tugas}/grades", {"entries": [{"student_id": self.s1_id, "score": 85}]})
    self._t_post(f"/api/teacher/assessments/{a_draft}/grades", {"entries": [{"student_id": self.s1_id, "score": 77}]})

    dash1 = self.student_client.get("/api/student/dashboard").json()
    self.assertEqual(len(dash1["pending_reveals"]), 2)
    by_id = {g["assessment_id"]: g for g in dash1["grade_timeline"]}
    self.assertTrue(by_id[a_ujian]["needs_reveal"])
    self.assertTrue(by_id[a_sum]["needs_reveal"])
    self.assertFalse(by_id[a_tugas]["needs_reveal"])

    # Reject non-surprise category
    r_bad_cat = self.student_client.post(f"/api/student/grades/{a_tugas}/reveal", headers=self._s1_headers())
    self.assertEqual(r_bad_cat.status_code, 400)

    # Reject draft exam
    r_bad_draft = self.student_client.post(f"/api/student/grades/{a_draft}/reveal", headers=self._s1_headers())
    self.assertEqual(r_bad_draft.status_code, 404)

    # Student 2 has no grade for a_ujian -> 404
    r_s2 = self.student2_client.post(f"/api/student/grades/{a_ujian}/reveal", headers=self._s2_headers())
    self.assertEqual(r_s2.status_code, 404)

    # Reveal Ujian for student 1
    r_rev = self.student_client.post(f"/api/student/grades/{a_ujian}/reveal", headers=self._s1_headers())
    self.assertEqual(r_rev.status_code, 200, r_rev.text)
    rev_data = r_rev.json()
    self.assertEqual(rev_data["normalized_score"], 88.0)
    self.assertIsNotNone(rev_data["revealed_at"])
    first_ts = rev_data["revealed_at"]

    # Idempotent second call preserves original revealed_at
    r_rev2 = self.student_client.post(f"/api/student/grades/{a_ujian}/reveal", headers=self._s1_headers())
    self.assertEqual(r_rev2.status_code, 200)
    self.assertEqual(r_rev2.json()["revealed_at"], first_ts)

    # Dashboard now shows a_ujian revealed and only a_sum pending
    dash2 = self.student_client.get("/api/student/dashboard").json()
    self.assertEqual([p["assessment_id"] for p in dash2["pending_reveals"]], [a_sum])

  def test_04_permanent_hard_delete_zero_leftovers(self) -> None:
    """Penghapusan nilai, sesi pertemuan, dan siswa menghapus permanen seluruh baris terkait di DB."""
    # Create assessment, grade, history, correction
    a1 = self._t_post(
        f"/api/teacher/classes/{self.class_id}/assessments",
        {"title": "Tugas Hapus", "category": "Tugas", "max_score": 100, "weight": 1, "assessment_date": "2026-10-15", "status": "published", "is_graded": True},
    ).json()["assessment"]["id"]
    self._t_post(f"/api/teacher/assessments/{a1}/grades", {"entries": [{"student_id": self.s1_id, "score": 75}]})
    self._t_post(f"/api/teacher/assessments/{a1}/grades", {"entries": [{"student_id": self.s1_id, "score": 85}]})
    self.student_client.post(
        "/api/student/corrections",
        json={"target_type": "grade", "target_id": a1, "message": "Cek nilai"},
        headers=self._s1_headers(),
    )

    # Reset grades permanently via DELETE
    r_reset = self.teacher_client.delete(f"/api/teacher/assessments/{a1}/grades", headers=self._t_headers())
    self.assertEqual(r_reset.status_code, 200, r_reset.text)
    with self.container.db.connection() as conn:
      self.assertEqual(conn.execute("SELECT COUNT(*) FROM grades WHERE assessment_id = ?", (a1,)).fetchone()[0], 0)
      self.assertEqual(conn.execute("SELECT COUNT(*) FROM grade_history WHERE assessment_id = ?", (a1,)).fetchone()[0], 0)
      self.assertEqual(conn.execute("SELECT COUNT(*) FROM correction_requests WHERE target_type = 'grade' AND target_id = ?", (a1,)).fetchone()[0], 0)

    # Create attendance session + records + correction, then delete session permanently
    sess = self._t_post(
        f"/api/teacher/classes/{self.class_id}/attendance/sessions",
        {"session_date": "2026-10-16", "meeting_number": 1, "topic": "Pertemuan 1", "mark_all_present": True},
    ).json()["session"]
    sess_id = sess["id"]
    with self.container.db.connection() as conn:
      rec_id = conn.execute("SELECT id FROM attendance_records WHERE session_id = ? AND student_id = ?", (sess_id, self.s1_id)).fetchone()[0]
    self.student_client.post(
        "/api/student/corrections",
        json={"target_type": "attendance", "target_id": rec_id, "message": "Cek hadir"},
        headers=self._s1_headers(),
    )
    r_del_s = self.teacher_client.delete(f"/api/teacher/attendance/sessions/{sess_id}", headers=self._t_headers())
    self.assertEqual(r_del_s.status_code, 200, r_del_s.text)
    with self.container.db.connection() as conn:
      self.assertEqual(conn.execute("SELECT COUNT(*) FROM attendance_sessions WHERE id = ?", (sess_id,)).fetchone()[0], 0)
      self.assertEqual(conn.execute("SELECT COUNT(*) FROM attendance_records WHERE session_id = ?", (sess_id,)).fetchone()[0], 0)
      self.assertEqual(conn.execute("SELECT COUNT(*) FROM attendance_history WHERE session_id = ?", (sess_id,)).fetchone()[0], 0)
      self.assertEqual(conn.execute("SELECT COUNT(*) FROM correction_requests WHERE target_type = 'attendance' AND target_id = ?", (rec_id,)).fetchone()[0], 0)

    # Delete student 1 permanently -> verify zero leftover rows across all tables
    with self.container.db.connection() as conn:
      s1_uid = conn.execute("SELECT user_id FROM students WHERE id = ?", (self.s1_id,)).fetchone()[0]
    self.teacher_client.patch(
        f"/api/teacher/students/{self.s1_id}",
        json={"account_status": "deactivated"},
        headers=self._t_headers(),
    )
    r_del_stu = self.teacher_client.delete(f"/api/teacher/students/{self.s1_id}?confirm_permanent=true", headers=self._t_headers())
    self.assertEqual(r_del_stu.status_code, 200, r_del_stu.text)
    with self.container.db.connection() as conn:
      for tbl, col, val in [
          ("students", "id", self.s1_id),
          ("users", "id", s1_uid),
          ("grades", "student_id", self.s1_id),
          ("grade_history", "student_id", self.s1_id),
          ("attendance_records", "student_id", self.s1_id),
          ("attendance_history", "student_id", self.s1_id),
          ("correction_requests", "student_id", self.s1_id),
          ("student_enrollments", "student_id", self.s1_id),
          ("sessions", "user_id", s1_uid),
          ("recovery_tokens", "user_id", s1_uid),
          ("audit_logs", "actor_user_id", s1_uid),
      ]:
        cnt = conn.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {col} = ?", (val,)).fetchone()[0]
        self.assertEqual(cnt, 0, f"Sisa baris ditemukan di {tbl}.{col} = {val}")

  def test_05_ui_invariants_v84(self) -> None:
    """Pastikan HTML & CSS v8.4 memuat elemen penggabungan EWS, scroll, perbandingan, & modal reveal."""
    static_dir = Path("edutrack/web/static")
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    css = (static_dir / "styles.css").read_text(encoding="utf-8")

    # EWS merged: t-attention-tbody removed, ews-card unified
    self.assertNotIn('id="t-attention-tbody"', html)
    self.assertIn("Peserta Didik Memerlukan Perhatian", html)
    # Scrollable meeting sessions & student panels
    self.assertIn("att-sessions-scroll", html)
    self.assertIn("student-panel-scroll", html)
    self.assertIn(".att-sessions-scroll", css)
    self.assertIn(".student-panel-scroll", css)
    # Side-by-side comparison for teacher & student
    self.assertIn('id="compare-mat-left"', html)
    self.assertIn('id="compare-mat-right"', html)
    self.assertIn('id="chart-t-compare-right"', html)
    self.assertIn('id="s-compare-mat-left"', html)
    self.assertIn('id="s-compare-mat-right"', html)
    self.assertIn('id="chart-s-compare-left"', html)
    self.assertIn('id="chart-s-compare-right"', html)
    # Surprise reveal modal CSS, unified glassmorphism theme & reduced-motion
    self.assertIn("#student-reveal-popup", css)
    self.assertIn("#student-ews-popup.ews-popup", css)
    self.assertIn("-webkit-backdrop-filter", css)
    self.assertIn("outline-offset: 2px", css)
    self.assertIn("prefers-reduced-motion", css)
    # Distribusi Nilai Akhir Kelas menggunakan renderDoughnutChart peka tema
    teacher_js = (static_dir / "js" / "teacher.js").read_text(encoding="utf-8")
    self.assertIn('renderDoughnutChart("chart-t-distribution"', teacher_js)
    self.assertIn("#047857", teacher_js)


  def test_06_delete_all_attendance_sessions_and_v842_ui(self) -> None:
    """Hapus semua sesi pertemuan menghapus permanen seluruh baris terkait dan mematuhi invarian UI v8.4.2."""
    # Empty class is idempotent (deleted_sessions == 0)
    r_empty = self.teacher_client.delete(
        f"/api/teacher/classes/{self.class_id}/attendance/sessions",
        headers=self._t_headers(),
    )
    self.assertEqual(r_empty.status_code, 200, r_empty.text)
    self.assertEqual(r_empty.json()["deleted_sessions"], 0)

    # Create 2 sessions + correction on record & session
    s1 = self._t_post(
        f"/api/teacher/classes/{self.class_id}/attendance/sessions",
        {"session_date": "2026-11-01", "meeting_number": 1, "topic": "P1", "mark_all_present": True},
    ).json()["session"]["id"]
    s2 = self._t_post(
        f"/api/teacher/classes/{self.class_id}/attendance/sessions",
        {"session_date": "2026-11-02", "meeting_number": 2, "topic": "P2", "mark_all_present": True},
    ).json()["session"]["id"]
    with self.container.db.connection() as conn:
      rec_id = conn.execute("SELECT id FROM attendance_records WHERE session_id = ? AND student_id = ?", (s1, self.s1_id)).fetchone()[0]
    self.student_client.post(
        "/api/student/corrections",
        json={"target_type": "attendance", "target_id": rec_id, "message": "Koreksi rec"},
        headers=self._s1_headers(),
    )
    self.student_client.post(
        "/api/student/corrections",
        json={"target_type": "attendance", "target_id": s2, "message": "Koreksi sess"},
        headers=self._s1_headers(),
    )

    # Delete all sessions for class
    r_del = self.teacher_client.delete(
        f"/api/teacher/classes/{self.class_id}/attendance/sessions",
        headers=self._t_headers(),
    )
    self.assertEqual(r_del.status_code, 200, r_del.text)
    self.assertEqual(r_del.json()["deleted_sessions"], 2)

    with self.container.db.connection() as conn:
      self.assertEqual(conn.execute("SELECT COUNT(*) FROM attendance_sessions WHERE class_id = ?", (self.class_id,)).fetchone()[0], 0)
      self.assertEqual(conn.execute("SELECT COUNT(*) FROM attendance_records WHERE session_id IN (?, ?)", (s1, s2)).fetchone()[0], 0)
      self.assertEqual(conn.execute("SELECT COUNT(*) FROM attendance_history WHERE session_id IN (?, ?)", (s1, s2)).fetchone()[0], 0)
      self.assertEqual(conn.execute("SELECT COUNT(*) FROM correction_requests WHERE target_type = 'attendance' AND student_id = ?", (self.s1_id,)).fetchone()[0], 0)

    # UI invariants v8.4.2
    static_dir = Path("edutrack/web/static")
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    css = (static_dir / "styles.css").read_text(encoding="utf-8")
    teacher_js = (static_dir / "js" / "teacher.js").read_text(encoding="utf-8")
    self.assertIn('id="btn-compare-select-all"', html)
    self.assertIn('id="btn-compare-clear-all"', html)
    self.assertIn('id="btn-delete-all-sessions"', html)
    self.assertIn("<h3>Penilaian</h3>", html)
    self.assertIn("<h3>Catatan</h3>", html)
    self.assertNotIn("Pusat pengelolaan pembelajaran, nilai, dan kehadiran", html)
    self.assertNotIn("Komunikasi searah permanen untuk jadwal ujian", html)
    self.assertNotIn("Bandingkan perkembangan nilai Anda antara dua materi", html)
    self.assertNotIn("Tugas berbentuk checklist pengumpulan", html)
    self.assertNotIn("Sistem Peringatan Dini (EWS) &amp; Peserta Didik Memerlukan Perhatian", html)
    self.assertNotIn("Panel Kiri:", teacher_js)
    self.assertNotIn("Panel Kanan:", teacher_js)
    self.assertIn(".btn:disabled", css)

if __name__ == "__main__":
  unittest.main()
