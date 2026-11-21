"""Pengujian 3-kategori (happy path, edge/empty, error/invalid) untuk EduTrack v8.2."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from fastapi.testclient import TestClient

from edutrack.configs.app_config import AppConfig
from edutrack.domain.errors import ValidationError
from edutrack.domain.models import AssessmentStatus
from edutrack.services.analytics_service import evaluate_student_ews
from edutrack.web.api import create_app


class EgmV82CorrectionsAndStudentEwsTest(unittest.TestCase):
  """Memverifikasi perbaikan koreksi guru dan pop-up EWS 3 detik dashboard siswa."""

  def setUp(self) -> None:
    self._tmpdir = tempfile.TemporaryDirectory()
    self._db_path = os.path.join(self._tmpdir.name, "edutrack_v8_2.db")
    self._cfg = AppConfig(
        db_path=self._db_path,
        backup_dir=os.path.join(self._tmpdir.name, "backups"),
        pbkdf2_iterations=10_000,
        seed_demo_data=False,
        ews_alpa_threshold=3,
    )
    self._app = create_app(self._cfg)
    self._container = self._app.state.container
    self._teacher = self._container.auth_service.register_teacher(
        "guru_v82", "PasswordGuru123!", "Guru V82"
    )

  def tearDown(self) -> None:
    self._tmpdir.cleanup()

  def _login(self, username: str, password: str) -> TestClient:
    client = TestClient(self._app)
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    self.assertEqual(res.status_code, 200, res.text)
    client.headers["X-CSRF-Token"] = client.cookies.get("edutrack_csrf", "")
    return client

  # 1. Happy Path: Koreksi siswa sampai ke guru biasa (non-admin) & EWS siswa terpicu
  def test_1_happy_path_student_correction_reaches_teacher_and_student_ews_triggered(self) -> None:
    guru = self._login("guru_v82", "PasswordGuru123!")
    cls_id = guru.post(
        "/api/teacher/classes",
        json={"name": "XI-V82", "education_level": "SMA", "mastery_threshold": 75.0},
    ).json()["classroom"]["id"]
    stu_res = guru.post(
        "/api/teacher/students",
        json={"class_id": cls_id, "full_name": "Nadia Putri", "student_code": "20268201", "account_status": "active"},
    ).json()
    stu_id = stu_res["student"]["id"]

    asmt = guru.post(
        f"/api/teacher/classes/{cls_id}/assessments",
        json={"title": "UH 1", "category": "UH", "assessment_date": "2026-11-10", "status": "published"},
    ).json()["assessment"]
    # Nilai 65 (< KKM 75) -> memicu EWS below_kkm
    guru.post(
        f"/api/teacher/assessments/{asmt['id']}/grades",
        json={"entries": [{"student_id": stu_id, "score": 65}]},
    )

    # Siswa login & ganti sandi pertama
    siswa = self._login("20268201", "12345678")
    siswa.post("/api/auth/change-password", json={"current_password": "12345678", "new_password": "SandiSiswa99!"})
    siswa.headers["X-CSRF-Token"] = siswa.cookies.get("edutrack_csrf", "")

    # Siswa kirim permintaan koreksi
    sent = siswa.post(
        "/api/student/corrections",
        json={"target_type": "grade", "target_id": asmt["id"], "message": "Mohon cek kembali nilai UH 1 saya."},
    )
    self.assertEqual(sent.status_code, 201, sent.text)

    # Guru non-admin tetap ditolak di /api/teacher/backups (403), namun /api/teacher/corrections sukses (200)
    self.assertEqual(guru.get("/api/teacher/backups").status_code, 403)
    t_corrs = guru.get("/api/teacher/corrections")
    self.assertEqual(t_corrs.status_code, 200)
    items = t_corrs.json()["corrections"]
    self.assertEqual(len(items), 1)
    self.assertEqual(items[0]["message"], "Mohon cek kembali nilai UH 1 saya.")
    self.assertEqual(items[0]["student_name"], "Nadia Putri")

    # Dashboard siswa memuat objek early_warning dengan is_triggered=True
    s_dash = siswa.get("/api/student/dashboard").json()
    ews = s_dash["early_warning"]
    self.assertTrue(ews["is_triggered"])
    self.assertEqual(ews["severity"], "perhatian")
    self.assertEqual(ews["triggers"], ["below_kkm"])
    self.assertIn("65.0", ews["message"])

    # Tambahkan 3 alpa -> severity naik menjadi kritis (below_kkm + alpa_exceeded)
    for d in range(1, 4):
      ses = guru.post(
          f"/api/teacher/classes/{cls_id}/attendance/sessions",
          json={"session_date": f"2026-11-0{d}", "meeting_number": d},
      ).json()["session"]
      guru.post(
          f"/api/teacher/attendance/sessions/{ses['id']}/records",
          json={"entries": [{"student_id": stu_id, "status": "alpa"}]},
      )
    s_dash2 = siswa.get("/api/student/dashboard").json()
    self.assertEqual(s_dash2["early_warning"]["severity"], "kritis")
    self.assertEqual(s_dash2["early_warning"]["triggers"], ["below_kkm", "alpa_exceeded"])

  # 2. Edge / Empty Cases & Error / Invalid Cases pada evaluate_student_ews
  def test_2_evaluate_student_ews_edge_and_invalid_cases(self) -> None:
    # Empty / belum ada nilai & 0 alpa -> aman
    empty = evaluate_student_ews(None, 75.0, 0, 3)
    self.assertFalse(empty["is_triggered"])
    self.assertEqual(empty["severity"], "aman")
    self.assertEqual(empty["reasons"], [])
    self.assertEqual(empty["message"], "")

    # Boundary tepat KKM & alpa 1 di bawah batas -> aman
    boundary_ok = evaluate_student_ews(75.0, 75.0, 2, 3)
    self.assertFalse(boundary_ok["is_triggered"])

    # Invalid inputs -> ValidationError
    with self.assertRaises(ValidationError):
      evaluate_student_ews(80.0, 75.0, 0, 0)
    with self.assertRaises(ValidationError):
      evaluate_student_ews(80.0, 75.0, -1, 3)
    with self.assertRaises(ValidationError):
      evaluate_student_ews(float("nan"), 75.0, 0, 3)
    with self.assertRaises(ValidationError):
      evaluate_student_ews(105.0, 75.0, 0, 3)
    with self.assertRaises(ValidationError):
      evaluate_student_ews(80.0, -5.0, 0, 3)

  # 3. Frontend Isolation (teacher.js) & Deterministic Node Test Pop-up EWS 3 Detik (student.js)
  def test_3_teacher_isolated_loader_and_student_ews_popup_3s_runtime(self) -> None:
    static_dir = Path(__file__).resolve().parent.parent / "web" / "static"
    teacher_js = (static_dir / "js" / "teacher.js").read_text(encoding="utf-8")
    self.assertIn("Promise.allSettled", teacher_js)
    self.assertIn('isAdmin ? api("/api/teacher/backups")', teacher_js)
    self.assertIn("if (rawResponse === null) return;", teacher_js)

    styles_css = (static_dir / "styles.css").read_text(encoding="utf-8")
    self.assertIn("#student-ews-popup.ews-popup", styles_css)

    # Uji runtime Node untuk showStudentEwsPopup & dismissStudentEwsPopup
    with tempfile.TemporaryDirectory() as tmp:
      tmp_dir = Path(tmp)
      (tmp_dir / "package.json").write_text('{"type": "module"}', encoding="utf-8")
      for name in ("state.js", "api.js", "charts.js", "student.js"):
        src = (static_dir / "js" / name).read_text(encoding="utf-8")
        src = re.sub(r'(\./[a-z]+\.js)\?v=[^"\x27]+', r"\1", src)
        (tmp_dir / name).write_text(src, encoding="utf-8")

      runner = tmp_dir / "test_popup.mjs"
      runner.write_text(
          """
const domMap = new Map();
const bodyChildren = [];
let scheduled = [];
let cleared = [];
let nextTimerId = 1;

globalThis.setTimeout = (fn, ms) => {
  const id = nextTimerId++;
  scheduled.push({ id, fn, ms });
  return id;
};
globalThis.clearTimeout = (id) => {
  cleared.push(id);
};
globalThis.document = {
  body: {
    appendChild(el) {
      bodyChildren.push(el);
      if (el.id) domMap.set(el.id, el);
    },
  },
  getElementById(id) {
    return domMap.get(id) || null;
  },
  createElement(tag) {
    const el = {
      tag,
      id: "",
      className: "",
      innerHTML: "",
      attrs: {},
      listeners: {},
      setAttribute(k, v) { this.attrs[k] = v; },
      addEventListener(evt, fn) { this.listeners[evt] = fn; },
      remove() {
        const idx = bodyChildren.indexOf(el);
        if (idx >= 0) bodyChildren.splice(idx, 1);
        if (el.id && domMap.get(el.id) === el) domMap.delete(el.id);
      },
    };
    return el;
  },
};

import { showStudentEwsPopup, dismissStudentEwsPopup } from "./student.js";

// 1. Tidak terpicu -> tidak menambah elemen DOM
if (showStudentEwsPopup({ is_triggered: false }, 3000) !== null || bodyChildren.length !== 0) {
  throw new Error("Non-triggered EWS tidak boleh membuat popup");
}

// 2. Terpicu dengan XSS -> tampil di DOM sebagai modal tengah, ter-escape, TANPA timer auto-dismiss
const el1 = showStudentEwsPopup({
  is_triggered: true,
  severity: "kritis",
  title: "Peringatan <script>",
  reasons: ["Nilai < 75"],
});
if (!el1 || bodyChildren.length !== 1 || scheduled.length !== 0) {
  throw new Error("Modal EWS gagal tampil atau masih memakai timer auto-dismiss");
}
if (el1.innerHTML.includes("<script>") || !el1.innerHTML.includes("Mengerti")) {
  throw new Error("XSS tidak ter-escape atau tombol Mengerti tidak ada di modal EWS");
}

// 3. Pemanggilan kedua menggantikan modal pertama (anti-tumpuk)
showStudentEwsPopup({ is_triggered: true, severity: "perhatian", reasons: ["Alpa 3x"] });
if (bodyChildren.length !== 1) {
  throw new Error("Deduplikasi modal EWS gagal");
}

// 4. Modal hanya tertutup ketika dismissStudentEwsPopup (dipicu tombol Mengerti / Tutup / Escape) dipanggil
dismissStudentEwsPopup();
if (bodyChildren.length !== 0 || domMap.has("student-ews-popup")) {
  throw new Error("Modal EWS tidak menutup saat dismiss dipanggil");
}

// 5. dismissStudentEwsPopup aman saat dipanggil pada kondisi kosong
dismissStudentEwsPopup();
console.log("NODE_EWS_POPUP_OK");
""",
          encoding="utf-8",
      )
      proc = subprocess.run(["node", str(runner)], capture_output=True, text=True, check=False)
      self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
      self.assertIn("NODE_EWS_POPUP_OK", proc.stdout)


if __name__ == "__main__":
  unittest.main()
