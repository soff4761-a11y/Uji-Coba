"""Unit test untuk dukungan PostgreSQL (Vercel/Neon/Supabase) & AppConfig.from_env()."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import unittest
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from edutrack.configs.app_config import AppConfig
from edutrack.domain.errors import ValidationError
from edutrack.repositories.database import (
    CompatConnection,
    Database,
    DatabaseIntegrityError,
    translate_sql_to_postgres,
)


class PostgresAdapterAndConfigTest(unittest.TestCase):
  """Menguji translasi SQL PostgreSQL, CompatConnection, dan konfigurasi Vercel."""

  # --- Happy Path ---

  def test_translate_sql_placeholders_and_insert_returning(self) -> None:
    q_select = "SELECT * FROM users WHERE username = ? AND status = 'active?'"
    self.assertEqual(
        translate_sql_to_postgres(q_select),
        "SELECT * FROM users WHERE username = %s AND status = 'active?'",
    )

    q_insert = "INSERT INTO users (username, full_name) VALUES (?, ?)"
    self.assertEqual(
        translate_sql_to_postgres(q_insert),
        "INSERT INTO users (username, full_name) VALUES (%s, %s) RETURNING id",
    )

  def test_app_config_from_env_vercel_postgres(self) -> None:
    cfg = AppConfig.from_env({
        "VERCEL": "1",
        "DATABASE_URL": "postgresql://user:pass@ep-demo.neon.tech/neondb?sslmode=require",
        "EDUTRACK_SEED_DEMO": "false",
    })
    self.assertTrue(cfg.is_postgres)
    self.assertTrue(cfg.cookie_secure)
    self.assertFalse(cfg.seed_demo_data)

  def test_compat_connection_postgres_insert_lastrowid_with_mock(self) -> None:
    raw_cursor = MagicMock()
    raw_cursor.fetchone.return_value = {"id": 42}
    raw_conn = MagicMock()
    raw_conn.cursor.return_value = raw_cursor

    compat = CompatConnection(raw_conn, is_postgres=True)
    cur = compat.execute("INSERT INTO users (username) VALUES (?)", ("guru_pg",))
    self.assertEqual(cur.lastrowid, 42)
    raw_cursor.execute.assert_called_once_with(
        "INSERT INTO users (username) VALUES (%s) RETURNING id", ("guru_pg",)
    )

  def test_database_postgres_initialize_and_backup_guard_with_mock(self) -> None:
    raw_cursor = MagicMock()
    raw_conn = MagicMock()
    raw_conn.cursor.return_value = raw_cursor

    db = Database(
        database_url="postgresql://user:pass@host/db",
        pg_connector=lambda _url: raw_conn,
    )
    self.assertTrue(db.is_postgres)
    self.assertGreaterEqual(raw_cursor.execute.call_count, 15)
    self.assertEqual(db.list_backups(), [])

    with self.assertRaises(ValidationError):
      db.create_backup("manual")
    with self.assertRaises(ValidationError):
      db.restore_backup("any.db")

  # --- Edge / Empty Cases ---

  def test_app_config_from_env_defaults_local_sqlite(self) -> None:
    cfg = AppConfig.from_env({})
    self.assertFalse(cfg.is_postgres)
    self.assertFalse(cfg.cookie_secure)
    self.assertEqual(cfg.db_path, "edutrack_data.db")
    self.assertTrue(cfg.seed_demo_data)

  def test_translate_sql_preserves_existing_returning(self) -> None:
    q = "INSERT INTO users (username) VALUES (?) RETURNING id"
    self.assertEqual(
        translate_sql_to_postgres(q),
        "INSERT INTO users (username) VALUES (%s) RETURNING id",
    )

  # --- Error / Invalid Cases ---

  def test_invalid_database_url_raises_value_error(self) -> None:
    with self.assertRaises(ValueError):
      AppConfig(database_url="mysql://user:pass@host/db")

  def test_postgres_unique_violation_maps_to_database_integrity_error(self) -> None:
    class UniqueViolation(Exception):
      pass

    raw_cursor = MagicMock()
    raw_cursor.execute.side_effect = UniqueViolation("duplicate key")
    raw_conn = MagicMock()
    raw_conn.cursor.return_value = raw_cursor

    compat = CompatConnection(raw_conn, is_postgres=True)
    with self.assertRaises(DatabaseIntegrityError):
      compat.execute("INSERT INTO users (username) VALUES (?)", ("dup",))

  def test_vercel_entrypoint_serves_home_and_auth(self) -> None:
    import os
    import tempfile
    from unittest.mock import patch

    with tempfile.TemporaryDirectory() as tmpdir:
      with patch.dict(os.environ, {"EDUTRACK_DB_PATH": os.path.join(tmpdir, "vercel_test.db")}):
        from api.index import _build_vercel_app  # pylint: disable=import-outside-toplevel

        vercel_app = _build_vercel_app()
        client = TestClient(vercel_app)
        res_home = client.get("/")
        self.assertEqual(res_home.status_code, 200)
        self.assertIn("Bahasa Indonesia", res_home.text)
        self.assertNotIn("EduTrack", res_home.text)
        res_health = client.get("/api/health")
        self.assertEqual(res_health.status_code, 200)
        self.assertTrue(res_health.json()["database_connected"])

  def test_frontend_app_js_has_valid_syntax(self) -> None:
    """Memastikan seluruh modul ES frontend valid secara sintaks."""
    node_bin = shutil.which("node")
    if not node_bin:
      self.skipTest("node tidak tersedia di lingkungan pengujian.")
    static_root = Path(__file__).resolve().parent.parent / "web" / "static"
    module_files = [static_root / "app.js"] + sorted((static_root / "js").glob("*.js"))
    for mf in module_files:
      proc = subprocess.run(
          [node_bin, "--input-type=module", "--check"],
          input=mf.read_text(encoding="utf-8"),
          capture_output=True,
          text=True,
          check=False,
      )
      self.assertEqual(proc.returncode, 0, msg=f"Syntax error di {mf.name}: {proc.stderr}")


  def test_postgres_v3_percent_placeholder_guard_and_existing_v6_migration(self) -> None:
    """Memastikan blok DO $$ (%role%, %I) tidak mengirim params=() ke psycopg v3 & aman di DB Supabase v1-v6."""
    import re as _re
    executed_sqls: list[str] = []

    class StrictPsycopgV3Cursor:
      def __init__(self) -> None:
        self._rows: list[dict] = []
        self.rowcount = 0

      def execute(self, sql: str, params=None) -> None:
        # Mensimulasikan parser PyFormatBinding psycopg v3:
        # jika params bukan None (termasuk tuple kosong ()), karakter % selain %s/%b/%t/%% memicu ProgrammingError!
        if params is not None:
          bad = _re.findall(r"%(?![sbt%])", sql)
          if bad:
            raise RuntimeError(f"psycopg v3 ProgrammingError: invalid placeholder in SQL with params={params!r}")
        executed_sqls.append(sql)
        if "FROM schema_migrations" in sql:
          self._rows = []
        elif "FROM information_schema.columns" in sql:
          tbl = params[0] if params else ""
          if tbl == "sessions":
            self._rows = [
                {"column_name": "id", "data_type": "integer"},
                {"column_name": "created_at", "data_type": "text"},
            ]
          elif tbl in ("users", "academic_periods", "classes", "learning_materials", "class_announcements", "correction_requests"):
            self._rows = [
                {"column_name": "must_change_password", "data_type": "integer"},
                {"column_name": "is_active", "data_type": "integer"},
                {"column_name": "is_archived", "data_type": "integer"},
                {"column_name": "allow_student_report_download", "data_type": "integer"},
                {"column_name": "is_pinned", "data_type": "integer"},
                {"column_name": "hidden_by_student", "data_type": "integer"},
            ]
          else:
            self._rows = []
        else:
          self._rows = []

      def fetchall(self):
        return list(self._rows)

      def fetchone(self):
        return self._rows[0] if self._rows else None

      def close(self) -> None:
        pass

    class StrictPgConn:
      def cursor(self):
        return StrictPsycopgV3Cursor()
      def commit(self) -> None:
        pass
      def rollback(self) -> None:
        pass
      def close(self) -> None:
        pass

    db = Database(
        database_url="postgresql://postgres.demo:secret@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres",
        pg_connector=lambda _url: StrictPgConn(),
    )
    self.assertTrue(db.is_postgres)
    # Pastikan migrasi #1 menambah last_activity_at bertipe TEXT agar cocok dengan created_at TEXT eksisting
    self.assertTrue(any("ADD COLUMN IF NOT EXISTS last_activity_at TEXT" in s for s in executed_sqls))
    # Pastikan blok DO $$ pada migrasi #4 dan #5 berhasil dieksekusi tanpa error % placeholder
    self.assertTrue(any("ILIKE '%role%'" in s for s in executed_sqls))
    self.assertTrue(any("TYPE BOOLEAN USING" in s for s in executed_sqls))

  def test_no_raw_integer_literals_for_boolean_columns_in_repositories(self) -> None:
    """Memastikan tidak ada perbandingan/insert literal 0/1 langsung pada kolom boolean di repo."""
    import re as _re
    repo_dir = Path(__file__).resolve().parent.parent / "repositories"
    bool_cols = ("is_archived", "is_active", "must_change_password", "allow_student_report_download", "is_pinned", "hidden_by_student")
    for rp in sorted(repo_dir.glob("*_repo.py")):
      txt = rp.read_text(encoding="utf-8")
      for col in bool_cols:
        self.assertIsNone(
            _re.search(rf"\b{col}\s*=\s*[01]\b", txt),
            f"Ditemukan literal integer pada kolom boolean {col} di {rp.name}",
        )

if __name__ == "__main__":
  unittest.main()
