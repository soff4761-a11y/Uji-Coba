"""Manajemen koneksi basis data ganda (SQLite lokal & PostgreSQL cloud untuk Vercel).

Menjamin:
1. Integritas referensial penuh (PRAGMA foreign_keys = ON di SQLite, FK native di PostgreSQL).
2. Transparansi query lintas-mesin melalui lapisan kompatibilitas placeholder (`?` -> `%s`)
   dan `RETURNING id` otomatis pada pernyataan INSERT di PostgreSQL.
3. Normalisasi kesalahan integritas unik/FK menjadi `DatabaseIntegrityError`.
"""

from __future__ import annotations

import atexit
from contextlib import contextmanager
import re
from contextvars import ContextVar
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Callable, Iterator, List, Optional, Sequence

from edutrack.domain.errors import NotFoundError, ValidationError


class DatabaseIntegrityError(Exception):
  """Kesalahan integritas basis data (UNIQUE / FOREIGN KEY) lintas-backend."""


SQLITE_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  full_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('admin', 'teacher', 'student')),
  status TEXT NOT NULL DEFAULT 'active'
    CHECK(status IN ('active', 'pending_activation', 'deactivated')),
  must_change_password INTEGER NOT NULL DEFAULT 0 CHECK(must_change_password IN (0, 1)),
  email TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  revoked_at TEXT
);

CREATE TABLE IF NOT EXISTS recovery_tokens (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE,
  expires_at TEXT NOT NULL,
  used_at TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS academic_periods (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  academic_year TEXT NOT NULL,
  semester TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 0 CHECK(is_active IN (0, 1)),
  is_archived INTEGER NOT NULL DEFAULT 0 CHECK(is_archived IN (0, 1)),
  created_at TEXT NOT NULL,
  UNIQUE(teacher_id, academic_year, semester)
);

CREATE TABLE IF NOT EXISTS classes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  period_id INTEGER NOT NULL REFERENCES academic_periods(id) ON DELETE RESTRICT,
  name TEXT NOT NULL,
  education_level TEXT NOT NULL,
  academic_year TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  calculation_mode TEXT NOT NULL DEFAULT 'weighted'
    CHECK(calculation_mode IN ('weighted', 'unweighted')),
  mastery_threshold REAL NOT NULL DEFAULT 75.0,
  allow_student_report_download INTEGER NOT NULL DEFAULT 1
    CHECK(allow_student_report_download IN (0, 1)),
  is_archived INTEGER NOT NULL DEFAULT 0 CHECK(is_archived IN (0, 1)),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS students (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
  teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  current_class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE RESTRICT,
  student_code TEXT NOT NULL,
  full_name TEXT NOT NULL,
  notes TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(teacher_id, student_code)
);

CREATE TABLE IF NOT EXISTS student_enrollments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  enrolled_at TEXT NOT NULL,
  left_at TEXT
);

CREATE TABLE IF NOT EXISTS learning_materials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  period_id INTEGER NOT NULL REFERENCES academic_periods(id) ON DELETE RESTRICT,
  teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  sort_order INTEGER NOT NULL DEFAULT 1,
  is_archived INTEGER NOT NULL DEFAULT 0 CHECK(is_archived IN (0, 1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assessments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  period_id INTEGER NOT NULL REFERENCES academic_periods(id) ON DELETE RESTRICT,
  title TEXT NOT NULL,
  category TEXT NOT NULL,
  assessment_date TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  max_score REAL NOT NULL DEFAULT 100.0 CHECK(max_score > 0),
  weight REAL NOT NULL DEFAULT 1.0 CHECK(weight >= 0),
  status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'published')),
  is_graded INTEGER NOT NULL DEFAULT 1 CHECK(is_graded IN (0, 1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS grades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
  student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  score REAL CHECK(score IS NULL OR score >= 0),
  feedback TEXT NOT NULL DEFAULT '',
  updated_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  updated_at TEXT NOT NULL,
  revealed_at TEXT DEFAULT NULL,
  UNIQUE(assessment_id, student_id)
);

CREATE TABLE IF NOT EXISTS grade_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
  student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  old_score REAL,
  new_score REAL,
  old_feedback TEXT,
  new_feedback TEXT,
  changed_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  reason TEXT NOT NULL DEFAULT '',
  changed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS attendance_sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  period_id INTEGER NOT NULL REFERENCES academic_periods(id) ON DELETE RESTRICT,
  session_date TEXT NOT NULL,
  meeting_number INTEGER NOT NULL CHECK(meeting_number >= 1),
  topic TEXT NOT NULL DEFAULT '',
  created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  created_at TEXT NOT NULL,
  UNIQUE(class_id, session_date, meeting_number)
);

CREATE TABLE IF NOT EXISTS attendance_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES attendance_sessions(id) ON DELETE CASCADE,
  student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK(status IN ('hadir', 'sakit', 'izin', 'alpa')),
  note TEXT NOT NULL DEFAULT '',
  updated_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  updated_at TEXT NOT NULL,
  UNIQUE(session_id, student_id)
);

CREATE TABLE IF NOT EXISTS attendance_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES attendance_sessions(id) ON DELETE CASCADE,
  student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  old_status TEXT,
  new_status TEXT NOT NULL,
  old_note TEXT,
  new_note TEXT NOT NULL DEFAULT '',
  changed_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  reason TEXT NOT NULL DEFAULT '',
  changed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS correction_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
  teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  target_type TEXT NOT NULL CHECK(target_type IN ('grade', 'attendance')),
  target_id INTEGER NOT NULL,
  message TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK(status IN ('pending', 'reviewed', 'resolved', 'rejected')),
  teacher_response TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
  action TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  details TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_classes_teacher ON classes(teacher_id, period_id);
CREATE INDEX IF NOT EXISTS idx_students_class ON students(current_class_id);
CREATE INDEX IF NOT EXISTS idx_students_teacher ON students(teacher_id);
CREATE INDEX IF NOT EXISTS idx_assessments_class ON assessments(class_id, status);
CREATE INDEX IF NOT EXISTS idx_grades_student ON grades(student_id);
CREATE INDEX IF NOT EXISTS idx_att_sessions_class ON attendance_sessions(class_id, session_date);
CREATE INDEX IF NOT EXISTS idx_att_records_student ON attendance_records(student_id);
CREATE TABLE IF NOT EXISTS class_announcements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
  teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'Umum',
  content TEXT NOT NULL,
  is_pinned INTEGER NOT NULL DEFAULT 0 CHECK(is_pinned IN (0, 1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_rate_limits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rate_key TEXT NOT NULL,
  attempted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_logs(actor_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_announcements_class ON class_announcements(class_id, is_pinned, id);
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_login_rate_key_time ON login_rate_limits(rate_key, attempted_at);
CREATE INDEX IF NOT EXISTS idx_enrollments_student_class ON student_enrollments(student_id, class_id);
CREATE INDEX IF NOT EXISTS idx_materials_class_arch_order ON learning_materials(class_id, is_archived, sort_order);
CREATE INDEX IF NOT EXISTS idx_grade_history_lookup ON grade_history(assessment_id, student_id, changed_at);
CREATE INDEX IF NOT EXISTS idx_att_history_lookup ON attendance_history(session_id, student_id, changed_at);
"""

# Skema PostgreSQL (kompatibel Neon, Supabase, Vercel Postgres)
POSTGRES_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS users (
      id SERIAL PRIMARY KEY,
      username TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL,
      full_name TEXT NOT NULL,
      role TEXT NOT NULL CHECK(role IN ('admin', 'teacher', 'student')),
      status TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active', 'pending_activation', 'deactivated')),
      must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
      email TEXT,
      created_at TIMESTAMPTZ NOT NULL,
      updated_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
      id SERIAL PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      token_hash TEXT NOT NULL UNIQUE,
      expires_at TIMESTAMPTZ NOT NULL,
      created_at TIMESTAMPTZ NOT NULL,
      revoked_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recovery_tokens (
      id SERIAL PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      token_hash TEXT NOT NULL UNIQUE,
      expires_at TIMESTAMPTZ NOT NULL,
      used_at TIMESTAMPTZ,
      created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS academic_periods (
      id SERIAL PRIMARY KEY,
      teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      name TEXT NOT NULL,
      academic_year TEXT NOT NULL,
      semester TEXT NOT NULL,
      is_active BOOLEAN NOT NULL DEFAULT FALSE,
      is_archived BOOLEAN NOT NULL DEFAULT FALSE,
      created_at TIMESTAMPTZ NOT NULL,
      UNIQUE(teacher_id, academic_year, semester)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS classes (
      id SERIAL PRIMARY KEY,
      teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      period_id INTEGER NOT NULL REFERENCES academic_periods(id) ON DELETE RESTRICT,
      name TEXT NOT NULL,
      education_level TEXT NOT NULL,
      academic_year TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      calculation_mode TEXT NOT NULL DEFAULT 'weighted'
        CHECK(calculation_mode IN ('weighted', 'unweighted')),
      mastery_threshold DOUBLE PRECISION NOT NULL DEFAULT 75.0,
      allow_student_report_download BOOLEAN NOT NULL DEFAULT TRUE,
      is_archived BOOLEAN NOT NULL DEFAULT FALSE,
      created_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS students (
      id SERIAL PRIMARY KEY,
      user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
      teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      current_class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE RESTRICT,
      student_code TEXT NOT NULL,
      full_name TEXT NOT NULL,
      notes TEXT NOT NULL DEFAULT '',
      created_at TIMESTAMPTZ NOT NULL,
      UNIQUE(teacher_id, student_code)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS student_enrollments (
      id SERIAL PRIMARY KEY,
      student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
      class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
      enrolled_at TIMESTAMPTZ NOT NULL,
      left_at TIMESTAMPTZ
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS learning_materials (
      id SERIAL PRIMARY KEY,
      class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
      period_id INTEGER NOT NULL REFERENCES academic_periods(id) ON DELETE RESTRICT,
      teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      title TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      sort_order INTEGER NOT NULL DEFAULT 1,
      is_archived BOOLEAN NOT NULL DEFAULT FALSE,
      created_at TIMESTAMPTZ NOT NULL,
      updated_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS assessments (
      id SERIAL PRIMARY KEY,
      class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
      period_id INTEGER NOT NULL REFERENCES academic_periods(id) ON DELETE RESTRICT,
      title TEXT NOT NULL,
      category TEXT NOT NULL,
      assessment_date TEXT NOT NULL,
      description TEXT NOT NULL DEFAULT '',
      max_score DOUBLE PRECISION NOT NULL DEFAULT 100.0 CHECK(max_score > 0),
      weight DOUBLE PRECISION NOT NULL DEFAULT 1.0 CHECK(weight >= 0),
      status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'published')),
      is_graded BOOLEAN NOT NULL DEFAULT TRUE,
      created_at TIMESTAMPTZ NOT NULL,
      updated_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS grades (
      id SERIAL PRIMARY KEY,
      assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
      student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
      score DOUBLE PRECISION CHECK(score IS NULL OR score >= 0),
      feedback TEXT NOT NULL DEFAULT '',
      updated_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
      updated_at TIMESTAMPTZ NOT NULL,
      revealed_at TIMESTAMPTZ DEFAULT NULL,
      UNIQUE(assessment_id, student_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS grade_history (
      id SERIAL PRIMARY KEY,
      assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
      student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
      old_score DOUBLE PRECISION,
      new_score DOUBLE PRECISION,
      old_feedback TEXT,
      new_feedback TEXT,
      changed_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
      reason TEXT NOT NULL DEFAULT '',
      changed_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attendance_sessions (
      id SERIAL PRIMARY KEY,
      class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
      period_id INTEGER NOT NULL REFERENCES academic_periods(id) ON DELETE RESTRICT,
      session_date TEXT NOT NULL,
      meeting_number INTEGER NOT NULL CHECK(meeting_number >= 1),
      topic TEXT NOT NULL DEFAULT '',
      created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
      created_at TIMESTAMPTZ NOT NULL,
      UNIQUE(class_id, session_date, meeting_number)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attendance_records (
      id SERIAL PRIMARY KEY,
      session_id INTEGER NOT NULL REFERENCES attendance_sessions(id) ON DELETE CASCADE,
      student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
      status TEXT NOT NULL CHECK(status IN ('hadir', 'sakit', 'izin', 'alpa')),
      note TEXT NOT NULL DEFAULT '',
      updated_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
      updated_at TIMESTAMPTZ NOT NULL,
      UNIQUE(session_id, student_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS attendance_history (
      id SERIAL PRIMARY KEY,
      session_id INTEGER NOT NULL REFERENCES attendance_sessions(id) ON DELETE CASCADE,
      student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
      old_status TEXT,
      new_status TEXT NOT NULL,
      old_note TEXT,
      new_note TEXT NOT NULL DEFAULT '',
      changed_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
      reason TEXT NOT NULL DEFAULT '',
      changed_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS correction_requests (
      id SERIAL PRIMARY KEY,
      student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
      teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      target_type TEXT NOT NULL CHECK(target_type IN ('grade', 'attendance')),
      target_id INTEGER NOT NULL,
      message TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'reviewed', 'resolved', 'rejected')),
      teacher_response TEXT NOT NULL DEFAULT '',
      created_at TIMESTAMPTZ NOT NULL,
      updated_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
      id SERIAL PRIMARY KEY,
      actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
      action TEXT NOT NULL,
      entity_type TEXT NOT NULL,
      entity_id TEXT NOT NULL,
      details TEXT NOT NULL DEFAULT '',
      created_at TIMESTAMPTZ NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token_hash)",
    "CREATE INDEX IF NOT EXISTS idx_classes_teacher ON classes(teacher_id, period_id)",
    "CREATE INDEX IF NOT EXISTS idx_students_class ON students(current_class_id)",
    "CREATE INDEX IF NOT EXISTS idx_students_teacher ON students(teacher_id)",
    "CREATE INDEX IF NOT EXISTS idx_assessments_class ON assessments(class_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_grades_student ON grades(student_id)",
    "CREATE INDEX IF NOT EXISTS idx_att_sessions_class ON attendance_sessions(class_id, session_date)",
    "CREATE INDEX IF NOT EXISTS idx_att_records_student ON attendance_records(student_id)",
    """
    CREATE TABLE IF NOT EXISTS class_announcements (
      id SERIAL PRIMARY KEY,
      class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
      teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      title TEXT NOT NULL,
      category TEXT NOT NULL DEFAULT 'Umum',
      content TEXT NOT NULL,
      is_pinned BOOLEAN NOT NULL DEFAULT FALSE,
      created_at TIMESTAMPTZ NOT NULL,
      updated_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS login_rate_limits (
      id SERIAL PRIMARY KEY,
      rate_key TEXT NOT NULL,
      attempted_at TIMESTAMPTZ NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_logs(actor_user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_announcements_class ON class_announcements(class_id, is_pinned, id)",
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
      version INTEGER PRIMARY KEY,
      name TEXT NOT NULL,
      applied_at TIMESTAMPTZ NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_login_rate_key_time ON login_rate_limits(rate_key, attempted_at)",
    "CREATE INDEX IF NOT EXISTS idx_enrollments_student_class ON student_enrollments(student_id, class_id)",
    "CREATE INDEX IF NOT EXISTS idx_materials_class_arch_order ON learning_materials(class_id, is_archived, sort_order)",
    "CREATE INDEX IF NOT EXISTS idx_grade_history_lookup ON grade_history(assessment_id, student_id, changed_at)",
    "CREATE INDEX IF NOT EXISTS idx_att_history_lookup ON attendance_history(session_id, student_id, changed_at)",
)


_TABLES_WITHOUT_ID = frozenset({"SCHEMA_MIGRATIONS"})


def utc_now_iso() -> str:
  """Mengembalikan cap waktu UTC dalam format ISO-8601."""
  return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def to_iso_str(val: Any) -> Optional[str]:
  """Menormalkan objek datetime (TIMESTAMPTZ PostgreSQL) atau string ke ISO-8601 UTC."""
  if val is None:
    return None
  if isinstance(val, datetime):
    dt = val if val.tzinfo is not None else val.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()
  return str(val)


def parse_utc_dt(val: Any) -> datetime:
  """Mengonversi datetime atau string ISO-8601 (dengan 'T' maupun spasi) ke datetime UTC."""
  if isinstance(val, datetime):
    return val.astimezone(timezone.utc) if val.tzinfo else val.replace(tzinfo=timezone.utc)
  s = str(val or "").strip()
  if s.endswith("Z"):
    s = s[:-1] + "+00:00"
  dt = datetime.fromisoformat(s)
  return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _normalize_pg_row(row: Any) -> Any:
  if row is None or not isinstance(row, dict):
    return row
  return {k: (to_iso_str(v) if isinstance(v, datetime) else v) for k, v in row.items()}


def translate_sql_to_postgres(sql: str) -> str:
  """Mengubah placeholder `?` menjadi `%s` di luar literal string tunggal.

  Menambahkan `RETURNING id` secara selektif hanya untuk pernyataan `INSERT INTO`
  (bukan CTE `WITH`, bukan `ON CONFLICT ... DO NOTHING`, bukan tabel tanpa kolom `id`,
  dan belum memiliki klausa `RETURNING`).
  """
  out: List[str] = []
  in_single_quote = False
  i = 0
  n = len(sql)
  while i < n:
    ch = sql[i]
    if ch == "'":
      if in_single_quote and i + 1 < n and sql[i + 1] == "'":
        out.append("''")
        i += 2
        continue
      in_single_quote = not in_single_quote
      out.append(ch)
    elif ch == "?" and not in_single_quote:
      out.append("%s")
    else:
      out.append(ch)
    i += 1

  translated = "".join(out).strip()
  norm = re.sub(r"\s+", " ", translated).strip().upper()
  if (
      norm.startswith("INSERT INTO ")
      and not re.search(r"\bRETURNING\b", norm)
      and not (re.search(r"\bON\s+CONFLICT\b", norm) and re.search(r"\bDO\s+NOTHING\b", norm))
  ):
    m = re.match(r'^INSERT\s+INTO\s+(?:"?[A-Z0-9_]+"?\.)?"?([A-Z0-9_]+)"?', norm)
    target_table = m.group(1) if m else ""
    if target_table not in _TABLES_WITHOUT_ID:
      translated = translated.rstrip(";") + " RETURNING id"
  return translated


def _is_integrity_exception(exc: Exception) -> bool:
  """Mendeteksi exception pelanggaran integritas (SQLite maupun PostgreSQL)."""
  if isinstance(exc, sqlite3.IntegrityError):
    return True
  name = type(exc).__name__
  return name in (
      "IntegrityError",
      "UniqueViolation",
      "ForeignKeyViolation",
      "CheckViolation",
      "NotNullViolation",
  )


class CompatCursor:
  """Pembungkus kursor seragam untuk SQLite dan PostgreSQL (normalisasi TIMESTAMPTZ)."""

  def __init__(
      self, raw_cursor: Any, lastrowid: Optional[int] = None, is_postgres: bool = False
  ) -> None:
    self._cur = raw_cursor
    self._is_postgres = is_postgres
    self.lastrowid = lastrowid if lastrowid is not None else getattr(raw_cursor, "lastrowid", None)
    self.rowcount = getattr(raw_cursor, "rowcount", -1)

  def fetchone(self) -> Any:
    row = self._cur.fetchone()
    return _normalize_pg_row(row) if self._is_postgres else row

  def fetchall(self) -> List[Any]:
    rows = list(self._cur.fetchall())
    return [_normalize_pg_row(r) for r in rows] if self._is_postgres else rows


class CompatConnection:
  """Pembungkus koneksi seragam yang menormalkan placeholder dan IntegrityError."""

  def __init__(self, raw_conn: Any, is_postgres: bool) -> None:
    self._conn = raw_conn
    self._is_postgres = is_postgres

  def execute(self, sql: str, params: Sequence[Any] = ()) -> CompatCursor:
    try:
      if not self._is_postgres:
        cur = self._conn.execute(sql, params)
        return CompatCursor(cur, is_postgres=False)

      pg_sql = translate_sql_to_postgres(sql)
      cur = self._conn.cursor()
      try:
        if params:
          cur.execute(pg_sql, tuple(params))
        else:
          cur.execute(pg_sql)
      except Exception:
        if hasattr(cur, "close"):
          cur.close()
        raise
      lastrowid: Optional[int] = None
      if re.search(r"\bRETURNING\s+ID\b", pg_sql, re.IGNORECASE):
        row = cur.fetchone()
        if row is not None:
          lastrowid = int(row["id"] if isinstance(row, dict) else row[0])
      return CompatCursor(cur, lastrowid=lastrowid, is_postgres=True)
    except Exception as exc:
      if _is_integrity_exception(exc):
        raise DatabaseIntegrityError(str(exc)) from exc
      raise

  def executescript(self, script: str) -> None:
    if self._is_postgres:
      raise ValidationError("executescript hanya digunakan pada mode SQLite.")
    self._conn.executescript(script)


def _default_postgres_connector(database_url: str) -> Any:
  """Membuka koneksi PostgreSQL via psycopg (v3) atau psycopg2 (aman untuk PgBouncer/Supabase)."""
  from edutrack.configs.app_config import sanitize_postgres_url  # pylint: disable=import-outside-toplevel

  normalized = sanitize_postgres_url(database_url)
  try:
    import psycopg  # type: ignore
    from psycopg.rows import dict_row  # type: ignore

    # prepare_threshold=None wajib agar transaksi melalui PgBouncer/Supabase Pooler tidak gagal.
    return psycopg.connect(normalized, row_factory=dict_row, prepare_threshold=None, connect_timeout=10)
  except ImportError:
    pass

  try:
    import psycopg2  # type: ignore
    from psycopg2.extras import RealDictCursor  # type: ignore

    return psycopg2.connect(normalized, cursor_factory=RealDictCursor, connect_timeout=10)
  except ImportError as exc:
    raise RuntimeError(
        "Driver PostgreSQL tidak terpasang. Instal 'psycopg[binary]' dari requirements.txt."
    ) from exc


class Database:
  """Adaptor koneksi basis data (SQLite lokal atau PostgreSQL cloud)."""

  def __init__(
      self,
      db_path: str = "edutrack_data.db",
      backup_dir: str = "edutrack_backups",
      database_url: Optional[str] = None,
      pg_connector: Optional[Callable[[str], Any]] = None,
  ) -> None:
    self.db_path = db_path
    self.backup_dir = backup_dir
    self.database_url = database_url.strip() if database_url else None
    self._custom_pg_connector = pg_connector is not None
    self._pg_connector = pg_connector or _default_postgres_connector
    self.is_postgres = bool(
        self.database_url
        and (
            self.database_url.lower().startswith("postgres://")
            or self.database_url.lower().startswith("postgresql://")
        )
    )
    self._pg_pool: Optional[Any] = None
    if self.is_postgres and not self._custom_pg_connector and self.database_url:
      self._pg_pool = self._try_create_pg_pool(self.database_url)
    self._memory_conn: Optional[sqlite3.Connection] = None

    if not self.is_postgres and db_path != ":memory:":
      parent = Path(db_path).parent
      if str(parent) not in ("", "."):
        parent.mkdir(parents=True, exist_ok=True)
    self.initialize()

  def _create_sqlite_connection(self) -> sqlite3.Connection:
    conn = sqlite3.connect(self.db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

  _pg_request_holder: ContextVar[Optional[Dict[str, Any]]] = ContextVar("edutrack_pg_req_holder", default=None)

  def bool_val(self, val: Any) -> Any:
    """Mengembalikan tipe boolean portabel (bool di PostgreSQL, 0/1 di SQLite)."""
    return bool(val) if self.is_postgres else (1 if val else 0)

  @staticmethod
  def _try_create_pg_pool(database_url: str) -> Optional[Any]:
    """Membuat ConnectionPool psycopg_pool untuk server persisten (non-serverless).

    Pada Vercel Serverless (`VERCEL=1`), container dibekukan antar-invocation sehingga
    background thread ConnectionPool rentan stale terhadap PgBouncer; gunakan koneksi
    per-request via `request_scope()` + Transaction Pooler Supabase.
    """
    if os.environ.get("VERCEL") == "1":
      return None
    try:
      from psycopg.rows import dict_row  # type: ignore
      from psycopg_pool import ConnectionPool  # type: ignore
      from edutrack.configs.app_config import sanitize_postgres_url  # pylint: disable=import-outside-toplevel
    except ImportError:
      return None
    try:
      normalized = sanitize_postgres_url(database_url)
      pool = ConnectionPool(
          conninfo=normalized,
          min_size=0,
          max_size=4,
          max_idle=60,
          max_lifetime=300,
          timeout=10,
          check=ConnectionPool.check_connection,
          kwargs={
              "row_factory": dict_row,
              "prepare_threshold": None,
              "connect_timeout": 10,
          },
          open=True,
      )
      atexit.register(pool.close)
      return pool
    except Exception:  # pylint: disable=broad-except
      return None

  def _acquire_pg_conn(self) -> Any:
    if self._pg_pool is not None:
      return self._pg_pool.getconn()
    assert self.database_url is not None
    return self._pg_connector(self.database_url)

  def _release_pg_conn(self, raw_conn: Any) -> None:
    if self._pg_pool is not None:
      self._pg_pool.putconn(raw_conn)
    else:
      raw_conn.close()

  @contextmanager
  def request_scope(self) -> Iterator[None]:
    """Menyiapkan cakupan koneksi PostgreSQL lazy dengan dukungan ConnectionPool."""
    if not self.is_postgres or self._pg_request_holder.get() is not None:
      yield
      return
    holder: Dict[str, Any] = {"conn": None}
    token = self._pg_request_holder.set(holder)
    try:
      yield
      if holder["conn"] is not None:
        try:
          holder["conn"].commit()
        except Exception:
          pass
    except Exception:
      if holder["conn"] is not None:
        try:
          holder["conn"].rollback()
        except Exception:
          pass
      raise
    finally:
      self._pg_request_holder.reset(token)
      if holder["conn"] is not None:
        try:
          self._release_pg_conn(holder["conn"])
        except Exception:
          pass

  @contextmanager
  def connection(self) -> Iterator[CompatConnection]:
    """Menyediakan koneksi transaksional dengan commit/rollback otomatis."""
    if self.is_postgres:
      holder = self._pg_request_holder.get()
      if holder is not None:
        if holder["conn"] is None:
          holder["conn"] = self._acquire_pg_conn()
        scoped = holder["conn"]
        try:
          yield CompatConnection(scoped, is_postgres=True)
          scoped.commit()
        except Exception:
          scoped.rollback()
          raise
        return
      raw_conn = self._acquire_pg_conn()
      try:
        yield CompatConnection(raw_conn, is_postgres=True)
        raw_conn.commit()
      except Exception:
        raw_conn.rollback()
        raise
      finally:
        self._release_pg_conn(raw_conn)
      return

    if self.db_path == ":memory:":
      if self._memory_conn is None:
        self._memory_conn = self._create_sqlite_connection()
      raw_conn = self._memory_conn
      try:
        yield CompatConnection(raw_conn, is_postgres=False)
        raw_conn.commit()
      except Exception:
        raw_conn.rollback()
        raise
      return

    raw_conn = self._create_sqlite_connection()
    try:
      yield CompatConnection(raw_conn, is_postgres=False)
      raw_conn.commit()
    except Exception:
      raw_conn.rollback()
      raise
    finally:
      raw_conn.close()

  def initialize(self) -> None:
    """Membuat skema dasar dan menjalankan migrasi berversi (schema_migrations) secara idempoten."""
    with self.connection() as conn:
      if self.is_postgres:
        for stmt in POSTGRES_SCHEMA_STATEMENTS:
          conn.execute(stmt)
      else:
        conn.executescript(SQLITE_SCHEMA_SQL)
    self._run_versioned_migrations()

  def _run_versioned_migrations(self) -> None:
    """Menjalankan daftar migrasi skema bernomor secara urut, idempoten, & terisolasi per transaksi."""
    with self.connection() as conn:
      applied_rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
      applied = {int(r["version"]) for r in applied_rows}

    migrations = [
        (1, "sessions_activity_and_device_columns", self._mig_001_sessions_columns),
        (2, "assessments_material_id_column", self._mig_002_assessments_material),
        (3, "correction_requests_hidden_flag", self._mig_003_correction_hidden),
        (4, "users_admin_role_and_grades_check", self._mig_004_admin_role_and_checks),
        (5, "composite_indexes_and_pg_native_types", self._mig_005_indexes_and_pg_types),
        (6, "assessments_is_graded_flag", self._mig_006_assessments_is_graded),
        (7, "grades_revealed_at_column", self._mig_007_grades_revealed_at),
    ]
    for ver, name, fn in migrations:
      if ver in applied:
        continue
      with self.connection() as conn:
        fn(conn)
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?) ON CONFLICT (version) DO NOTHING",
            (ver, name, utc_now_iso()),
        )

  def _pg_col_types(self, conn: CompatConnection, table: str) -> Dict[str, str]:
    rows = conn.execute(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    ).fetchall()
    return {str(r["column_name"]): str(r["data_type"]).lower() for r in rows}

  def _mig_001_sessions_columns(self, conn: CompatConnection) -> None:
    if self.is_postgres:
      cols = self._pg_col_types(conn, "sessions")
      created_is_text = cols.get("created_at") == "text"
      if not cols or "last_activity_at" not in cols:
        col_type = "TEXT" if created_is_text else "TIMESTAMPTZ"
        conn.execute(f"ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_activity_at {col_type}")
        cols = self._pg_col_types(conn, "sessions")
      if not cols or "user_agent" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_agent TEXT NOT NULL DEFAULT ''")
      if not cols or "ip_address" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN IF NOT EXISTS ip_address TEXT NOT NULL DEFAULT ''")
      last_act_type = cols.get("last_activity_at")
      if last_act_type == "timestamp with time zone" and created_is_text:
        conn.execute(
            "UPDATE sessions SET last_activity_at = created_at::timestamptz "
            "WHERE last_activity_at IS NULL AND created_at IS NOT NULL AND created_at <> ''"
        )
      elif last_act_type == "text" and not created_is_text:
        conn.execute(
            "UPDATE sessions SET last_activity_at = created_at::text "
            "WHERE last_activity_at IS NULL AND created_at IS NOT NULL"
        )
      else:
        conn.execute("UPDATE sessions SET last_activity_at = created_at WHERE last_activity_at IS NULL")
    else:
      cols = [r["name"] for r in conn.execute("PRAGMA table_info(sessions)").fetchall()]
      if "last_activity_at" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN last_activity_at TEXT")
      if "user_agent" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN user_agent TEXT NOT NULL DEFAULT ''")
      if "ip_address" not in cols:
        conn.execute("ALTER TABLE sessions ADD COLUMN ip_address TEXT NOT NULL DEFAULT ''")
      conn.execute("UPDATE sessions SET last_activity_at = created_at WHERE last_activity_at IS NULL")

  def _mig_002_assessments_material(self, conn: CompatConnection) -> None:
    if self.is_postgres:
      cols = self._pg_col_types(conn, "assessments")
      if not cols or "material_id" not in cols:
        conn.execute("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS material_id INTEGER REFERENCES learning_materials(id) ON DELETE SET NULL")
    else:
      cols = [r["name"] for r in conn.execute("PRAGMA table_info(assessments)").fetchall()]
      if "material_id" not in cols:
        conn.execute("ALTER TABLE assessments ADD COLUMN material_id INTEGER REFERENCES learning_materials(id) ON DELETE SET NULL")

  def _mig_007_grades_revealed_at(self, conn: CompatConnection) -> None:
    if self.is_postgres:
      cols = self._pg_col_types(conn, "grades")
      if not cols or "revealed_at" not in cols:
        conn.execute("ALTER TABLE grades ADD COLUMN IF NOT EXISTS revealed_at TIMESTAMPTZ DEFAULT NULL")
    else:
      cols = [r["name"] for r in conn.execute("PRAGMA table_info(grades)").fetchall()]
      if "revealed_at" not in cols:
        conn.execute("ALTER TABLE grades ADD COLUMN revealed_at TEXT DEFAULT NULL")

  def _mig_006_assessments_is_graded(self, conn: CompatConnection) -> None:
    if self.is_postgres:
      cols = self._pg_col_types(conn, "assessments")
      if "is_graded" not in cols:
        conn.execute("ALTER TABLE assessments ADD COLUMN IF NOT EXISTS is_graded BOOLEAN NOT NULL DEFAULT TRUE")
    else:
      cols = [r["name"] for r in conn.execute("PRAGMA table_info(assessments)").fetchall()]
      if "is_graded" not in cols:
        conn.execute("ALTER TABLE assessments ADD COLUMN is_graded INTEGER NOT NULL DEFAULT 1 CHECK(is_graded IN (0, 1))")

  def _mig_003_correction_hidden(self, conn: CompatConnection) -> None:
    if self.is_postgres:
      cols = self._pg_col_types(conn, "correction_requests")
      if not cols or "hidden_by_student" not in cols:
        conn.execute("ALTER TABLE correction_requests ADD COLUMN IF NOT EXISTS hidden_by_student BOOLEAN NOT NULL DEFAULT FALSE")
    else:
      cols = [r["name"] for r in conn.execute("PRAGMA table_info(correction_requests)").fetchall()]
      if "hidden_by_student" not in cols:
        conn.execute("ALTER TABLE correction_requests ADD COLUMN hidden_by_student INTEGER NOT NULL DEFAULT 0 CHECK(hidden_by_student IN (0, 1))")

  def _mig_004_admin_role_and_checks(self, conn: CompatConnection) -> None:
    if self.is_postgres:
      conn.execute("""
        DO $$
        DECLARE r RECORD;
        BEGIN
          FOR r IN
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'users'::regclass AND contype = 'c'
              AND pg_get_constraintdef(oid) ILIKE '%role%'
          LOOP
            EXECUTE format('ALTER TABLE users DROP CONSTRAINT IF EXISTS %I', r.conname);
          END LOOP;
          ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('admin', 'teacher', 'student'));
        EXCEPTION WHEN undefined_table THEN NULL;
        END $$;
      """)
    else:
      row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
      if row and "'admin'" not in str(row["sql"] or ""):
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("""
          CREATE TABLE users_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'teacher', 'student')),
            full_name TEXT NOT NULL,
            email TEXT,
            status TEXT NOT NULL DEFAULT 'active'
              CHECK(status IN ('active', 'pending_activation', 'deactivated')),
            must_change_password INTEGER NOT NULL DEFAULT 0 CHECK(must_change_password IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
          )
        """)
        conn.execute("INSERT INTO users_new SELECT * FROM users")
        conn.execute("DROP TABLE users")
        conn.execute("ALTER TABLE users_new RENAME TO users")
        conn.execute("PRAGMA foreign_keys = ON")

  def _mig_005_indexes_and_pg_types(self, conn: CompatConnection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS idx_assessments_material ON assessments(material_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_learning_materials_class ON learning_materials(class_id, sort_order)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_enrollments_student_class ON student_enrollments(student_id, class_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_materials_class_arch_order ON learning_materials(class_id, is_archived, sort_order)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_grade_history_lookup ON grade_history(assessment_id, student_id, changed_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_att_history_lookup ON attendance_history(session_id, student_id, changed_at)")

    if self.is_postgres:
      bool_cols = [
          ("users", "must_change_password", "FALSE"),
          ("academic_periods", "is_active", "FALSE"),
          ("academic_periods", "is_archived", "FALSE"),
          ("classes", "allow_student_report_download", "TRUE"),
          ("classes", "is_archived", "FALSE"),
          ("learning_materials", "is_archived", "FALSE"),
          ("class_announcements", "is_pinned", "FALSE"),
          ("correction_requests", "hidden_by_student", "FALSE"),
      ]
      for tbl, col, default_lit in bool_cols:
        col_map = self._pg_col_types(conn, tbl)
        if col_map.get(col) in ("integer", "smallint", "bigint"):
          conn.execute(f"""
            DO $$
            DECLARE r RECORD;
            BEGIN
              FOR r IN
                SELECT conname FROM pg_constraint
                WHERE conrelid = '{tbl}'::regclass AND contype = 'c'
                  AND pg_get_constraintdef(oid) ILIKE '%{col}%'
              LOOP
                EXECUTE format('ALTER TABLE {tbl} DROP CONSTRAINT IF EXISTS %I', r.conname);
              END LOOP;
            END $$;
          """)
          conn.execute(f"ALTER TABLE {tbl} ALTER COLUMN {col} DROP DEFAULT")
          conn.execute(f"ALTER TABLE {tbl} ALTER COLUMN {col} TYPE BOOLEAN USING ({col} <> 0)")
          conn.execute(f"ALTER TABLE {tbl} ALTER COLUMN {col} SET DEFAULT {default_lit}")
      sess_cols = self._pg_col_types(conn, "sessions")
      if sess_cols.get("created_at") == "text" and sess_cols.get("last_activity_at") == "timestamp with time zone":
        conn.execute(
            "ALTER TABLE sessions ALTER COLUMN created_at TYPE TIMESTAMPTZ "
            "USING NULLIF(created_at, '')::timestamptz"
        )

  def create_backup(self, label: str = "manual") -> str:
    """Membuat salinan cadangan basis data SQLite secara aman."""
    if self.is_postgres:
      raise ValidationError(
          "Pada mode PostgreSQL cloud (Vercel/Neon/Supabase), pencadangan dikelola melalui fitur snapshot/PITR penyedia basis data."
      )
    if self.db_path == ":memory:":
      raise ValidationError(
          "Pencadangan berkas tidak didukung pada basis data ':memory:'."
      )
    safe_label = "".join(c for c in label if c.isalnum() or c in ("-", "_")) or "manual"
    Path(self.backup_dir).mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"edutrack_{stamp}_{safe_label}.db"
    target = Path(self.backup_dir) / filename

    src_conn = self._create_sqlite_connection()
    dst_conn = sqlite3.connect(str(target))
    try:
      src_conn.backup(dst_conn)
    finally:
      dst_conn.close()
      src_conn.close()
    return filename

  def list_backups(self) -> List[dict]:
    """Mengembalikan daftar berkas cadangan lokal (mode SQLite)."""
    if self.is_postgres:
      return []
    bdir = Path(self.backup_dir)
    if not bdir.exists():
      return []
    items = []
    for entry in sorted(bdir.glob("*.db"), reverse=True):
      stat = entry.stat()
      items.append({
          "filename": entry.name,
          "size_bytes": stat.st_size,
          "modified_at": datetime.fromtimestamp(
              stat.st_mtime, tz=timezone.utc
          ).isoformat(),
      })
    return items

  def restore_backup(self, filename: str) -> None:
    """Memulihkan basis data lokal dari berkas cadangan yang sah."""
    if self.is_postgres:
      raise ValidationError(
          "Pemulihan berkas lokal tidak digunakan pada mode PostgreSQL cloud. Gunakan dashboard Neon/Supabase."
      )
    if self.db_path == ":memory:":
      raise ValidationError(
          "Pemulihan berkas tidak didukung pada basis data ':memory:'."
      )
    if os.path.basename(filename) != filename or not filename.endswith(".db"):
      raise ValidationError("Nama berkas cadangan tidak valid.")
    source = Path(self.backup_dir) / filename
    if not source.exists():
      raise NotFoundError(f"Berkas cadangan '{filename}' tidak ditemukan.")
    shutil.copy2(str(source), self.db_path)
    self.initialize()
