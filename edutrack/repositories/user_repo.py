"""Repositori pengguna, sesi autentikasi, token pemulihan, dan catatan audit."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from edutrack.domain.errors import ConflictError
from edutrack.domain.models import AccountStatus, Role, User
from edutrack.repositories.database import Database, parse_utc_dt, DatabaseIntegrityError, utc_now_iso


class UserRepository:
  """Akses data persisten untuk akun pengguna, sesi, pemulihan, dan audit."""

  def __init__(self, db: Database) -> None:
    self._db = db

  @staticmethod
  def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=int(row["id"]),
        username=str(row["username"]),
        full_name=str(row["full_name"]),
        role=Role(row["role"]),
        status=AccountStatus(row["status"]),
        must_change_password=bool(row["must_change_password"]),
        email=row["email"],
        created_at=str(row["created_at"]),
    )

  def create_user(
      self,
      username: str,
      password_hash: str,
      full_name: str,
      role: Role,
      status: AccountStatus = AccountStatus.ACTIVE,
      must_change_password: bool = False,
      email: Optional[str] = None,
  ) -> User:
    """Menyimpan akun pengguna baru ke basis data."""
    now = utc_now_iso()
    try:
      with self._db.connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO users (
              username, password_hash, full_name, role, status,
              must_change_password, email, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username,
                password_hash,
                full_name,
                role.value,
                status.value,
                self._db.bool_val(must_change_password),
                email,
                now,
                now,
            ),
        )
        user_id = int(cur.lastrowid)
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    except DatabaseIntegrityError as exc:
      raise ConflictError(
          f"Username '{username}' sudah terdaftar dalam sistem."
      ) from exc
    return self._row_to_user(row)

  def get_by_id(self, user_id: int) -> Optional[User]:
    """Mengambil pengguna berdasarkan ID."""
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT * FROM users WHERE id = ?", (user_id,)
      ).fetchone()
    return self._row_to_user(row) if row else None

  def get_auth_record_by_username(self, username: str) -> Optional[Dict[str, Any]]:
    """Mengambil pengguna beserta password_hash untuk verifikasi login."""
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username,)
      ).fetchone()
    if not row:
      return None
    return {
        "user": self._row_to_user(row),
        "password_hash": str(row["password_hash"]),
    }

  def get_password_hash(self, user_id: int) -> Optional[str]:
    """Mengambil hash kata sandi pengguna berdasarkan ID."""
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT password_hash FROM users WHERE id = ?", (user_id,)
      ).fetchone()
    return str(row["password_hash"]) if row else None

  def update_password(
      self,
      user_id: int,
      new_password_hash: str,
      must_change_password: bool = False,
      activate_if_pending: bool = False,
  ) -> None:
    """Memperbarui hash kata sandi pengguna dan status aktivasi opsional."""
    now = utc_now_iso()
    with self._db.connection() as conn:
      if activate_if_pending:
        conn.execute(
            """
            UPDATE users
            SET password_hash = ?,
                must_change_password = ?,
                status = CASE WHEN status = 'pending_activation' THEN 'active' ELSE status END,
                updated_at = ?
            WHERE id = ?
            """,
            (new_password_hash, self._db.bool_val(must_change_password), now, user_id),
        )
      else:
        conn.execute(
            """
            UPDATE users
            SET password_hash = ?, must_change_password = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_password_hash, self._db.bool_val(must_change_password), now, user_id),
        )

  def update_account_profile(
      self,
      user_id: int,
      full_name: Optional[str] = None,
      email: Optional[str] = None,
      status: Optional[AccountStatus] = None,
      username: Optional[str] = None,
  ) -> Optional[User]:
    """Memperbarui username, nama lengkap, email, atau status akun pengguna."""
    now = utc_now_iso()
    try:
      with self._db.connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not row:
          return None
        next_username = username if username is not None else row["username"]
        next_name = full_name if full_name is not None else row["full_name"]
        next_email = email if email is not None else row["email"]
        next_status = status.value if status is not None else row["status"]
        conn.execute(
            """
            UPDATE users
            SET username = ?, full_name = ?, email = ?, status = ?, updated_at = ?
            WHERE id = ?
            """,
            (next_username, next_name, next_email, next_status, now, user_id),
        )
        updated = conn.execute(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    except DatabaseIntegrityError as exc:
      raise ConflictError(
          f"Username '{username}' sudah digunakan akun lain."
      ) from exc
    return self._row_to_user(updated)

  def delete_user(self, user_id: int) -> None:
    """Menghapus akun pengguna (dipakai untuk rollback pembuatan akun gagal)."""
    with self._db.connection() as conn:
      conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

  def create_session(
      self,
      user_id: int,
      token_hash: str,
      expires_at: str,
      now_iso: Optional[str] = None,
      user_agent: str = "",
      ip_address: str = "",
  ) -> int:
    """Menyimpan sesi autentikasi baru beserta info perangkat dan cap waktu aktivitas awal."""
    now = now_iso or utc_now_iso()
    clean_ua = (user_agent or "")[:250]
    clean_ip = (ip_address or "")[:64]
    with self._db.connection() as conn:
      cur = conn.execute(
          """
          INSERT INTO sessions (user_id, token_hash, expires_at, last_activity_at, user_agent, ip_address, created_at)
          VALUES (?, ?, ?, ?, ?, ?, ?)
          """,
          (user_id, token_hash, expires_at, now, clean_ua, clean_ip, now),
      )
      return int(cur.lastrowid)

  def get_active_session_user(
      self,
      token_hash: str,
      now_iso: str,
      idle_cutoff_iso: Optional[str] = None,
  ) -> Optional[User]:
    """Mengambil pengguna jika sesi aktif, belum kedaluwarsa, dan tidak melewati batas idle."""
    with self._db.connection() as conn:
      row = conn.execute(
          """
          SELECT u.*, COALESCE(s.last_activity_at, s.created_at) AS session_last_activity
          FROM sessions s
          JOIN users u ON u.id = s.user_id
          WHERE s.token_hash = ?
            AND s.revoked_at IS NULL
            AND s.expires_at > ?
          """,
          (token_hash, now_iso),
      ).fetchone()
    if not row:
      return None
    if idle_cutoff_iso is not None:
      last_act = str(row["session_last_activity"] or "")
      if last_act and parse_utc_dt(last_act) < parse_utc_dt(idle_cutoff_iso):
        return None
    return self._row_to_user(row)

  def is_session_idle_expired(
      self, token_hash: str, now_iso: str, idle_cutoff_iso: str
  ) -> bool:
    """Memeriksa apakah sesi aktif namun melewati batas tidak aktif (idle)."""
    with self._db.connection() as conn:
      row = conn.execute(
          """
          SELECT COALESCE(last_activity_at, created_at) AS last_act
          FROM sessions
          WHERE token_hash = ?
            AND revoked_at IS NULL
            AND expires_at > ?
          """,
          (token_hash, now_iso),
      ).fetchone()
    if not row:
      return False
    return bool(row["last_act"]) and parse_utc_dt(row["last_act"]) < parse_utc_dt(idle_cutoff_iso)

  def get_active_session_with_activity(
      self, token_hash: str, now_iso: str
  ) -> Optional[Tuple[User, str]]:
    """Mengembalikan (User, last_activity_at) untuk pengecekan throttle tanpa query tambahan."""
    with self._db.connection() as conn:
      row = conn.execute(
          """
          SELECT u.*, COALESCE(s.last_activity_at, s.created_at) AS session_last_activity
          FROM sessions s
          JOIN users u ON u.id = s.user_id
          WHERE s.token_hash = ?
            AND s.revoked_at IS NULL
            AND s.expires_at > ?
          """,
          (token_hash, now_iso),
      ).fetchone()
    if not row:
      return None
    return self._row_to_user(row), str(row["session_last_activity"] or "")

  def touch_session_activity(self, token_hash: str, now_iso: Optional[str] = None) -> None:
    """Memperbarui waktu aktivitas terakhir untuk sesi aktif."""
    now = now_iso or utc_now_iso()
    with self._db.connection() as conn:
      conn.execute(
          "UPDATE sessions SET last_activity_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
          (now, token_hash),
      )

  def revoke_session(self, token_hash: str) -> None:
    """Mencabut satu sesi berdasarkan token_hash."""
    now = utc_now_iso()
    with self._db.connection() as conn:
      conn.execute(
          "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
          (now, token_hash),
      )

  def revoke_all_user_sessions(self, user_id: int) -> None:
    """Mencabut seluruh sesi aktif milik pengguna tertentu."""
    now = utc_now_iso()
    with self._db.connection() as conn:
      conn.execute(
          "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
          (now, user_id),
      )

  def create_recovery_token(
      self, user_id: int, token_hash: str, expires_at: str
  ) -> None:
    """Menyimpan token pemulihan akun satu kali pakai."""
    now = utc_now_iso()
    with self._db.connection() as conn:
      conn.execute(
          """
          INSERT INTO recovery_tokens (user_id, token_hash, expires_at, created_at)
          VALUES (?, ?, ?, ?)
          """,
          (user_id, token_hash, expires_at, now),
      )

  def consume_recovery_token(self, token_hash: str, now_iso: str) -> Optional[int]:
    """Memvalidasi dan menandai token pemulihan sebagai telah dipakai."""
    with self._db.connection() as conn:
      row = conn.execute(
          """
          SELECT id, user_id
          FROM recovery_tokens
          WHERE token_hash = ?
            AND used_at IS NULL
            AND expires_at > ?
          """,
          (token_hash, now_iso),
      ).fetchone()
      if not row:
        return None
      conn.execute(
          "UPDATE recovery_tokens SET used_at = ? WHERE id = ?",
          (now_iso, int(row["id"])),
      )
      return int(row["user_id"])

  def log_audit(
      self,
      actor_user_id: Optional[int],
      action: str,
      entity_type: str,
      entity_id: str | int,
      details: str = "",
  ) -> None:
    """Mencatat jejak aktivitas penting ke tabel audit_logs."""
    now = utc_now_iso()
    with self._db.connection() as conn:
      conn.execute(
          """
          INSERT INTO audit_logs (actor_user_id, action, entity_type, entity_id, details, created_at)
          VALUES (?, ?, ?, ?, ?, ?)
          """,
          (actor_user_id, action, entity_type, str(entity_id), details, now),
      )

  def list_audit_logs(
      self, actor_user_id: Optional[int] = None, limit: int = 100, offset: int = 0
  ) -> List[Dict[str, Any]]:
    """Mengambil daftar catatan aktivitas terbaru."""
    with self._db.connection() as conn:
      if actor_user_id is not None:
        rows = conn.execute(
            """
            SELECT a.*, u.username AS actor_username, u.full_name AS actor_name
            FROM audit_logs a
            LEFT JOIN users u ON u.id = a.actor_user_id
            WHERE a.actor_user_id = ?
            ORDER BY a.id DESC
            LIMIT ?
            """,
            (actor_user_id, limit),
        ).fetchall()
      else:
        rows = conn.execute(
            """
            SELECT a.*, u.username AS actor_username, u.full_name AS actor_name
            FROM audit_logs a
            LEFT JOIN users u ON u.id = a.actor_user_id
            ORDER BY a.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]

  def list_active_sessions(
      self,
      user_id: int,
      now_iso: str,
      idle_cutoff_iso: str,
      current_token_hash: Optional[str] = None,
  ) -> List[Dict[str, Any]]:
    """Mengembalikan daftar sesi aktif milik pengguna (tanpa membocorkan token_hash)."""
    with self._db.connection() as conn:
      rows = conn.execute(
          """
          SELECT id, token_hash,
                 COALESCE(user_agent, '') AS user_agent,
                 COALESCE(ip_address, '') AS ip_address,
                 created_at,
                 COALESCE(last_activity_at, created_at) AS last_activity_at,
                 expires_at
          FROM sessions
          WHERE user_id = ?
            AND revoked_at IS NULL
            AND expires_at > ?
            AND COALESCE(last_activity_at, created_at) >= ?
          ORDER BY COALESCE(last_activity_at, created_at) DESC, id DESC
          """,
          (user_id, now_iso, idle_cutoff_iso),
      ).fetchall()
    result: List[Dict[str, Any]] = []
    for r in rows:
      d = dict(r)
      is_curr = bool(current_token_hash and str(d["token_hash"]) == current_token_hash)
      result.append({
          "id": int(d["id"]),
          "user_agent": str(d["user_agent"] or ""),
          "ip_address": str(d["ip_address"] or ""),
          "created_at": str(d["created_at"]),
          "last_activity_at": str(d["last_activity_at"]),
          "expires_at": str(d["expires_at"]),
          "is_current": is_curr,
      })
    return result

  def revoke_session_by_id(
      self,
      session_id: int,
      user_id: int,
      current_token_hash: Optional[str] = None,
  ) -> Tuple[bool, bool]:
    """Mencabut satu sesi aktif milik pengguna secara atomik. Returns (revoked, revoked_current)."""
    now = utc_now_iso()
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT id, token_hash FROM sessions WHERE id = ? AND user_id = ? AND revoked_at IS NULL",
          (session_id, user_id),
      ).fetchone()
      if not row:
        return False, False
      is_curr = bool(current_token_hash and str(row["token_hash"]) == current_token_hash)
      conn.execute(
          "UPDATE sessions SET revoked_at = ? WHERE id = ? AND user_id = ? AND revoked_at IS NULL",
          (now, session_id, user_id),
      )
      return True, is_curr

  def revoke_other_user_sessions(self, user_id: int, keep_token_hash: str) -> int:
    """Mencabut seluruh sesi aktif milik pengguna kecuali sesi saat ini."""
    now = utc_now_iso()
    with self._db.connection() as conn:
      cur = conn.execute(
          "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL AND token_hash != ?",
          (now, user_id, keep_token_hash),
      )
      return int(getattr(cur, "rowcount", 0) or 0)

  def count_recent_rate_attempts(
      self, rate_key: str, cutoff_iso: str
  ) -> Tuple[int, Optional[str]]:
    """Menghitung jumlah percobaan dalam jendela waktu & cap waktu tertua (untuk Retry-After)."""
    with self._db.connection() as conn:
      row = conn.execute(
          """
          SELECT COUNT(*) AS cnt, MIN(attempted_at) AS oldest
          FROM login_rate_limits
          WHERE rate_key = ? AND attempted_at >= ?
          """,
          (rate_key, cutoff_iso),
      ).fetchone()
    if not row:
      return 0, None
    return int(row["cnt"]), (str(row["oldest"]) if row["oldest"] is not None else None)

  def record_rate_attempt(
      self, rate_key: str, now_iso: str, prune_before_iso: Optional[str] = None
  ) -> None:
    """Mencatat satu percobaan pada rate limiter sekaligus membersihkan entri kedaluwarsa."""
    with self._db.connection() as conn:
      if prune_before_iso:
        conn.execute("DELETE FROM login_rate_limits WHERE attempted_at < ?", (prune_before_iso,))
      conn.execute(
          "INSERT INTO login_rate_limits (rate_key, attempted_at) VALUES (?, ?)",
          (rate_key, now_iso),
      )

  def clear_rate_attempts(self, rate_key: str) -> None:
    """Menghapus catatan kegagalan setelah autentikasi berhasil."""
    with self._db.connection() as conn:
      conn.execute("DELETE FROM login_rate_limits WHERE rate_key = ?", (rate_key,))
