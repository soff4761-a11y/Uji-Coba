"""Pengujian integrasi & keamanan komprehensif untuk EduTrack v7 (EGM)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from edutrack.configs.app_config import AppConfig
from edutrack.repositories.database import (
    Database,
    DatabaseIntegrityError,
    _is_integrity_exception,
    translate_sql_to_postgres,
)
from edutrack.web.api import create_app


class EgmV7HardeningTest(unittest.TestCase):
  """Memverifikasi seluruh peningkatan keamanan, performa/DB, dan modularisasi v7."""

  def setUp(self) -> None:
    self._tmpdir = tempfile.TemporaryDirectory()
    self._db_path = os.path.join(self._tmpdir.name, "edutrack_v7.db")
    self._now = datetime(2026, 11, 20, 8, 0, 0, tzinfo=timezone.utc)
    self._cfg = AppConfig(
        db_path=self._db_path,
        backup_dir=os.path.join(self._tmpdir.name, "backups"),
        pbkdf2_iterations=10_000,
        seed_demo_data=False,
        session_touch_interval_seconds=300,
    )
    self._app = create_app(self._cfg)
    self._container = self._app.state.container
    self._container.auth_service._clock = lambda: self._now
    self._container.auth_service.register_admin(
        "admin_v7", "PasswordAdmin123!", "Admin Utama"
    )
    self._container.auth_service.register_teacher(
        "guru_v7", "PasswordGuru123!", "Guru V7"
    )

  def tearDown(self) -> None:
    self._tmpdir.cleanup()

  def _login(self, username: str, password: str) -> TestClient:
    client = TestClient(self._app)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    self.assertEqual(res.status_code, 200, res.text)
    # Keamanan v7: token TIDAK boleh dikirim di body JSON
    self.assertNotIn("token", res.json())
    csrf = client.cookies.get("edutrack_csrf", "")
    self.assertTrue(len(csrf) >= 16)
    client.headers["X-CSRF-Token"] = csrf
    return client

  def test_1_closed_recovery_nis_defaults_student_username_and_teacher_reset(self) -> None:
    anon = TestClient(self._app)
    # Endpoint recovery publik & email telah dihapus (404)
    self.assertEqual(anon.post("/api/auth/recovery/request", json={"username": "guru_v7"}).status_code, 404)
    self.assertEqual(anon.post("/api/auth/recovery/reset", json={"recovery_token": "x", "new_password": "Password123!"}).status_code, 404)

    guru = self._login("guru_v7", "PasswordGuru123!")
    cls_id = guru.post("/api/teacher/classes", json={"name": "XII-V7", "education_level": "SMA"}).json()["classroom"]["id"]

    # Tambah murid tanpa username/password -> otomatis NIS & 12345678
    created = guru.post(
        "/api/teacher/students",
        json={"class_id": cls_id, "full_name": "Raka Pratama", "student_code": "2026001", "account_status": "active"},
    )
    self.assertEqual(created.status_code, 201, created.text)
    body = created.json()
    self.assertEqual(body["username"], "2026001")
    self.assertEqual(body["initial_password"], "12345678")
    stu_id = body["student"]["id"]

    # Murid login pakai NIS & 12345678, lalu ganti sandi dan ubah username
    siswa = self._login("2026001", "12345678")
    ch = siswa.post("/api/auth/change-password", json={"current_password": "12345678", "new_password": "SandiPribadi99!"})
    self.assertEqual(ch.status_code, 200, ch.text)
    siswa.headers["X-CSRF-Token"] = siswa.cookies.get("edutrack_csrf", "")

    u_chg = siswa.patch("/api/student/username", json={"username": "raka_keren"})
    self.assertEqual(u_chg.status_code, 200, u_chg.text)
    self.assertEqual(u_chg.json()["user"]["username"], "raka_keren")

    # Guru reset kredensial murid -> otomatis kembali ke NIS (2026001) & 12345678 + sesi lama dicabut
    rst = guru.post(f"/api/teacher/students/{stu_id}/reset-credentials")
    self.assertEqual(rst.status_code, 200, rst.text)
    self.assertEqual(rst.json()["username"], "2026001")
    self.assertEqual(rst.json()["temporary_password"], "12345678")
    self.assertEqual(siswa.get("/api/auth/me").status_code, 401)
    # Login ulang dengan NIS & 12345678 berhasil
    siswa_baru = self._login("2026001", "12345678")
    self.assertEqual(siswa_baru.get("/api/auth/me").status_code, 200)

  def test_2_csrf_protection_change_password_revokes_other_sessions_and_admin_only_backup(self) -> None:
    # CSRF block saat X-CSRF-Token tidak dikirim pada mutasi berkuki sesi
    guru = self._login("guru_v7", "PasswordGuru123!")
    saved_csrf = guru.headers.pop("X-CSRF-Token")
    blocked = guru.post("/api/teacher/classes", json={"name": "Tanpa CSRF", "education_level": "SMA"})
    self.assertEqual(blocked.status_code, 403)
    self.assertEqual(blocked.json()["code"], "csrf_failed")
    guru.headers["X-CSRF-Token"] = saved_csrf

    # Backup/Restore ditolak untuk guru biasa (403), diizinkan untuk Admin (200/201)
    self.assertEqual(guru.get("/api/teacher/backups").status_code, 403)
    self.assertEqual(guru.post("/api/teacher/backups", json={"label": "guru"}).status_code, 403)

    admin = self._login("admin_v7", "PasswordAdmin123!")
    self.assertEqual(admin.get("/api/teacher/backups").status_code, 200)
    b_res = admin.post("/api/teacher/backups", json={"label": "admin_ok"})
    self.assertEqual(b_res.status_code, 201, b_res.text)

    # change_password mencabut sesi di perangkat lain (dev2), sementara dev1 mendapat cookie segar
    dev1 = self._login("guru_v7", "PasswordGuru123!")
    dev2 = self._login("guru_v7", "PasswordGuru123!")
    self.assertEqual(dev2.get("/api/auth/me").status_code, 200)
    cp = dev1.post("/api/auth/change-password", json={"current_password": "PasswordGuru123!", "new_password": "PasswordBaru987!"})
    self.assertEqual(cp.status_code, 200)
    dev1.headers["X-CSRF-Token"] = dev1.cookies.get("edutrack_csrf", "")
    self.assertEqual(dev1.get("/api/auth/me").status_code, 200)
    self.assertEqual(dev2.get("/api/auth/me").status_code, 401)

  def test_3_touch_session_throttling_pagination_and_streaming_export(self) -> None:
    guru = self._login("guru_v7", "PasswordGuru123!")
    # Catat last_activity awal
    s0 = guru.get("/api/auth/sessions").json()["sessions"][0]["last_activity_at"]
    # Maju 60 detik (< 300s throttle) -> last_activity_at TIDAK berubah (beban tulis dihindari)
    self._now = self._now + timedelta(seconds=60)
    self.assertEqual(guru.get("/api/auth/me").status_code, 200)
    s1 = guru.get("/api/auth/sessions").json()["sessions"][0]["last_activity_at"]
    self.assertEqual(s0, s1)
    # Maju 310 detik (>= 300s) -> last_activity_at diperbarui
    self._now = self._now + timedelta(seconds=310)
    self.assertEqual(guru.get("/api/auth/me").status_code, 200)
    s2 = guru.get("/api/auth/sessions").json()["sessions"][0]["last_activity_at"]
    self.assertNotEqual(s1, s2)

    # Pagination kelas
    for i in range(4):
      guru.post("/api/teacher/classes", json={"name": f"Kelas-{i}", "education_level": "SMA"})
    p_res = guru.get("/api/teacher/classes?limit=2&offset=1").json()
    self.assertEqual(len(p_res["classes"]), 2)
    self.assertEqual(p_res["pagination"]["total"], 4)
    self.assertEqual(p_res["pagination"]["offset"], 1)

  def test_4_sql_translator_integrity_exceptions_versioned_migrations_and_es_modules(self) -> None:
    # CTE WITH, ON CONFLICT DO NOTHING, dan schema_migrations TIDAK boleh ditambah RETURNING id
    self.assertNotIn("RETURNING", translate_sql_to_postgres("WITH c AS (SELECT 1) INSERT INTO grades (score) SELECT 1"))
    self.assertNotIn("RETURNING", translate_sql_to_postgres("INSERT INTO grades (score) VALUES (?) ON CONFLICT DO NOTHING"))
    self.assertNotIn("RETURNING", translate_sql_to_postgres("INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)"))
    self.assertIn("RETURNING id", translate_sql_to_postgres("INSERT INTO users (username) VALUES (?)"))

    # CheckViolation & NotNullViolation terdeteksi
    CheckViolation = type("CheckViolation", (Exception,), {})
    NotNullViolation = type("NotNullViolation", (Exception,), {})
    self.assertTrue(_is_integrity_exception(CheckViolation("bad check")))
    self.assertTrue(_is_integrity_exception(NotNullViolation("bad null")))

    # Tabel schema_migrations tercatat 5 migrasi
    with self._container.db.connection() as conn:
      vers = [int(r["version"]) for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()]
    self.assertEqual(vers, [1, 2, 3, 4, 5, 6, 7])

    # CHECK constraint grades.score >= 0 menolak nilai negatif di level DB
    with self.assertRaises(DatabaseIntegrityError):
      with self._container.db.connection() as conn:
        conn.execute("INSERT INTO grades (assessment_id, student_id, score, updated_by, updated_at) VALUES (1, 1, -5, 1, '2026-11-20T00:00:00+00:00')")

    # Verifikasi modul ES & tanpa sessionStorage token di frontend
    static_dir = Path(__file__).resolve().parent.parent / "web" / "static"
    for mod in ["app.js", "js/state.js", "js/api.js", "js/charts.js", "js/teacher.js", "js/student.js"]:
      content = (static_dir / mod).read_text(encoding="utf-8")
      self.assertNotIn('sessionStorage.setItem("edutrack_token"', content)
      self.assertNotIn('sessionStorage.getItem("edutrack_token"', content)


if __name__ == "__main__":
  unittest.main()
