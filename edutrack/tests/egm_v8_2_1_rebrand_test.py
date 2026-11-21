"""Pengujian regresi rebranding permukaan pengguna ke 'Bahasa Indonesia' (EGM v8.2.1)."""

from __future__ import annotations

import inspect
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient
import openpyxl

from edutrack.configs.app_config import AppConfig
from edutrack.main import seed_initial_data
from edutrack.services.report_service import _render_pdf
from edutrack.web.api import create_app


class RebrandBahasaIndonesiaTest(unittest.TestCase):
  """Verifikasi seluruh permukaan terlihat pengguna memakai 'Bahasa Indonesia' tanpa mengubah internal."""

  def setUp(self) -> None:
    self._tmpdir = tempfile.TemporaryDirectory()
    self._cfg = AppConfig(
        db_path=os.path.join(self._tmpdir.name, "rebrand_v8_2_1.db"),
        backup_dir=os.path.join(self._tmpdir.name, "backups"),
        cookie_secure=False,
    )
    self._app = create_app(self._cfg)
    seed_initial_data(self._app.state.container)
    self._client = TestClient(self._app)

  def tearDown(self) -> None:
    self._client.close()
    self._tmpdir.cleanup()

  def test_index_html_uses_bahasa_indonesia_and_no_edutrack(self) -> None:
    res = self._client.get("/")
    self.assertEqual(res.status_code, 200)
    html = res.text
    self.assertIn("<title>Bahasa Indonesia — Login &amp; Portal Pembelajaran</title>", html)
    self.assertEqual(html.count('<p class="auth-app-name">Bahasa Indonesia</p>'), 2)
    self.assertEqual(html.count("<strong>Bahasa Indonesia</strong>"), 2)
    self.assertIn('<h2 id="st-header-name">Bahasa Indonesia</h2>', html)
    self.assertNotIn("edutrack", html.lower())

  def test_manifest_json_rebranded_and_no_cache_header(self) -> None:
    res = self._client.get("/manifest.json")
    self.assertEqual(res.status_code, 200)
    self.assertIn("no-cache", res.headers.get("cache-control", ""))
    data = res.json()
    self.assertEqual(data["name"], "Bahasa Indonesia — Portal Pembelajaran")
    self.assertEqual(data["short_name"], "Bahasa Indonesia")
    self.assertIn("Bahasa Indonesia", data["description"])
    self.assertNotIn("edutrack", res.text.lower())

  def test_pwa_icon_svg_is_valid_bi_vector(self) -> None:
    res = self._client.get("/static/icon.svg")
    self.assertEqual(res.status_code, 200)
    root = ET.fromstring(res.text)
    self.assertEqual(root.attrib.get("viewBox"), "0 0 512 512")
    tags = [el.tag.split("}")[-1] for el in root.iter()]
    self.assertNotIn("text", tags)
    self.assertIn("path", tags)
    rects = [el for el in root.iter() if el.tag.endswith("rect") and el.attrib.get("x") == "298"]
    self.assertEqual(len(rects), 1)
    circles = [el for el in root.iter() if el.tag.endswith("circle") and el.attrib.get("cx") == "388"]
    self.assertEqual(len(circles), 1)

  def test_service_worker_cache_name_bumped(self) -> None:
    res = self._client.get("/sw.js")
    self.assertEqual(res.status_code, 200)
    self.assertNotIn('CACHE_NAME = "edutrack-shell-v8.2"', res.text)
    self.assertIn('CACHE_NAME = "edutrack-shell-v8.4.2"', res.text)

  def test_api_title_and_fallback_index_json(self) -> None:
    self.assertEqual(self._app.title, "Bahasa Indonesia — Sistem Administrasi Pembelajaran")
    orig_exists = Path.exists

    def _fake_exists(path_self: Path) -> bool:
      if path_self.name == "index.html":
        return False
      return orig_exists(path_self)

    with patch.object(Path, "exists", _fake_exists):
      res = self._client.get("/")
    self.assertEqual(res.status_code, 200)
    self.assertEqual(res.json(), {"status": "ok", "message": "Bahasa Indonesia API aktif."})

  def test_excel_template_and_pdf_default_badge(self) -> None:
    container = self._app.state.container
    with container.db.connection() as conn:
      teacher_row = conn.execute("SELECT id FROM users WHERE role IN ('teacher', 'admin') LIMIT 1").fetchone()
      asmt_row = conn.execute("SELECT id FROM assessments LIMIT 1").fetchone()
    self.assertIsNotNone(teacher_row)
    self.assertIsNotNone(asmt_row)
    teacher = container.user_repo.get_by_id(int(teacher_row["id"]))
    self.assertIsNotNone(teacher)

    _, xlsx_bytes = container.grade_service.generate_grade_import_template(teacher, int(asmt_row["id"]))
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes))
    ws = wb.active
    self.assertEqual(ws["A1"].value, "TEMPLATE IMPOR NILAI PESERTA DIDIK — BAHASA INDONESIA")

    sig = inspect.signature(_render_pdf)
    self.assertEqual(sig.parameters["badge_text"].default, "BAHASA INDONESIA • LAPORAN")
    pdf_bytes = _render_pdf("Laporan Uji", "Subjudul", ["Kolom"], [["Nilai"]])
    self.assertTrue(pdf_bytes.startswith(b"%PDF"))

  def test_internal_config_invariants_preserved(self) -> None:
    default_cfg = AppConfig()
    self.assertEqual(default_cfg.cookie_name, "edutrack_session")
    self.assertEqual(default_cfg.csrf_cookie_name, "edutrack_csrf")
    self.assertEqual(default_cfg.db_path, "edutrack_data.db")


if __name__ == "__main__":
  unittest.main()
