"""Pengujian integrasi menyeluruh EGM v3 (Suite A-E):
A. Hapus Semua & Hapus Terpilih Peserta Didik (kelas terisolasi, proteksi riwayat, atomik)
B. Pengelolaan Materi Pembelajaran pada Penilaian & Buku Nilai (CRUD, arsip, anti-campur)
C. Dashboard Peserta Didik dengan Filter Materi (Semua Materi vs Materi Tertentu, draft tersembunyi)
D. Hapus Riwayat Permintaan Koreksi Siswa (pending -> hapus, terproses -> sembunyikan, anti-IDOR)
E. Antarmuka & Visualisasi (hapus 'DB: PostgreSQL Cloud', fix category_comparison di app.js)
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from edutrack.configs.app_config import AppConfig
from edutrack.web.api import create_app


class EgmV3IntegrationTest(unittest.TestCase):
  """Menguji seluruh fitur EGM v3 secara end-to-end terhadap DB, API, dan aset frontend."""

  def setUp(self) -> None:
    self._tmpdir = tempfile.TemporaryDirectory()
    self._db_path = os.path.join(self._tmpdir.name, "egm_v3_test.db")
    cfg = AppConfig(db_path=self._db_path, pbkdf2_iterations=10_000)
    self.app = create_app(cfg)
    self.container = self.app.state.container
    self.teacher = self.container.auth_service.register_teacher(
        username="guru_v3",
        password="PasswordGuru123!",
        full_name="Pak Hendra, S.Pd.",
        email="hendra@sekolah.sch.id",
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

  # --- SUITE A: Hapus Semua & Hapus Terpilih Peserta Didik ---

  def test_suite_a_bulk_delete_students_scoped_and_protected(self) -> None:
    guru = self._login("guru_v3", "PasswordGuru123!")
    cls_a = guru.post("/api/teacher/classes", json={"name": "X-A", "education_level": "SMA"}).json()["classroom"]["id"]
    cls_b = guru.post("/api/teacher/classes", json={"name": "X-B", "education_level": "SMA"}).json()["classroom"]["id"]

    s_a1 = guru.post("/api/teacher/students", json={"class_id": cls_a, "full_name": "Andi", "student_code": "A1"}).json()["student"]["id"]
    s_a2 = guru.post("/api/teacher/students", json={"class_id": cls_a, "full_name": "Budi", "student_code": "A2"}).json()["student"]["id"]
    s_b1 = guru.post("/api/teacher/students", json={"class_id": cls_b, "full_name": "Citra", "student_code": "B1"}).json()["student"]["id"]

    # Pratinjau harus menampilkan tepat 2 siswa pada kelas X-A
    prev = guru.get(f"/api/teacher/classes/{cls_a}/students/bulk-delete-preview")
    self.assertEqual(prev.status_code, 200)
    self.assertEqual(prev.json()["total_selected"], 2)

    # Mencoba memasukkan ID siswa kelas lain ke bulk-delete X-A -> harus ditolak 403 (all-or-nothing)
    cross = guru.post(
        f"/api/teacher/classes/{cls_a}/students/bulk-delete",
        json={"delete_all": False, "student_ids": [s_a1, s_b1], "mode": "permanent", "confirm": True},
    )
    self.assertEqual(cross.status_code, 403)
    self.assertEqual(len(guru.get(f"/api/teacher/students?class_id={cls_a}").json()["students"]), 2)

    # Mode archive: menonaktifkan seluruh siswa X-A tanpa memengaruhi X-B
    arch = guru.post(
        f"/api/teacher/classes/{cls_a}/students/bulk-delete",
        json={"delete_all": True, "mode": "archive", "confirm": True},
    )
    self.assertEqual(arch.status_code, 200)
    self.assertEqual(arch.json()["affected_count"], 2)
    self.assertEqual(len(guru.get(f"/api/teacher/students?class_id={cls_b}").json()["students"]), 1)

    # Mode permanent pada kelas X-A (tanpa riwayat lintas kelas) -> hapus 2 siswa, X-B tetap utuh
    perm = guru.post(
        f"/api/teacher/classes/{cls_a}/students/bulk-delete",
        json={"delete_all": True, "mode": "permanent", "confirm": True},
    )
    self.assertEqual(perm.status_code, 200)
    self.assertEqual(perm.json()["affected_count"], 2)
    self.assertEqual(len(guru.get(f"/api/teacher/students?class_id={cls_a}").json()["students"]), 0)
    self.assertEqual(len(guru.get(f"/api/teacher/students?class_id={cls_b}").json()["students"]), 1)

  # --- SUITE B & C: Materi Pembelajaran, Buku Nilai & Filter Materi Dashboard Siswa ---

  def test_suite_b_and_c_materials_gradebook_and_student_material_filter(self) -> None:
    guru = self._login("guru_v3", "PasswordGuru123!")
    cls_id = guru.post("/api/teacher/classes", json={"name": "XI-BINDO", "education_level": "SMA"}).json()["classroom"]["id"]

    stu = guru.post(
        "/api/teacher/students",
        json={
            "class_id": cls_id,
            "full_name": "Nadia Putri",
            "student_code": "NIS-501",
            "username": "nadia_501",
            "initial_password": "NadiaPass123!",
            "account_status": "active",
        },
    ).json()["student"]

    # Buat 2 Materi Pembelajaran
    m1 = guru.post(
        f"/api/teacher/classes/{cls_id}/materials",
        json={"title": "Bab 1: Teks Deskripsi", "description": "Struktur & kaidah", "sort_order": 1},
    ).json()["material"]
    m2 = guru.post(
        f"/api/teacher/classes/{cls_id}/materials",
        json={"title": "Bab 2: Teks Prosedur", "description": "Langkah sistematis", "sort_order": 2},
    ).json()["material"]

    # Buat penilaian terpisah untuk Bab 1 & Bab 2 (termasuk 1 draft)
    a1 = guru.post(
        f"/api/teacher/classes/{cls_id}/assessments",
        json={"title": "Kuis Bab 1", "category": "Kuis", "assessment_date": "2026-11-10", "max_score": 100, "weight": 20, "status": "published", "material_id": m1["id"]},
    ).json()["assessment"]
    a2 = guru.post(
        f"/api/teacher/classes/{cls_id}/assessments",
        json={"title": "Kuis Bab 2", "category": "Kuis", "assessment_date": "2026-11-15", "max_score": 100, "weight": 20, "status": "published", "material_id": m2["id"]},
    ).json()["assessment"]
    a2_draft = guru.post(
        f"/api/teacher/classes/{cls_id}/assessments",
        json={"title": "Tugas Bab 2 (Draft)", "category": "Tugas", "assessment_date": "2026-11-16", "max_score": 100, "weight": 20, "status": "draft", "material_id": m2["id"]},
    ).json()["assessment"]

    # Pastikan PATCH parsial (mis. ubah title) TIDAK menghapus material_id
    upd = guru.patch(f"/api/teacher/assessments/{a1['id']}", json={"title": "Kuis Bab 1 (Revisi)"})
    self.assertEqual(upd.status_code, 200)
    self.assertEqual(upd.json()["assessment"]["material_id"], m1["id"])

    # Input nilai berbeda untuk Bab 1 (80) dan Bab 2 (94) + draft (50)
    guru.post(f"/api/teacher/assessments/{a1['id']}/grades", json={"entries": [{"student_id": stu["id"], "score": 80, "feedback": "Baik"}]})
    guru.post(f"/api/teacher/assessments/{a2['id']}/grades", json={"entries": [{"student_id": stu["id"], "score": 94, "feedback": "Sangat baik"}]})
    guru.post(f"/api/teacher/assessments/{a2_draft['id']}/grades", json={"entries": [{"student_id": stu["id"], "score": 50, "feedback": "Draft"}]})

    # Materi yang masih memiliki penilaian tidak boleh dihapus permanen (409)
    del_m1 = guru.delete(f"/api/teacher/materials/{m1['id']}")
    self.assertEqual(del_m1.status_code, 409)

    # Buku Nilai terfilter materi Bab 1 hanya menampilkan penilaian Bab 1 (tidak bercampur dengan Bab 2)
    gb_m1 = guru.get(f"/api/teacher/classes/{cls_id}/gradebook?material_id={m1['id']}").json()
    self.assertEqual(len(gb_m1["assessments"]), 1)
    self.assertEqual(gb_m1["assessments"][0]["id"], a1["id"])
    self.assertEqual(gb_m1["rows"][0]["material_averages"][str(m1["id"])], 80.0)
    self.assertEqual(gb_m1["rows"][0]["material_averages"][str(m2["id"])], 94.0)

    # Dashboard Siswa: Semua Materi vs Materi Tertentu (nilai draft tidak boleh muncul!)
    siswa = self._login("nadia_501", "NadiaPass123!")
    dash_all = siswa.get("/api/student/dashboard").json()
    self.assertEqual(len(dash_all["materials"]), 2)
    self.assertEqual(len(dash_all["grade_timeline"]), 2)  # Hanya 2 published, draft tidak muncul
    self.assertEqual(len(dash_all["category_comparison"]), 1)
    self.assertEqual(dash_all["category_comparison"][0]["average"], 87.0)

    dash_m2 = siswa.get(f"/api/student/dashboard?material_id={m2['id']}").json()
    self.assertEqual(len(dash_m2["grade_timeline"]), 1)
    self.assertEqual(dash_m2["grade_timeline"][0]["title"], "Kuis Bab 2")
    self.assertEqual(dash_m2["grade_timeline"][0]["normalized_score"], 94.0)
    self.assertEqual(dash_m2["category_comparison"][0]["average"], 94.0)

  # --- SUITE D: Hapus Riwayat Permintaan Koreksi Siswa ---

  def test_suite_d_student_delete_correction_pending_vs_processed_and_idor(self) -> None:
    guru = self._login("guru_v3", "PasswordGuru123!")
    cls_id = guru.post("/api/teacher/classes", json={"name": "XII-A", "education_level": "SMA"}).json()["classroom"]["id"]
    s1 = guru.post(
        "/api/teacher/students",
        json={"class_id": cls_id, "full_name": "Siswa Satu", "student_code": "S1", "username": "siswa_satu", "initial_password": "Password123!", "account_status": "active"},
    ).json()["student"]
    guru.post(
        "/api/teacher/students",
        json={"class_id": cls_id, "full_name": "Siswa Dua", "student_code": "S2", "username": "siswa_dua", "initial_password": "Password123!", "account_status": "active"},
    )
    asmt = guru.post(
        f"/api/teacher/classes/{cls_id}/assessments",
        json={"title": "Ujian 1", "category": "Ujian", "assessment_date": "2026-11-18", "max_score": 100, "weight": 10, "status": "published"},
    ).json()["assessment"]
    guru.post(f"/api/teacher/assessments/{asmt['id']}/grades", json={"entries": [{"student_id": s1["id"], "score": 70}]})

    siswa1 = self._login("siswa_satu", "Password123!")
    siswa2 = self._login("siswa_dua", "Password123!")

    c_pending = siswa1.post("/api/student/corrections", json={"target_type": "grade", "target_id": asmt["id"], "message": "Salah ketik nilai pending"}).json()["correction"]
    c_done = siswa1.post("/api/student/corrections", json={"target_type": "grade", "target_id": asmt["id"], "message": "Mohon dicek kembali"}).json()["correction"]

    # Guru menanggapi c_done
    guru.patch(f"/api/teacher/corrections/{c_done['id']}", json={"status": "resolved", "teacher_response": "Sudah dicek, nilai benar 70."})

    # IDOR check: siswa2 mencoba menghapus koreksi siswa1 -> 403 Forbidden
    idor = siswa2.delete(f"/api/student/corrections/{c_pending['id']}")
    self.assertEqual(idor.status_code, 403)

    # Siswa1 menghapus c_pending -> dihapus permanen
    del_p = siswa1.delete(f"/api/student/corrections/{c_pending['id']}")
    self.assertEqual(del_p.status_code, 200)
    self.assertEqual(del_p.json()["status"], "deleted")

    # Siswa1 menghapus c_done (sudah diproses guru) -> disembunyikan dari siswa, tetapi TETAP ADA di guru!
    del_d = siswa1.delete(f"/api/student/corrections/{c_done['id']}")
    self.assertEqual(del_d.status_code, 200)
    self.assertEqual(del_d.json()["status"], "hidden")
    self.assertEqual(len(siswa1.get("/api/student/corrections").json()["corrections"]), 0)
    teacher_corrs = guru.get("/api/teacher/corrections").json()["corrections"]
    self.assertEqual(len(teacher_corrs), 1)
    self.assertEqual(teacher_corrs[0]["id"], c_done["id"])

  # --- SUITE E: Antarmuka & Visualisasi (No DB Badge + category_comparison Fix) ---

  def test_suite_e_ui_no_db_badge_and_doughnut_category_fix(self) -> None:
    static_dir = Path(__file__).resolve().parents[1] / "web" / "static"
    idx_html = (static_dir / "index.html").read_text(encoding="utf-8")
    app_js = (static_dir / "app.js").read_text(encoding="utf-8")

    self.assertNotIn("db-backend-badge", idx_html)
    self.assertNotIn("DB: PostgreSQL Cloud", app_js)
    student_js_res = TestClient(self.app).get("/static/js/student.js")
    self.assertEqual(student_js_res.status_code, 200)
    self.assertIn("data.category_comparison", student_js_res.text)
    self.assertIn("s-filter-material", idx_html)


  # --- SUITE F: Regresi Audit Goldfish v4 (PG request_scope, PATCH material_id, UI parity, CSS) ---

  def test_suite_f_goldfish_v4_regressions(self) -> None:
    guru = self._login("guru_v3", "PasswordGuru123!")
    cls_id = guru.post("/api/teacher/classes", json={"name": "XI-F", "education_level": "SMA"}).json()["classroom"]["id"]
    m1 = guru.post(f"/api/teacher/classes/{cls_id}/materials", json={"title": "Bab 1"}).json()["material"]
    m2 = guru.post(f"/api/teacher/classes/{cls_id}/materials", json={"title": "Bab 2"}).json()["material"]
    asmt = guru.post(
        f"/api/teacher/classes/{cls_id}/assessments",
        json={"title": "Tugas Awal", "category": "Tugas", "assessment_date": "2026-11-18", "max_score": 100, "weight": 10, "status": "published", "material_id": m1["id"]},
    ).json()["assessment"]

    # Blocker #4: PATCH assessment dengan material_id non-null tidak boleh NameError (500)
    patch_mat = guru.patch(f"/api/teacher/assessments/{asmt['id']}", json={"material_id": m2["id"]})
    self.assertEqual(patch_mat.status_code, 200)
    self.assertEqual(patch_mat.json()["assessment"]["material_id"], m2["id"])

    # Blocker #3: material_summary menyertakan id, material_id, is_archived, status
    gb = guru.get(f"/api/teacher/classes/{cls_id}/gradebook").json()
    m_item = next(x for x in gb["material_summary"] if x["material_id"] == m2["id"])
    self.assertEqual(m_item["id"], m2["id"])
    self.assertIn("is_archived", m_item)
    self.assertFalse(m_item["is_archived"])

    # Major #8: student_ids non-numerik mengembalikan 400 bukan 500
    bad_prev = guru.get(f"/api/teacher/classes/{cls_id}/students/bulk-delete-preview?student_ids=abc")
    self.assertEqual(bad_prev.status_code, 400)

    # Blocker #2 & Major #5/#6: Verifikasi HTML & CSS (tombol hapus massal + 6 kolom tabel + min-width:0)
    html = guru.get("/").text
    self.assertIn('id="chk-select-all-students"', html)
    self.assertIn('id="btn-bulk-delete-selected"', html)
    self.assertIn('id="btn-bulk-delete-all"', html)
    self.assertIn('id="s-filter-material"', html)
    self.assertIn('id="form-material"', html)
    self.assertNotIn("DB: PostgreSQL Cloud", html)
    css = guru.get("/static/styles.css").text
    self.assertIn("min-width: 0;", css)
    self.assertIn('input[type="checkbox"]', css)

  def test_suite_f_postgres_request_scope_reuses_single_connection(self) -> None:
    from edutrack.repositories.database import Database

    open_count = 0
    class _DummyCursor:
      rowcount = 1
      lastrowid = 1
      def execute(self, sql, params=()): pass
      def fetchone(self): return {"id": 1}
      def fetchall(self): return []
      def close(self): pass

    class _DummyConn:
      def __init__(self): self.closed = False
      def cursor(self): return _DummyCursor()
      def commit(self): pass
      def rollback(self): pass
      def close(self): self.closed = True

    def _connector(_url):
      nonlocal open_count
      open_count += 1
      return _DummyConn()

    db = Database(database_url="postgresql://u:p@host/db", pg_connector=_connector)
    open_after_init = open_count
    with db.request_scope():
      with db.connection() as c1:
        c1.execute("SELECT 1")
      with db.connection() as c2:
        c2.execute("SELECT 1")
      with db.connection() as c3:
        c3.execute("SELECT 1")
    self.assertEqual(open_count - open_after_init, 1)

  # --- SUITE G: Dashboard Siswa Sidebar Dinamis, Jam Real-Time & PDF Bergrafik (v5) ---

  def test_suite_g_student_sidebar_clock_and_visual_pdf_report(self) -> None:
    guru = self._login("guru_v3", "PasswordGuru123!")
    cls_id = guru.post("/api/teacher/classes", json={"name": "XII-IPA-1", "education_level": "SMA"}).json()["classroom"]["id"]
    stu = guru.post(
        "/api/teacher/students",
        json={"class_id": cls_id, "full_name": "Budi Santoso", "student_code": "NIS-777", "username": "budi_777", "initial_password": "Password123!", "account_status": "active"},
    ).json()["student"]
    mat = guru.post(f"/api/teacher/classes/{cls_id}/materials", json={"title": "Bab 1: Dinamika"}).json()["material"]
    a1 = guru.post(
        f"/api/teacher/classes/{cls_id}/assessments",
        json={"title": "Kuis 1", "category": "Kuis", "assessment_date": "2026-11-18", "max_score": 100, "weight": 20, "status": "published", "material_id": mat["id"]},
    ).json()["assessment"]
    a2 = guru.post(
        f"/api/teacher/classes/{cls_id}/assessments",
        json={"title": "Tugas 1", "category": "Tugas", "assessment_date": "2026-11-19", "max_score": 100, "weight": 30, "status": "published", "material_id": mat["id"]},
    ).json()["assessment"]
    guru.post(f"/api/teacher/assessments/{a1['id']}/grades", json={"entries": [{"student_id": stu["id"], "score": 85, "feedback": "Bagus"}]})
    guru.post(f"/api/teacher/assessments/{a2['id']}/grades", json={"entries": [{"student_id": stu["id"], "score": 92, "feedback": "Sangat baik"}]})

    ses = guru.post(f"/api/teacher/classes/{cls_id}/attendance/sessions", json={"session_date": "2026-11-18", "meeting_number": 1, "topic": "Pertemuan 1"}).json()["session"]
    guru.post(f"/api/teacher/attendance/sessions/{ses['id']}/records", json={"records": [{"student_id": stu["id"], "status": "hadir", "note": ""}]})

    # 1. Verifikasi struktur HTML dashboard siswa v5 (sidebar dinamis + identitas di topbar + jam real-time)
    html = guru.get("/").text
    self.assertIn('id="student-sidebar"', html)
    self.assertIn('id="btn-collapse-student-sidebar"', html)
    self.assertIn('id="st-realtime-clock"', html)
    self.assertIn('id="st-clock-text"', html)
    self.assertIn('id="st-header-name"', html)
    self.assertIn('id="st-header-class"', html)

    # 2. Verifikasi PDF laporan individu siswa, nilai kelas, dan kehadiran kelas ter-generate valid
    siswa = self._login("budi_777", "Password123!")
    pdf_st = siswa.get("/api/reports/individual?fmt=pdf")
    self.assertEqual(pdf_st.status_code, 200)
    self.assertTrue(pdf_st.content.startswith(b"%PDF-"))
    self.assertGreater(len(pdf_st.content), 3000)

    pdf_cls = guru.get(f"/api/reports/class/{cls_id}/grades?fmt=pdf")
    self.assertEqual(pdf_cls.status_code, 200)
    self.assertTrue(pdf_cls.content.startswith(b"%PDF-"))

    pdf_att = guru.get(f"/api/reports/class/{cls_id}/attendance?fmt=pdf")
    self.assertEqual(pdf_att.status_code, 200)
    self.assertTrue(pdf_att.content.startswith(b"%PDF-"))

if __name__ == "__main__":
  unittest.main()
