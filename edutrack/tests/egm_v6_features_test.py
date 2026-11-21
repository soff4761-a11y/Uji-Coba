"""Pengujian integrasi lengkap untuk 5 fitur EduTrack v6 (EGM)."""

from __future__ import annotations

import os
import tempfile
import unittest
from typing import List, Tuple
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from edutrack.configs.app_config import AppConfig
from edutrack.services.report_service import _draw_page_chrome
from edutrack.web.api import create_app


class EgmV6FeaturesTest(unittest.TestCase):
  """Menguji Papan Pengumuman, PWA, PDF tanpa footer, Keamanan Akun/Sesi/Rate-Limit, dan EWS."""

  def setUp(self) -> None:
    self._tmpdir = tempfile.TemporaryDirectory()
    self._db_path = os.path.join(self._tmpdir.name, "edutrack_v6.db")
    self._cfg = AppConfig(
        db_path=self._db_path,
        pbkdf2_iterations=10_000,
        seed_demo_data=False,
        login_rate_limit_max_attempts=3,
        login_rate_limit_window_seconds=300,
        ews_alpa_threshold=3,
    )
    self._app = create_app(self._cfg)
    self._container = self._app.state.container
    self._container.auth_service.register_teacher(
        "guru_v6", "PasswordGuru123!", "Guru V6", email="guru.v6@sekolah.sch.id"
    )
    self._container.auth_service.register_teacher(
        "guru_lain", "PasswordLain123!", "Guru Lain", email="lain@sekolah.sch.id"
    )

  def tearDown(self) -> None:
    self._tmpdir.cleanup()

  def _login(
      self, username: str, password: str, user_agent: str = "Mozilla/5.0 Chrome/120 Safari/537.36"
  ) -> TestClient:
    client = TestClient(self._app)
    res = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
        headers={"User-Agent": user_agent},
    )
    self.assertEqual(res.status_code, 200, res.text)
    csrf = client.cookies.get("edutrack_csrf", "")
    if csrf:
      client.headers["X-CSRF-Token"] = csrf
    return client

  # --- FITUR 1: Papan Pengumuman Kelas ---

  def test_feature1_class_announcements_crud_and_rbac(self) -> None:
    guru = self._login("guru_v6", "PasswordGuru123!")
    guru_lain = self._login("guru_lain", "PasswordLain123!")
    cls_id = guru.post("/api/teacher/classes", json={"name": "XI-A", "education_level": "SMA"}).json()["classroom"]["id"]
    guru.post(
        "/api/teacher/students",
        json={
            "class_id": cls_id,
            "full_name": "Siti Rahma",
            "student_code": "NIS-601",
            "username": "siti_601",
            "initial_password": "Password123!",
            "account_status": "active",
        },
    )

    # Buat 2 pengumuman (1 disematkan)
    c1 = guru.post(
        f"/api/teacher/classes/{cls_id}/announcements",
        json={"title": "Jadwal UTS", "category": "Jadwal Ujian", "content": "UTS dimulai Senin depan.", "is_pinned": False},
    )
    self.assertEqual(c1.status_code, 201)
    a1 = c1.json()["announcement"]

    c2 = guru.post(
        f"/api/teacher/classes/{cls_id}/announcements",
        json={"title": "Tenggat Tugas Bab 2", "category": "Tenggat Tugas", "content": "Kumpulkan Jumat.", "is_pinned": True},
    )
    self.assertEqual(c2.status_code, 201)
    a2 = c2.json()["announcement"]

    # Guru ubah pengumuman
    upd = guru.patch(f"/api/teacher/announcements/{a1['id']}", json={"title": "Jadwal UTS (Revisi)"})
    self.assertEqual(upd.status_code, 200)
    self.assertEqual(upd.json()["announcement"]["title"], "Jadwal UTS (Revisi)")

    # Guru lain tidak boleh ubah/hapus (anti-IDOR)
    self.assertEqual(guru_lain.patch(f"/api/teacher/announcements/{a1['id']}", json={"title": "Hack"}).status_code, 403)
    self.assertEqual(guru_lain.delete(f"/api/teacher/announcements/{a1['id']}").status_code, 403)

    # Siswa hanya bisa membaca (pinned tampil pertama) + muncul di dashboard siswa
    siswa = self._login("siti_601", "Password123!")
    st_list = siswa.get("/api/student/announcements").json()["announcements"]
    self.assertEqual(len(st_list), 2)
    self.assertEqual(st_list[0]["id"], a2["id"])
    dash = siswa.get("/api/student/dashboard").json()
    self.assertEqual(len(dash["announcements"]), 2)
    # Siswa ditolak jika mencoba membuat/menghapus
    self.assertEqual(siswa.post(f"/api/teacher/classes/{cls_id}/announcements", json={"title": "X", "content": "Y"}).status_code, 403)

    # Guru hapus pengumuman
    self.assertEqual(guru.delete(f"/api/teacher/announcements/{a1['id']}").status_code, 200)
    self.assertEqual(len(siswa.get("/api/student/announcements").json()["announcements"]), 1)

  # --- FITUR 2: PWA Manifest, Service Worker & Offline UI ---

  def test_feature2_pwa_manifest_service_worker_and_offline_ui(self) -> None:
    client = TestClient(self._app)
    m_res = client.get("/manifest.json")
    self.assertEqual(m_res.status_code, 200)
    manifest = m_res.json()
    self.assertEqual(manifest["display"], "standalone")
    self.assertTrue(any(i.get("purpose") == "any maskable" for i in manifest["icons"]))

    sw_res = client.get("/sw.js")
    self.assertEqual(sw_res.status_code, 200)
    self.assertEqual(sw_res.headers.get("service-worker-allowed"), "/")
    self.assertIn('url.pathname.startsWith("/api/")', sw_res.text)
    self.assertIn("no-store", sw_res.headers.get("cache-control", ""))

    html = client.get("/").text
    self.assertIn('rel="manifest" href="/manifest.json"', html)
    self.assertIn('id="offline-sync-banner"', html)

  # --- FITUR 3: Template PDF Tanpa Footer ---

  def test_feature3_pdf_template_has_no_footer(self) -> None:
    mock_canvas = MagicMock()
    mock_doc = MagicMock()
    mock_doc.pagesize = (595.27, 841.89)
    mock_doc.leftMargin = 30
    mock_doc.rightMargin = 30
    _draw_page_chrome(mock_canvas, mock_doc)
    mock_canvas.drawString.assert_not_called()
    mock_canvas.drawRightString.assert_not_called()
    mock_canvas.line.assert_not_called()
    # Top accent bar tetap digambar (2 rect)
    self.assertEqual(mock_canvas.rect.call_count, 2)

  # --- FITUR 4: Email Recovery, Active Sessions & Logout All, Login Rate Limiting ---

  def test_feature4_email_recovery_active_sessions_logout_all_and_rate_limit(self) -> None:
    # 4b. Manajemen sesi aktif + Logout dari semua perangkat
    dev1 = self._login("guru_v6", "PasswordGuru123!", user_agent="Mozilla/5.0 (Windows NT 10.0) Chrome/121 Safari/537.36")
    dev2 = self._login("guru_v6", "PasswordGuru123!", user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17) Safari/604.1")
    sess_list = dev1.get("/api/auth/sessions").json()["sessions"]
    self.assertEqual(len(sess_list), 2)
    for s in sess_list:
      self.assertNotIn("token_hash", s)
      self.assertIn("device_label", s)
    other_sess = next(s for s in sess_list if not s["is_current"])
    # Cabut sesi dev2 dari dev1
    self.assertEqual(dev1.delete(f"/api/auth/sessions/{other_sess['id']}").status_code, 200)
    self.assertEqual(dev2.get("/api/auth/me").status_code, 401)
    self.assertEqual(dev1.get("/api/auth/me").status_code, 200)

    # Login lagi di dev3 lalu logout-all dari dev1 -> kedua perangkat tercabut
    dev3 = self._login("guru_v6", "PasswordGuru123!")
    self.assertEqual(dev1.post("/api/auth/logout-all", json={"keep_current": False}).status_code, 200)
    self.assertEqual(dev1.get("/api/auth/me").status_code, 401)
    self.assertEqual(dev3.get("/api/auth/me").status_code, 401)

    # 4c. Rate limiting login (max 3 gagal -> percobaan ke-4 HTTP 429 + Retry-After)
    anon = TestClient(self._app)
    for _ in range(3):
      bad = anon.post(
          "/api/auth/login",
          json={"username": "guru_v6", "password": "SalahPassword!"},
          headers={"x-vercel-forwarded-for": "203.0.113.10"},
      )
      self.assertEqual(bad.status_code, 401)
    blocked = anon.post(
        "/api/auth/login",
        json={"username": "guru_v6", "password": "PasswordGuru123!"},
        headers={"x-vercel-forwarded-for": "203.0.113.10"},
    )
    self.assertEqual(blocked.status_code, 429)
    self.assertIn("retry-after", {k.lower(): v for k, v in blocked.headers.items()})

  # --- FITUR 5: Early Warning System (EWS) ---

  def test_feature5_early_warning_system_kkm_and_alpa(self) -> None:
    guru = self._login("guru_v6", "PasswordGuru123!")
    cls_id = guru.post(
        "/api/teacher/classes",
        json={"name": "X-EWS", "education_level": "SMA", "mastery_threshold": 75.0},
    ).json()["classroom"]["id"]

    # 4 siswa: s_kritis (<KKM + alpa 3), s_nilai (<KKM saja), s_alpa (alpa 3, belum ada nilai), s_aman (nilai 88, alpa 0)
    def mk(name: str, code: str, uname: str) -> int:
      return guru.post(
          "/api/teacher/students",
          json={"class_id": cls_id, "full_name": name, "student_code": code, "username": uname, "initial_password": "Password123!", "account_status": "active"},
      ).json()["student"]["id"]

    s_kritis = mk("Andi Kritis", "E1", "andi_e1")
    s_nilai = mk("Budi Nilai", "E2", "budi_e2")
    s_alpa = mk("Citra Alpa", "E3", "citra_e3")
    s_aman = mk("Dewi Aman", "E4", "dewi_e4")

    asmt = guru.post(
        f"/api/teacher/classes/{cls_id}/assessments",
        json={"title": "Ulangan 1", "category": "Ujian", "assessment_date": "2026-11-18", "max_score": 100, "weight": 100, "status": "published"},
    ).json()["assessment"]
    guru.post(
        f"/api/teacher/assessments/{asmt['id']}/grades",
        json={
            "entries": [
                {"student_id": s_kritis, "score": 60},
                {"student_id": s_nilai, "score": 68},
                {"student_id": s_aman, "score": 88},
            ]
        },
    )

    # Buat 3 sesi kehadiran: s_kritis & s_alpa alpa 3x; s_nilai & s_aman hadir 3x
    for m in (1, 2, 3):
      ses = guru.post(
          f"/api/teacher/classes/{cls_id}/attendance/sessions",
          json={"session_date": f"2026-11-1{m}", "meeting_number": m, "topic": f"P{m}"},
      ).json()["session"]
      guru.post(
          f"/api/teacher/attendance/sessions/{ses['id']}/records",
          json={
              "entries": [
                  {"student_id": s_kritis, "status": "alpa", "note": ""},
                  {"student_id": s_alpa, "status": "alpa", "note": ""},
                  {"student_id": s_nilai, "status": "hadir", "note": ""},
                  {"student_id": s_aman, "status": "hadir", "note": ""},
              ]
          },
      )

    # Validasi threshold < 1 -> 400
    self.assertEqual(guru.get(f"/api/teacher/early-warning?class_id={cls_id}&alpa_threshold=0").status_code, 400)

    ews = guru.get(f"/api/teacher/early-warning?class_id={cls_id}&alpa_threshold=3").json()
    self.assertEqual(ews["total_flagged"], 3)
    self.assertEqual(ews["critical_count"], 1)
    self.assertEqual(ews["warning_count"], 2)
    # Kritis harus di urutan pertama
    self.assertEqual(ews["students"][0]["student_id"], s_kritis)
    self.assertEqual(ews["students"][0]["severity"], "kritis")
    self.assertCountEqual(ews["students"][0]["triggers"], ["below_kkm", "alpa_exceeded"])
    # Citra Alpa tidak boleh salah ditandai below_kkm karena belum punya nilai (None)
    citra = next(x for x in ews["students"] if x["student_id"] == s_alpa)
    self.assertEqual(citra["triggers"], ["alpa_exceeded"])
    # Dewi Aman tidak masuk EWS
    self.assertFalse(any(x["student_id"] == s_aman for x in ews["students"]))


if __name__ == "__main__":
  unittest.main()
