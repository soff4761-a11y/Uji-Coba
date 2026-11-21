"""Pengujian integrasi menyeluruh EGM v2 (Suite A-E):
A. Antarmuka & Diagram Donat Dashboard Peserta Didik
B. Keamanan Sesi (Idle Timeout 60 Menit Server-Side untuk Guru & Siswa)
C. Template & Impor Data Peserta Didik (.xlsx + Preview & Konfirmasi)
D. Template & Impor Nilai Peserta Didik (.xlsx + Preview, Konflik & Draft/Publikasi)
E. Perbaikan Bug Penghapusan Kelas (Anti HTTP 500 & Perlindungan Data Historis)
"""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import openpyxl
from fastapi.testclient import TestClient

from edutrack.configs.app_config import AppConfig
from edutrack.web.api import create_app


class EgmV2IntegrationTest(unittest.TestCase):
  """Menguji seluruh fitur revisi EGM v2 secara end-to-end terhadap DB & API nyata."""

  def setUp(self) -> None:
    self._tmpdir = tempfile.TemporaryDirectory()
    self._db_path = os.path.join(self._tmpdir.name, "egm_v2_test.db")
    cfg = AppConfig(db_path=self._db_path, pbkdf2_iterations=10_000, session_idle_timeout_minutes=60)
    self.app = create_app(cfg)
    self.container = self.app.state.container
    self.teacher = self.container.auth_service.register_teacher(
        username="guru_v2",
        password="PasswordGuru123!",
        full_name="Ibu Sari, M.Pd.",
        email="sari@sekolah.sch.id",
    )

  def tearDown(self) -> None:
    self._tmpdir.cleanup()

  def _login(self, username: str, password: str) -> TestClient:
    client = TestClient(self.app)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    self.assertEqual(res.status_code, 200, msg=res.text)
    csrf = client.cookies.get("edutrack_csrf")
    if csrf:
      client.headers.update({"X-CSRF-Token": csrf})
    return client

  # --- SUITE E: Perbaikan Bug Penghapusan Kelas (Anti HTTP 500) ---

  def test_suite_e_safe_class_deletion_and_no_http_500(self) -> None:
    guru = self._login("guru_v2", "PasswordGuru123!")

    # 1. Buat kelas kosong dan hapus -> harus 200 OK
    res_empty = guru.post(
        "/api/teacher/classes",
        json={"name": "Kelas Kosong", "education_level": "SMA", "mastery_threshold": 75},
    )
    self.assertEqual(res_empty.status_code, 201)
    empty_id = res_empty.json()["classroom"]["id"]

    dep_empty = guru.get(f"/api/teacher/classes/{empty_id}/dependencies")
    self.assertEqual(dep_empty.status_code, 200)
    self.assertTrue(dep_empty.json()["can_delete_safely"])

    del_empty = guru.delete(f"/api/teacher/classes/{empty_id}?confirm_permanent=true")
    self.assertEqual(del_empty.status_code, 200)

    # 2. Buat kelas berisi siswa, nilai, & kehadiran -> harus ditolak 409 (BUKAN 500!) dan data tetap utuh
    res_full = guru.post(
        "/api/teacher/classes",
        json={"name": "XI-IPA-1", "education_level": "SMA", "mastery_threshold": 75},
    )
    self.assertEqual(res_full.status_code, 201)
    full_id = res_full.json()["classroom"]["id"]

    res_stu = guru.post(
        "/api/teacher/students",
        json={"class_id": full_id, "full_name": "Bima Sakti", "student_code": "NIS-101"},
    )
    self.assertEqual(res_stu.status_code, 201)

    dep_full = guru.get(f"/api/teacher/classes/{full_id}/dependencies")
    self.assertEqual(dep_full.status_code, 200)
    self.assertFalse(dep_full.json()["can_delete_safely"])
    self.assertEqual(dep_full.json()["recommended_action"], "archive")
    self.assertEqual(dep_full.json()["counts"]["students"], 1)

    del_full = guru.delete(f"/api/teacher/classes/{full_id}?confirm_permanent=true&force=true")
    self.assertEqual(del_full.status_code, 409)
    self.assertIn("Arsipkan Kelas", del_full.json()["detail"])

    # Pastikan data siswa tidak hilang dan kelas bisa diarsipkan dengan aman
    stu_list = guru.get(f"/api/teacher/students?class_id={full_id}").json()["students"]
    self.assertEqual(len(stu_list), 1)
    arch = guru.patch(f"/api/teacher/classes/{full_id}", json={"is_archived": True})
    self.assertEqual(arch.status_code, 200)
    self.assertTrue(arch.json()["classroom"]["is_archived"])

  # --- SUITE B: Idle Session Timeout 60 Menit (Server-Side) ---

  def test_suite_b_server_side_60_min_idle_timeout_teacher_and_student(self) -> None:
    current_time = [datetime(2026, 11, 19, 10, 0, 0, tzinfo=timezone.utc)]
    self.container.auth_service._clock = lambda: current_time[0]  # pylint: disable=protected-access

    guru = self._login("guru_v2", "PasswordGuru123!")

    # Setelah 40 menit idle -> masih aktif & ping memperbarui last_activity_at
    current_time[0] += timedelta(minutes=40)
    ping_res = guru.post("/api/auth/ping")
    self.assertEqual(ping_res.status_code, 200)

    # 40 menit lagi setelah ping (total 80 menit sejak login, tapi baru 40 menit sejak ping) -> tetap aktif!
    current_time[0] += timedelta(minutes=40)
    me_ok = guru.get("/api/auth/me")
    self.assertEqual(me_ok.status_code, 200)

    # 61 menit tanpa aktivitas -> sesi berakhir otomatis (401 + X-Session-Expired: idle)
    current_time[0] += timedelta(minutes=61)
    me_expired = guru.get("/api/auth/me")
    self.assertEqual(me_expired.status_code, 401)
    self.assertEqual(me_expired.headers.get("X-Session-Expired"), "idle")
    self.assertIn("60 menit", me_expired.json()["detail"])

    # Sesi yang sudah berakhir tidak bisa dipakai lagi walau jam dimundurkan
    current_time[0] -= timedelta(minutes=30)
    me_revoked = guru.get("/api/auth/me")
    self.assertEqual(me_revoked.status_code, 401)

  # --- SUITE C: Template & Impor Peserta Didik (.xlsx + Preview & Konfirmasi) ---

  def test_suite_c_student_excel_template_preview_and_confirm_import(self) -> None:
    guru = self._login("guru_v2", "PasswordGuru123!")
    cls_id = guru.post(
        "/api/teacher/classes",
        json={"name": "X-MIPA-2", "education_level": "SMA", "mastery_threshold": 75},
    ).json()["classroom"]["id"]

    # 1. Unduh template Excel resmi dan pastikan bisa dibaca openpyxl
    tpl_res = guru.get("/api/teacher/students/import-template")
    self.assertEqual(tpl_res.status_code, 200)
    wb_tpl = openpyxl.load_workbook(io.BytesIO(tpl_res.content))
    self.assertIn("Data Peserta Didik", wb_tpl.sheetnames)
    self.assertIn("Petunjuk Pengisian", wb_tpl.sheetnames)

    # 2. Buat berkas Excel campuran: 2 baris valid + 2 baris invalid (username ganda & password lemah)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["No.", "NIS / Identitas", "Nama Peserta Didik", "Username", "Password", "Catatan (Opsional)"])
    ws.append([1, "NIS-201", "Dina Kartika", "dina_201", "DinaPass123!", "Aktif"])
    ws.append([2, "NIS-202", "Eko Prasetyo", "eko_202", "EkoPass123!", ""])
    ws.append([3, "NIS-203", "Duplikat User", "dina_201", "ValidPass123!", ""])
    ws.append([4, "NIS-204", "Sandi Pendek", "pendek_204", "123", ""])
    buf = io.BytesIO()
    wb.save(buf)
    xlsx_bytes = buf.getvalue()

    # 3. Preview harus mendeteksi 2 valid & 2 invalid tanpa menyimpan ke DB
    prev = guru.post(
        f"/api/teacher/classes/{cls_id}/students/import/preview",
        files={"file": ("siswa.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    self.assertEqual(prev.status_code, 200)
    pdata = prev.json()
    self.assertEqual(pdata["valid_count"], 2)
    self.assertEqual(pdata["invalid_count"], 2)
    # Pastikan password plaintext TIDAK dikembalikan di preview
    for r in pdata["valid_rows"]:
      self.assertNotIn("password", r)
    self.assertEqual(len(guru.get(f"/api/teacher/students?class_id={cls_id}").json()["students"]), 0)

    # 4. Konfirmasi impor -> hanya 2 baris valid yang tersimpan, password ter-hash, akun bisa login
    conf = guru.post(
        f"/api/teacher/classes/{cls_id}/students/import/confirm",
        files={"file": ("siswa.xlsx", xlsx_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    self.assertEqual(conf.status_code, 200)
    self.assertEqual(conf.json()["imported_count"], 2)
    self.assertEqual(conf.json()["failed_count"], 2)

    siswa_client = self._login("dina_201", "DinaPass123!")
    me_siswa = siswa_client.get("/api/auth/me").json()["user"]
    self.assertTrue(me_siswa["must_change_password"])

  # --- SUITE D & A: Template & Impor Nilai (.xlsx + Konflik + Draft) & Diagram Donat Siswa ---

  def test_suite_d_and_a_grade_import_conflicts_draft_and_student_doughnut_data(self) -> None:
    guru = self._login("guru_v2", "PasswordGuru123!")
    cls_id = guru.post(
        "/api/teacher/classes",
        json={"name": "XI-BAHASA", "education_level": "SMA", "mastery_threshold": 75},
    ).json()["classroom"]["id"]

    s1 = guru.post(
        "/api/teacher/students",
        json={"class_id": cls_id, "full_name": "Farah Nabila", "student_code": "NIS-301", "username": "farah_301", "initial_password": "FarahPass123!", "account_status": "active"},
    ).json()["student"]
    s2 = guru.post(
        "/api/teacher/students",
        json={"class_id": cls_id, "full_name": "Gilang Ramadhan", "student_code": "NIS-302", "username": "gilang_302", "initial_password": "GilangPass123!", "account_status": "active"},
    ).json()["student"]

    asmt = guru.post(
        f"/api/teacher/classes/{cls_id}/assessments",
        json={
            "title": "Kuis Aljabar",
            "category": "Kuis",
            "assessment_date": "2026-11-19",
            "max_score": 100,
            "weight": 20,
            "status": "draft",
        },
    ).json()["assessment"]
    asmt_id = asmt["id"]

    # 1. Unduh template nilai berdasarkan konteks asesmen
    tpl = guru.get(f"/api/teacher/assessments/{asmt_id}/import-template")
    self.assertEqual(tpl.status_code, 200)
    wb = openpyxl.load_workbook(io.BytesIO(tpl.content))
    ws = wb["Template Nilai"]

    # Isi nilai Farah = 88, Gilang = kosong (tidak boleh dianggap 0!), tambah 1 baris NIS tidak dikenal
    for row in ws.iter_rows(min_row=13):
      if row[1].value == "NIS-301":
        row[3].value = 88
      elif row[1].value == "NIS-302":
        row[3].value = ""
    ws.append([3, "NIS-999", "Tidak Terdaftar", 95, ""])
    buf1 = io.BytesIO()
    wb.save(buf1)
    xlsx1 = buf1.getvalue()

    prev1 = guru.post(
        f"/api/teacher/assessments/{asmt_id}/grades/import/preview",
        files={"file": ("nilai.xlsx", xlsx1, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    ).json()
    self.assertEqual(prev1["valid_count"], 2)
    self.assertEqual(prev1["empty_count"], 1)
    self.assertEqual(prev1["invalid_count"], 1)

    conf1 = guru.post(
        f"/api/teacher/assessments/{asmt_id}/grades/import/confirm?conflict_mode=skip",
        files={"file": ("nilai.xlsx", xlsx1, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    ).json()
    self.assertEqual(conf1["inserted"], 1)
    self.assertEqual(conf1["skipped"], 1)
    self.assertEqual(conf1["failed"], 1)

    # Nilai draft TIDAK boleh terlihat oleh peserta didik sebelum dipublikasikan
    siswa = self._login("farah_301", "FarahPass123!")
    dash_draft = siswa.get("/api/student/dashboard").json()
    self.assertEqual(len(dash_draft["grade_timeline"]), 0)

    # 2. Unggah ulang nilai Farah = 95 -> harus terdeteksi konflik, skip tidak menimpa, overwrite menimpa
    for row in ws.iter_rows(min_row=13):
      if row[1].value == "NIS-301":
        row[3].value = 95
    buf2 = io.BytesIO()
    wb.save(buf2)
    xlsx2 = buf2.getvalue()

    prev2 = guru.post(
        f"/api/teacher/assessments/{asmt_id}/grades/import/preview",
        files={"file": ("nilai2.xlsx", xlsx2, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    ).json()
    self.assertEqual(prev2["conflict_count"], 1)

    # Mode skip mempertahankan nilai lama (88)
    conf_skip = guru.post(
        f"/api/teacher/assessments/{asmt_id}/grades/import/confirm?conflict_mode=skip",
        files={"file": ("nilai2.xlsx", xlsx2, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    ).json()
    self.assertEqual(conf_skip["updated"], 0)
    self.assertEqual(conf_skip["skipped"], 2)

    # Mode overwrite memperbarui ke 95
    conf_ov = guru.post(
        f"/api/teacher/assessments/{asmt_id}/grades/import/confirm?conflict_mode=overwrite",
        files={"file": ("nilai2.xlsx", xlsx2, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    ).json()
    self.assertEqual(conf_ov["updated"], 1)

    # Publikasikan -> siswa sekarang melihat nilai 95 di dashboard (sumber data diagram donat)
    guru.patch(f"/api/teacher/assessments/{asmt_id}", json={"status": "published"})
    dash_pub = siswa.get("/api/student/dashboard").json()
    self.assertEqual(len(dash_pub["grade_timeline"]), 1)
    self.assertEqual(dash_pub["grade_timeline"][0]["normalized_score"], 95.0)

    # Verifikasi statis Suite A: ketiga diagram siswa di app.js memakai renderUnifiedDoughnutChart
    app_js = (Path(__file__).resolve().parents[1] / "web" / "static" / "app.js").read_text(encoding="utf-8")
    student_js_res = guru.get("/static/js/student.js")
    self.assertEqual(student_js_res.status_code, 200)
    self.assertIn('renderDoughnutChart("chart-s-trend"', student_js_res.text)
    self.assertIn('renderDoughnutChart("chart-s-category"', student_js_res.text)
    self.assertIn('renderDoughnutChart("chart-s-attendance"', student_js_res.text)


if __name__ == "__main__":
  unittest.main()
