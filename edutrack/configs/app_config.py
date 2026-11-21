"""Konfigurasi bertipe eksplisit untuk aplikasi EduTrack.

Semua parameter sistem (jalur SQLite atau URL PostgreSQL cloud, parameter
hashing, masa berlaku sesi, ambang ketuntasan, dan pengaturan cookie) dikelola
secara deterministik melalui AppConfig. Pembacaan environment variable hanya
dilakukan pada batas konfigurasi lewat ``AppConfig.from_env()``.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


_UNSUPPORTED_LIBPQ_PARAMS = frozenset({
    "pgbouncer",
    "supa",
    "connection_limit",
    "pool_timeout",
    "schema",
})


def sanitize_postgres_url(raw_url: str) -> str:
  """Menormalkan URL PostgreSQL agar kompatibel dengan psycopg/libpq & Supabase.

  Mengubah skema ``postgres://`` menjadi ``postgresql://`` serta membuang
  parameter query non-libpq (mis. ``pgbouncer=true``, ``supa=base-pooler.x``)
  yang kerap disisipkan integrasi Vercel-Supabase, sambil mempertahankan
  parameter standar seperti ``sslmode=require``.

  Args:
    raw_url: String koneksi PostgreSQL mentah.

  Returns:
    String koneksi PostgreSQL yang bersih dan valid untuk libpq/psycopg.

  Raises:
    ValueError: Jika skema URL bukan ``postgres://`` atau ``postgresql://``.
  """
  cleaned = (raw_url or "").strip()
  if cleaned.startswith("postgres://"):
    cleaned = "postgresql://" + cleaned[len("postgres://"):]
  if not cleaned.startswith("postgresql://"):
    raise ValueError("URL PostgreSQL harus diawali 'postgresql://' atau 'postgres://'.")

  parts = urlsplit(cleaned)
  filtered_query = [
      (k, v)
      for k, v in parse_qsl(parts.query, keep_blank_values=True)
      if k.lower() not in _UNSUPPORTED_LIBPQ_PARAMS
  ]
  return urlunsplit((
      parts.scheme,
      parts.netloc,
      parts.path,
      urlencode(filtered_query),
      parts.fragment,
  ))


@dataclass(frozen=True)
class AppConfig:
  """Konfigurasi utama aplikasi EduTrack."""

  db_path: str = "edutrack_data.db"
  database_url: Optional[str] = None
  backup_dir: str = "edutrack_backups"
  session_ttl_hours: int = 24
  session_idle_timeout_minutes: int = 60
  recovery_ttl_minutes: int = 30
  pbkdf2_iterations: int = 120_000
  default_mastery_threshold: float = 75.0
  high_absence_threshold_pct: float = 20.0
  cookie_name: str = "edutrack_session"
  csrf_cookie_name: str = "edutrack_csrf"
  cookie_secure: bool = False
  seed_demo_data: bool = True
  session_touch_interval_seconds: int = 300
  ews_alpa_threshold: int = 3
  ews_unsubmitted_checklist_threshold: int = 3
  login_rate_limit_max_attempts: int = 5
  login_rate_limit_window_seconds: int = 300

  def __post_init__(self) -> None:
    if not self.database_url and (not self.db_path or not self.db_path.strip()):
      raise ValueError("db_path tidak boleh kosong apabila database_url tidak disetel.")
    if self.database_url:
      url = self.database_url.strip()
      if not (
          url.startswith("postgres://")
          or url.startswith("postgresql://")
          or url.startswith("sqlite:")
      ):
        raise ValueError(
            "database_url harus diawali 'postgresql://', 'postgres://', atau 'sqlite:'."
        )
    if self.session_ttl_hours <= 0:
      raise ValueError("session_ttl_hours harus bernilai positif.")
    if self.session_idle_timeout_minutes <= 0:
      raise ValueError("session_idle_timeout_minutes harus bernilai positif.")
    if self.recovery_ttl_minutes <= 0:
      raise ValueError("recovery_ttl_minutes harus bernilai positif.")
    if self.pbkdf2_iterations < 10_000:
      raise ValueError("pbkdf2_iterations minimal 10.000 demi keamanan.")
    if not (0.0 <= self.default_mastery_threshold <= 100.0):
      raise ValueError("default_mastery_threshold harus antara 0 dan 100.")
    if not (0.0 <= self.high_absence_threshold_pct <= 100.0):
      raise ValueError("high_absence_threshold_pct harus antara 0 dan 100.")
    if self.ews_alpa_threshold < 1:
      raise ValueError("ews_alpa_threshold harus >= 1.")
    if self.login_rate_limit_max_attempts < 1:
      raise ValueError("login_rate_limit_max_attempts harus >= 1.")
    if self.login_rate_limit_window_seconds < 1:
      raise ValueError("login_rate_limit_window_seconds harus >= 1.")
    if self.session_touch_interval_seconds < 0:
      raise ValueError("session_touch_interval_seconds harus >= 0.")

  @property
  def is_postgres(self) -> bool:
    """Mengembalikan True apabila konfigurasi mengarah ke PostgreSQL."""
    if not self.database_url:
      return False
    url = self.database_url.strip().lower()
    return url.startswith("postgres://") or url.startswith("postgresql://")

  @staticmethod
  def _parse_positive_int(raw: Optional[str], default: int) -> int:
    if raw is None or not str(raw).strip():
      return default
    try:
      val = int(str(raw).strip())
      return val if val > 0 else default
    except ValueError:
      return default

  @classmethod
  def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "AppConfig":
    """Membentuk AppConfig dari environment variable (kompatibel Vercel/Supabase/Neon).

    Urutan prioritas koneksi PostgreSQL:
      1. ``DATABASE_URL`` (jika disetel manual)
      2. ``POSTGRES_URL`` (IPv4 pooler integrasi Vercel-Supabase)
      3. ``POSTGRES_PRISMA_URL``
      4. ``POSTGRES_URL_NON_POOLING`` / ``SUPABASE_DB_URL``
    """
    source = os.environ if env is None else env
    # Prioritaskan DATABASE_URL (manual), lalu POSTGRES_URL (IPv4 pooler) sebelum NON_POOLING (IPv6-only di Supabase).
    raw_db_url = (
        source.get("DATABASE_URL")
        or source.get("POSTGRES_URL")
        or source.get("POSTGRES_PRISMA_URL")
        or source.get("POSTGRES_URL_NON_POOLING")
        or source.get("SUPABASE_DB_URL")
        or ""
    ).strip()

    normalized_url: Optional[str] = None
    if raw_db_url:
      if raw_db_url.startswith("postgres://") or raw_db_url.startswith("postgresql://"):
        normalized_url = sanitize_postgres_url(raw_db_url)
      else:
        normalized_url = raw_db_url

    is_vercel = source.get("VERCEL") == "1"
    default_db_path = "/tmp/edutrack_temp.db" if is_vercel else "edutrack_data.db"
    db_path = (source.get("EDUTRACK_DB_PATH") or default_db_path).strip()

    cookie_secure_raw = source.get("EDUTRACK_COOKIE_SECURE")
    if cookie_secure_raw is not None:
      cookie_secure = cookie_secure_raw.strip().lower() in ("1", "true", "yes")
    else:
      cookie_secure = is_vercel

    seed_raw = source.get("EDUTRACK_SEED_DEMO", "true").strip().lower()
    seed_demo = seed_raw not in ("0", "false", "no")

    return cls(
        db_path=db_path,
        database_url=normalized_url,
        backup_dir=source.get("EDUTRACK_BACKUP_DIR", "edutrack_backups"),
        session_ttl_hours=cls._parse_positive_int(source.get("EDUTRACK_SESSION_TTL_HOURS"), 24),
        session_idle_timeout_minutes=cls._parse_positive_int(source.get("EDUTRACK_SESSION_IDLE_TIMEOUT_MINUTES"), 60),
        recovery_ttl_minutes=cls._parse_positive_int(source.get("EDUTRACK_RECOVERY_TTL_MINUTES"), 30),
        pbkdf2_iterations=cls._parse_positive_int(source.get("EDUTRACK_PBKDF2_ITERATIONS"), 120000),
        cookie_secure=cookie_secure,
        seed_demo_data=seed_demo,
        session_touch_interval_seconds=cls._parse_positive_int(source.get("EDUTRACK_SESSION_TOUCH_INTERVAL_SECONDS"), 300),
        ews_alpa_threshold=cls._parse_positive_int(source.get("EDUTRACK_EWS_ALPA_THRESHOLD"), 3),
        ews_unsubmitted_checklist_threshold=cls._parse_positive_int(
            source.get("EDUTRACK_EWS_UNSUBMITTED_THRESHOLD"), 3
        ),
        login_rate_limit_max_attempts=cls._parse_positive_int(source.get("EDUTRACK_LOGIN_MAX_ATTEMPTS"), 5),
        login_rate_limit_window_seconds=cls._parse_positive_int(source.get("EDUTRACK_LOGIN_WINDOW_SECONDS"), 300),
    )
