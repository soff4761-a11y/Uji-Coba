"""Pengujian fitur hapus catatan koreksi guru & penghapusan panel Audit Log di dashboard guru (v8.2.2)."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from edutrack.configs.app_config import AppConfig
from edutrack.main import seed_initial_data
from edutrack.web.api import create_app


class TeacherDeleteCorrectionAndHideAuditLogTest(unittest.TestCase):
  """Verifikasi hapus koreksi oleh guru (termasuk anti-IDOR & CSRF) dan hilangnya panel Audit Log."""

  def setUp(self) -> None:
    self._tmpdir = tempfile.TemporaryDirectory()
    self._cfg = AppConfig(
        db_path=os.path.join(self._tmpdir.name, "v8_2_2.db"),
        backup_dir=os.path.join(self._tmpdir.name, "backups"),
        cookie_secure=False,
    )
    self._app = create_app(self._cfg)
    seed_initial_data(self._app.state.container)
    self._client = TestClient(self._app)

  def tearDown(self) -> None:
    self._client.close()
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

  def _get_seeded_teacher_and_create_correction(self, message: str = "Mohon cek ulang nilai UTS."):
    container = self._app.state.container
    with container.db.connection() as conn:
      t_row = conn.execute("SELECT id FROM users WHERE role = 'teacher' ORDER BY id ASC LIMIT 1").fetchone()
      s_row = conn.execute("SELECT id FROM students ORDER BY id ASC LIMIT 1").fetchone()
    self.assertIsNotNone(t_row)
    self.assertIsNotNone(s_row)
    teacher = container.user_repo.get_by_id(int(t_row["id"]))
    self.assertIsNotNone(teacher)
    req = container.attendance_repo.create_correction_request(
        student_id=int(s_row["id"]),
        teacher_id=teacher.id,
        target_type="grade",
        target_id=1,
        message=message,
    )
    return teacher, int(req["id"])

  def test_teacher_can_delete_pending_and_resolved_corrections(self) -> None:
    teacher, req_pending = self._get_seeded_teacher_and_create_correction("Koreksi pending")
    _, req_resolved = self._get_seeded_teacher_and_create_correction("Koreksi selesai")
    guru = self._client_for_user(teacher)
    try:
      # Selesaikan req_resolved terlebih dahulu
      patch_res = guru.patch(
          f"/api/teacher/corrections/{req_resolved}",
          json={"status": "resolved", "teacher_response": "Sudah diperbaiki."},
      )
      self.assertEqual(patch_res.status_code, 200, patch_res.text)

      # Hapus yang pending
      del_pending = guru.delete(f"/api/teacher/corrections/{req_pending}")
      self.assertEqual(del_pending.status_code, 200, del_pending.text)
      self.assertEqual(del_pending.json()["status"], "deleted")

      # Hapus yang sudah resolved
      del_resolved = guru.delete(f"/api/teacher/corrections/{req_resolved}")
      self.assertEqual(del_resolved.status_code, 200, del_resolved.text)
      self.assertEqual(del_resolved.json()["status"], "deleted")

      # Pastikan keduanya hilang dari daftar koreksi guru
      list_res = guru.get("/api/teacher/corrections")
      self.assertEqual(list_res.status_code, 200)
      ids = [int(item["id"]) for item in list_res.json()["corrections"]]
      self.assertNotIn(req_pending, ids)
      self.assertNotIn(req_resolved, ids)
    finally:
      guru.close()

  def test_delete_correction_not_found_and_idor_blocked(self) -> None:
    container = self._app.state.container
    teacher1, req_id = self._get_seeded_teacher_and_create_correction("Milik guru utama")
    teacher2 = container.auth_service.register_teacher(
        username="guru_lain_v822",
        password="Password123!",
        full_name="Guru Lain",
    )

    guru1 = self._client_for_user(teacher1)
    guru2 = self._client_for_user(teacher2)
    try:
      # Guru lain tidak boleh menghapus koreksi milik guru1 -> 403
      res_idor = guru2.delete(f"/api/teacher/corrections/{req_id}")
      self.assertEqual(res_idor.status_code, 403, res_idor.text)

      # ID tidak ada -> 404
      res_404 = guru1.delete("/api/teacher/corrections/999999")
      self.assertEqual(res_404.status_code, 404, res_404.text)

      # Tanpa header CSRF -> 403
      del guru1.headers["X-CSRF-Token"]
      res_no_csrf = guru1.delete(f"/api/teacher/corrections/{req_id}")
      self.assertEqual(res_no_csrf.status_code, 403)
    finally:
      guru1.close()
      guru2.close()

  def test_teacher_dashboard_hides_audit_log_and_has_delete_correction_button(self) -> None:
    static_dir = Path(__file__).resolve().parent.parent / "web" / "static"
    index_html = (static_dir / "index.html").read_text(encoding="utf-8")
    teacher_js = (static_dir / "js" / "teacher.js").read_text(encoding="utf-8")

    # Panel Catatan Aktivitas (Audit Log) tidak lagi ditampilkan di dashboard guru
    self.assertNotIn("Catatan Aktivitas (Audit Log)", index_html)
    self.assertNotIn('id="t-audit-tbody"', index_html)
    self.assertNotIn("/api/teacher/audit-logs", teacher_js)
    self.assertNotIn("t-audit-tbody", teacher_js)

    # Fitur hapus koreksi tersedia di UI guru
    self.assertIn("deleteTeacherCorrection", teacher_js)
    self.assertIn('method: "DELETE"', teacher_js)


if __name__ == "__main__":
  unittest.main()
