"""Pengujian E2E & Keamanan Wajib (Bagian 16): RBAC, anti-IDOR, persistensi sesi, laporan Excel/CSV/PDF."""

from __future__ import annotations

import tempfile
import unittest

from fastapi.testclient import TestClient

from edutrack.configs.app_config import AppConfig
from edutrack.web.api import create_app


class ApiSecurityE2ETest(unittest.TestCase):
  """Menguji seluruh alur Guru, Peserta Didik, penolakan IDOR, dan integritas data."""

  def setUp(self) -> None:
    self._tmpdir = tempfile.TemporaryDirectory()
    cfg = AppConfig(
        db_path=f"{self._tmpdir.name}/e2e.db",
        backup_dir=f"{self._tmpdir.name}/backups",
        pbkdf2_iterations=12_000,
    )
    self.app = create_app(cfg)
    self.container = self.app.state.container
    self.container.auth_service.register_teacher("guru_a", "PassGuruA123!", "Guru A")
    self.container.auth_service.register_teacher("guru_b", "PassGuruB123!", "Guru B")

  def tearDown(self) -> None:
    self._tmpdir.cleanup()

  def _login_client(self, username: str, password: str) -> TestClient:
    client = TestClient(self.app)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    self.assertEqual(res.status_code, 200, res.text)
    csrf = client.cookies.get("edutrack_csrf", "")
    if csrf:
      client.headers["X-CSRF-Token"] = csrf
    return client

  def test_full_teacher_student_flow_and_idor_security(self) -> None:
    # 1. Guru A login, buat periode, kelas, dan dua peserta didik
    guru_a = self._login_client("guru_a", "PassGuruA123!")
    p_res = guru_a.post(
        "/api/teacher/periods",
        json={"name": "Ganjil 2026/2027", "academic_year": "2026/2027", "semester": "Ganjil"},
    )
    self.assertEqual(p_res.status_code, 201)
    period_id = p_res.json()["period"]["id"]

    c_res = guru_a.post(
        "/api/teacher/classes",
        json={"period_id": period_id, "name": "X-1", "education_level": "SMA X", "mastery_threshold": 75},
    )
    self.assertEqual(c_res.status_code, 201)
    class_id = c_res.json()["classroom"]["id"]

    s1_res = guru_a.post(
        "/api/teacher/students",
        json={
            "class_id": class_id, "full_name": "Siswa Satu", "student_code": "S001",
            "username": "siswa_1", "initial_password": "TempPass123!",
        },
    )
    self.assertEqual(s1_res.status_code, 201)
    s1_id = s1_res.json()["student"]["id"]

    s2_res = guru_a.post(
        "/api/teacher/students",
        json={
            "class_id": class_id, "full_name": "Siswa Dua", "student_code": "S002",
            "username": "siswa_2", "initial_password": "TempPass456!",
        },
    )
    self.assertEqual(s2_res.status_code, 201)
    s2_id = s2_res.json()["student"]["id"]

    # 2. Guru A buat 2 penilaian: 1 draft & 1 published, lalu input nilai
    a_draft = guru_a.post(
        f"/api/teacher/classes/{class_id}/assessments",
        json={
            "title": "Tugas Rahasia Draft", "category": "Tugas", "assessment_date": "2026-09-01",
            "max_score": 100, "weight": 40, "status": "draft",
        },
    ).json()["assessment"]
    a_pub = guru_a.post(
        f"/api/teacher/classes/{class_id}/assessments",
        json={
            "title": "Ujian Harian 1", "category": "Ujian", "assessment_date": "2026-09-10",
            "max_score": 100, "weight": 60, "status": "published",
        },
    ).json()["assessment"]

    # Simpan nilai: s1=90 pada published & 50 pada draft; s2=None (belum dinilai)
    guru_a.post(
        f"/api/teacher/assessments/{a_pub['id']}/grades",
        json={"entries": [{"student_id": s1_id, "score": 90, "feedback": "Sangat baik"}, {"student_id": s2_id, "score": None, "feedback": ""}]},
    )
    guru_a.post(
        f"/api/teacher/assessments/{a_draft['id']}/grades",
        json={"entries": [{"student_id": s1_id, "score": 50, "feedback": "Draft"}]},
    )

    # 3. Guru A catat kehadiran & uji pencegahan duplikasi sesi
    att_res = guru_a.post(
        f"/api/teacher/classes/{class_id}/attendance/sessions",
        json={"session_date": "2026-09-10", "meeting_number": 1, "topic": "Bab 1", "mark_all_present": True},
    )
    self.assertEqual(att_res.status_code, 201)
    session_id = att_res.json()["session"]["id"]

    dup_att = guru_a.post(
        f"/api/teacher/classes/{class_id}/attendance/sessions",
        json={"session_date": "2026-09-10", "meeting_number": 1, "topic": "Duplikat"},
    )
    self.assertEqual(dup_att.status_code, 409)

    # Koreksi kehadiran siswa_2 menjadi alpa -> harus tercatat di riwayat
    guru_a.post(
        f"/api/teacher/attendance/sessions/{session_id}/records",
        json={"entries": [{"student_id": s2_id, "status": "alpa", "note": "Tanpa keterangan"}], "reason": "Verifikasi ulang"},
    )
    att_hist = guru_a.get(f"/api/teacher/classes/{class_id}/attendance/history").json()["history"]
    self.assertTrue(any(h["new_status"] == "alpa" and h["old_status"] == "hadir" for h in att_hist))

    # 4. Siswa 1 login, wajib ganti kata sandi pertama kali, lalu verifikasi isolasi data
    siswa_1 = self._login_client("siswa_1", "TempPass123!")
    me_before = siswa_1.get("/api/auth/me").json()["user"]
    self.assertTrue(me_before["must_change_password"])

    ch_pw = siswa_1.post(
        "/api/auth/change-password",
        json={"current_password": "TempPass123!", "new_password": "SandiBaruSiswa1!"},
    )
    self.assertEqual(ch_pw.status_code, 200)
    siswa_1.headers["X-CSRF-Token"] = siswa_1.cookies.get("edutrack_csrf", "")
    self.assertFalse(ch_pw.json()["user"]["must_change_password"])
    self.assertEqual(ch_pw.json()["user"]["status"], "active")

    # Dashboard siswa_1 hanya menampilkan penilaian PUBLISHED (bukan draft!)
    st_dash = siswa_1.get("/api/student/dashboard").json()
    self.assertEqual(len(st_dash["grade_timeline"]), 1)
    self.assertEqual(st_dash["grade_timeline"][0]["title"], "Ujian Harian 1")
    self.assertAlmostEqual(st_dash["grade_summary"]["final_score"], 90.0)
    self.assertAlmostEqual(st_dash["attendance_summary"]["attendance_percentage"], 100.0)

    # Siswa 1 ajukan permintaan koreksi (tidak mengubah nilai!)
    corr = siswa_1.post(
        "/api/student/corrections",
        json={"target_type": "grade", "target_id": a_pub["id"], "message": "Mohon cek ulang soal nomor 3."},
    )
    self.assertEqual(corr.status_code, 201)

    # 5. PENGUJIAN KEAMANAN & ANTI-IDOR (Siswa mencoba akses endpoint guru / data siswa lain)
    self.assertEqual(siswa_1.get("/api/teacher/dashboard").status_code, 403)
    self.assertEqual(siswa_1.get(f"/api/teacher/classes/{class_id}/gradebook").status_code, 403)
    self.assertEqual(siswa_1.get(f"/api/teacher/students/{s2_id}/progress").status_code, 403)
    self.assertEqual(
        siswa_1.post(f"/api/teacher/assessments/{a_pub['id']}/grades", json={"entries": []}).status_code,
        403,
    )
    # IDOR: siswa_1 mencoba unduh laporan siswa_2 lewat parameter student_id!
    self.assertEqual(
        siswa_1.get(f"/api/reports/individual?student_id={s2_id}&fmt=pdf").status_code,
        403,
    )
    # Laporan milik sendiri diizinkan selama diaktifkan guru
    self.assertEqual(
        siswa_1.get("/api/reports/individual?fmt=pdf").status_code, 200
    )

    # 6. Isolasi antarguru (Guru B tidak boleh mengakses kelas/siswa Guru A!)
    guru_b = self._login_client("guru_b", "PassGuruB123!")
    self.assertEqual(guru_b.get(f"/api/teacher/classes/{class_id}").status_code, 403)
    self.assertEqual(guru_b.get(f"/api/teacher/classes/{class_id}/gradebook").status_code, 403)
    self.assertEqual(guru_b.get(f"/api/teacher/students/{s1_id}/progress").status_code, 403)
    self.assertEqual(guru_b.get(f"/api/reports/class/{class_id}/grades?fmt=xlsx").status_code, 403)

    # 7. Ekspor laporan Guru A (Excel, CSV, PDF) harus menghasilkan berkas valid
    for endpoint in [
        f"/api/reports/class/{class_id}/grades?fmt=xlsx",
        f"/api/reports/class/{class_id}/grades?fmt=csv",
        f"/api/reports/class/{class_id}/grades?fmt=pdf",
        f"/api/reports/class/{class_id}/attendance?fmt=xlsx",
        f"/api/reports/class/{class_id}/attendance?fmt=pdf",
    ]:
      r = guru_a.get(endpoint)
      self.assertEqual(r.status_code, 200, endpoint)
      self.assertGreater(len(r.content), 50)

    # 8. Persistensi setelah logout & login ulang dengan sandi baru
    self.assertEqual(siswa_1.post("/api/auth/logout").status_code, 200)
    self.assertEqual(siswa_1.get("/api/student/dashboard").status_code, 401)

    siswa_1_relogin = self._login_client("siswa_1", "SandiBaruSiswa1!")
    st_dash_after = siswa_1_relogin.get("/api/student/dashboard").json()
    self.assertAlmostEqual(st_dash_after["grade_summary"]["final_score"], 90.0)



  def test_teacher_change_login_username_and_student_crud_delete_rollback(self) -> None:
    guru_a = self._login_client("guru_a", "PassGuruA123!")

    # 1. Health endpoint
    health = guru_a.get("/api/health")
    self.assertEqual(health.status_code, 200)
    self.assertEqual(health.json()["database_backend"], "sqlite")

    # 2. Ubah username login guru & verifikasi login dengan username baru
    upd = guru_a.patch(
        "/api/auth/profile",
        json={"username": "guru_a_baru", "full_name": "Guru A Updated"},
    )
    self.assertEqual(upd.status_code, 200, upd.text)
    self.assertEqual(upd.json()["user"]["username"], "guru_a_baru")

    # Username dengan spasi harus ditolak (400), duplikat ditolak (409)
    self.assertEqual(
        guru_a.patch("/api/auth/profile", json={"username": "ada spasi"}).status_code, 400
    )
    self.assertEqual(
        guru_a.patch("/api/auth/profile", json={"username": "guru_b"}).status_code, 409
    )

    relogin = self._login_client("guru_a_baru", "PassGuruA123!")

    # 3. Buat periode, kelas, tambah murid, uji rollback bersih bila NIS duplikat
    pid = relogin.post(
        "/api/teacher/periods",
        json={"name": "Genap 2026/2027", "academic_year": "2026/2027", "semester": "Genap"},
    ).json()["period"]["id"]
    cid = relogin.post(
        "/api/teacher/classes",
        json={"period_id": pid, "name": "XI-1", "education_level": "SMA XI"},
    ).json()["classroom"]["id"]

    s1 = relogin.post(
        "/api/teacher/students",
        json={"class_id": cid, "full_name": "Murid A", "student_code": "M001", "username": "murid_a"},
    )
    self.assertEqual(s1.status_code, 201)
    s1_id = s1.json()["student"]["id"]

    # Gagal karena NIS duplikat -> akun user 'murid_retry' harus ter-rollback bersih!
    dup_nis = relogin.post(
        "/api/teacher/students",
        json={"class_id": cid, "full_name": "Murid B", "student_code": "M001", "username": "murid_retry"},
    )
    self.assertEqual(dup_nis.status_code, 409)

    # Coba lagi dengan NIS valid & username 'murid_retry' -> harus BERHASIL (tidak terganjal akun yatim!)
    retry_ok = relogin.post(
        "/api/teacher/students",
        json={"class_id": cid, "full_name": "Murid B", "student_code": "M002", "username": "murid_retry"},
    )
    self.assertEqual(retry_ok.status_code, 201, retry_ok.text)
    s2_id = retry_ok.json()["student"]["id"]

    # 4. Edit username murid & hapus murid (nonaktifkan -> hapus permanen)
    ed = relogin.patch(
        f"/api/teacher/students/{s2_id}",
        json={"full_name": "Murid B Revisi", "username": "murid_b_baru"},
    )
    self.assertEqual(ed.status_code, 200)
    self.assertEqual(ed.json()["student"]["username"], "murid_b_baru")

    # Hapus tanpa nonaktif -> 400
    self.assertEqual(
        relogin.delete(f"/api/teacher/students/{s1_id}?confirm_permanent=true").status_code, 400
    )
    # Nonaktifkan lalu hapus permanen -> 200
    self.assertEqual(
        relogin.patch(f"/api/teacher/students/{s1_id}", json={"account_status": "deactivated"}).status_code,
        200,
    )
    self.assertEqual(
        relogin.delete(f"/api/teacher/students/{s1_id}?confirm_permanent=true").status_code, 200
    )
    remaining = relogin.get(f"/api/teacher/students?class_id={cid}").json()["students"]
    self.assertEqual(len(remaining), 1)
    self.assertEqual(remaining[0]["id"], s2_id)

if __name__ == "__main__":
  unittest.main()
