"""Layanan autentikasi, sesi, RBAC, penggantian sandi, dan manajemen perangkat."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Callable, Dict, List, Optional, Sequence

from edutrack.configs.app_config import AppConfig
from edutrack.domain.errors import (
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from edutrack.domain.models import AccountStatus, Role, User
from edutrack.domain.security import (
    generate_secure_token,
    hash_password,
    hash_token,
    validate_password_strength,
    verify_password,
)
from edutrack.repositories.database import parse_utc_dt
from edutrack.repositories.user_repo import UserRepository


def _default_clock() -> datetime:
  return datetime.now(timezone.utc)


class AuthService:
  """Mengelola autentikasi pengguna, otorisasi RBAC, rate limiting, dan sesi aktif."""

  def __init__(
      self,
      user_repo: UserRepository,
      config: AppConfig,
      clock: Callable[[], datetime] = _default_clock,
  ) -> None:
    self._user_repo = user_repo
    self._config = config
    self._clock = clock

  @staticmethod
  def _summarize_user_agent(ua: str) -> str:
    raw = (ua or "").strip()
    if not raw:
      return "Perangkat tidak diketahui"
    low = raw.lower()
    browser = "Browser"
    if "edg/" in low:
      browser = "Edge"
    elif "chrome/" in low and "safari/" in low:
      browser = "Chrome"
    elif "firefox/" in low:
      browser = "Firefox"
    elif "safari/" in low:
      browser = "Safari"
    elif "testclient" in low or "httpx" in low:
      browser = "API Client"
    os_name = "Perangkat"
    if "android" in low:
      os_name = "Android"
    elif "iphone" in low or "ipad" in low:
      os_name = "iOS"
    elif "windows" in low:
      os_name = "Windows"
    elif "mac os" in low or "macintosh" in low:
      os_name = "macOS"
    elif "linux" in low:
      os_name = "Linux"
    return f"{browser} di {os_name}"

  def _enforce_rate_limit(
      self, keys_with_limits: List[tuple[str, int]], window_seconds: int, action_label: str
  ) -> None:
    if not hasattr(self._user_repo, "count_recent_rate_attempts"):
      return
    now = self._clock().replace(microsecond=0)
    cutoff_iso = (now - timedelta(seconds=window_seconds)).isoformat()
    for rate_key, limit in keys_with_limits:
      raw_res = self._user_repo.count_recent_rate_attempts(rate_key, cutoff_iso)
      if not isinstance(raw_res, tuple) or len(raw_res) != 2:
        continue
      cnt, oldest_iso = raw_res
      if cnt >= limit:
        retry_after = window_seconds
        if oldest_iso:
          try:
            oldest_dt = parse_utc_dt(oldest_iso)
            elapsed = (now - oldest_dt).total_seconds()
            retry_after = max(1, int(math.ceil(window_seconds - elapsed)))
          except ValueError:
            retry_after = window_seconds
        raise RateLimitError(
            f"Terlalu banyak percobaan {action_label}. Silakan coba lagi dalam {retry_after} detik.",
            retry_after=retry_after,
        )

  def _record_rate_failure(self, keys: List[str], window_seconds: int) -> None:
    if not hasattr(self._user_repo, "record_rate_attempt"):
      return
    now = self._clock().replace(microsecond=0)
    now_iso = now.isoformat()
    prune_before = (now - timedelta(seconds=window_seconds * 2)).isoformat()
    for rate_key in keys:
      self._user_repo.record_rate_attempt(rate_key, now_iso, prune_before_iso=prune_before)

  def _clear_rate_keys(self, keys: List[str]) -> None:
    if not hasattr(self._user_repo, "clear_rate_attempts"):
      return
    for rate_key in keys:
      self._user_repo.clear_rate_attempts(rate_key)

  def _register_privileged_user(
      self,
      role: Role,
      username: str,
      password: str,
      full_name: str,
      email: Optional[str] = None,
  ) -> User:
    clean_user = (username or "").strip()
    clean_name = (full_name or "").strip()
    if len(clean_user) < 3 or " " in clean_user:
      raise ValidationError(
          "Username minimal 3 karakter dan tidak boleh mengandung spasi."
      )
    if not clean_name:
      raise ValidationError("Nama lengkap wajib diisi.")
    validate_password_strength(password)

    pw_hash = hash_password(password, iterations=self._config.pbkdf2_iterations)
    user = self._user_repo.create_user(
        username=clean_user,
        password_hash=pw_hash,
        role=role,
        full_name=clean_name,
        email=email.strip() if email else None,
        status=AccountStatus.ACTIVE,
        must_change_password=False,
    )
    self._user_repo.log_audit(
        user.id,
        f"register_{role.value}",
        "user",
        user.id,
        f"Akun {role.value} '{clean_user}' dibuat.",
    )
    return user

  def register_teacher(
      self,
      username: str,
      password: str,
      full_name: str,
      email: Optional[str] = None,
  ) -> User:
    """Mendaftarkan akun guru baru dengan sandi ter-hash PBKDF2."""
    return self._register_privileged_user(Role.TEACHER, username, password, full_name, email=email)

  def register_admin(
      self,
      username: str,
      password: str,
      full_name: str,
      email: Optional[str] = None,
  ) -> User:
    """Mendaftarkan akun administrator sistem (memiliki akses backup/restore)."""
    return self._register_privileged_user(Role.ADMIN, username, password, full_name, email=email)

  def issue_session(
      self,
      user: User,
      user_agent: str = "",
      ip_address: str = "",
  ) -> Dict[str, object]:
    """Menerbitkan token sesi baru untuk pengguna terautentikasi."""
    raw_token = generate_secure_token(32)
    now = self._clock().replace(microsecond=0)
    now_iso = now.isoformat()
    expires_at = (now + timedelta(hours=self._config.session_ttl_hours)).isoformat()
    clean_ip = (ip_address or "unknown").strip()[:64] or "unknown"
    try:
      self._user_repo.create_session(
          user.id,
          hash_token(raw_token),
          expires_at,
          now_iso=now_iso,
          user_agent=user_agent,
          ip_address=clean_ip,
      )
    except TypeError:
      self._user_repo.create_session(user.id, hash_token(raw_token), expires_at, now_iso=now_iso)
    return {"token": raw_token, "expires_at": expires_at, "user": user}

  def login(
      self,
      username: str,
      password: str,
      user_agent: str = "",
      ip_address: str = "",
  ) -> Dict[str, object]:
    """Memverifikasi kredensial pengguna dengan rate limiting dan menerbitkan token sesi aman."""
    clean_user = (username or "").strip()
    norm_user = clean_user.lower()
    clean_ip = (ip_address or "unknown").strip()[:64] or "unknown"
    max_att = self._config.login_rate_limit_max_attempts
    win_sec = self._config.login_rate_limit_window_seconds

    limit_checks: List[tuple[str, int]] = [(f"ip:{clean_ip}", max_att * 4)]
    fail_keys: List[str] = [f"ip:{clean_ip}"]
    if norm_user:
      limit_checks.insert(0, (f"ip_user:{clean_ip}:{norm_user}", max_att))
      limit_checks.append((f"user:{norm_user}", max_att * 2))
      fail_keys.extend([f"ip_user:{clean_ip}:{norm_user}", f"user:{norm_user}"])

    self._enforce_rate_limit(limit_checks, win_sec, "login")

    if not clean_user or not password:
      self._record_rate_failure(fail_keys, win_sec)
      raise AuthenticationError("Username dan kata sandi wajib diisi.")

    record = self._user_repo.get_auth_record_by_username(clean_user)
    if not record or not verify_password(password, record["password_hash"]):
      self._record_rate_failure(fail_keys, win_sec)
      raise AuthenticationError("Username atau kata sandi tidak sesuai.")

    user: User = record["user"]
    if user.status == AccountStatus.DEACTIVATED:
      raise AuthenticationError(
          "Akun Anda sedang dinonaktifkan. Hubungi guru pengelola kelas."
      )

    if norm_user:
      self._clear_rate_keys([f"ip_user:{clean_ip}:{norm_user}", f"user:{norm_user}"])

    issued = self.issue_session(user, user_agent=user_agent, ip_address=clean_ip)
    self._user_repo.log_audit(
        user.id, "login", "session", user.id, f"Login berhasil ({user.role.value})."
    )
    return issued

  def authenticate_token(self, raw_token: Optional[str], touch_activity: bool = True) -> User:
    """Memvalidasi token sesi, batas idle 60 menit, dan throttle update aktivitas (default 5 menit)."""
    if not raw_token or not raw_token.strip():
      raise AuthenticationError("Autentikasi diperlukan. Silakan login terlebih dahulu.")
    token_digest = hash_token(raw_token)
    now = self._clock().replace(microsecond=0)
    now_iso = now.isoformat()
    idle_mins = getattr(self._config, "session_idle_timeout_minutes", 60)
    idle_cutoff_iso = (now - timedelta(minutes=idle_mins)).isoformat()

    if hasattr(self._user_repo, "is_session_idle_expired") and self._user_repo.is_session_idle_expired(
        token_digest, now_iso, idle_cutoff_iso
    ):
      self._user_repo.revoke_session(token_digest)
      raise AuthenticationError(
          f"Sesi Anda telah berakhir karena tidak ada aktivitas selama {idle_mins} menit. Silakan login kembali.",
          headers={"X-Session-Expired": "idle"},
      )

    last_activity_str: Optional[str] = None
    if hasattr(self._user_repo, "get_active_session_with_activity"):
      pair = self._user_repo.get_active_session_with_activity(token_digest, now_iso)
      if isinstance(pair, tuple) and len(pair) == 2:
        user, last_activity_str = pair
      else:
        user = None
    else:
      user = self._user_repo.get_active_session_user(token_digest, now_iso)

    if not user:
      raise AuthenticationError("Sesi tidak valid atau telah berakhir.")
    if user.status == AccountStatus.DEACTIVATED:
      self._user_repo.revoke_session(token_digest)
      raise AuthenticationError("Akun telah dinonaktifkan.")

    if touch_activity and hasattr(self._user_repo, "touch_session_activity"):
      touch_interval = getattr(self._config, "session_touch_interval_seconds", 300)
      should_touch = True
      if last_activity_str and touch_interval > 0:
        try:
          elapsed = (now - parse_utc_dt(last_activity_str)).total_seconds()
          should_touch = elapsed >= touch_interval
        except ValueError:
          should_touch = True
      if should_touch:
        self._user_repo.touch_session_activity(token_digest, now_iso)
    return user

  def logout(self, raw_token: Optional[str]) -> None:
    """Mencabut sesi autentikasi saat ini."""
    if not raw_token:
      return
    now_iso = self._clock().replace(microsecond=0).isoformat()
    token_digest = hash_token(raw_token)
    user = self._user_repo.get_active_session_user(token_digest, now_iso)
    self._user_repo.revoke_session(token_digest)
    if user:
      self._user_repo.log_audit(user.id, "logout", "session", user.id, "Logout pengguna.")

  def change_password(
      self, user: User, current_password: str, new_password: str
  ) -> User:
    """Mengganti kata sandi pengguna terautentikasi dan mencabut seluruh sesi lama."""
    stored_hash = self._user_repo.get_password_hash(user.id)
    if not stored_hash or not verify_password(current_password, stored_hash):
      raise AuthenticationError("Kata sandi saat ini tidak sesuai.")
    if current_password == new_password:
      raise ValidationError("Kata sandi baru harus berbeda dari kata sandi lama.")
    validate_password_strength(new_password)

    new_hash = hash_password(new_password, iterations=self._config.pbkdf2_iterations)
    self._user_repo.update_password(
        user.id,
        new_hash,
        must_change_password=False,
        activate_if_pending=True,
    )
    # Cabut seluruh sesi lama agar perangkat lain langsung keluar
    self._user_repo.revoke_all_user_sessions(user.id)
    self._user_repo.log_audit(
        user.id, "change_password", "user", user.id, "Kata sandi diperbarui dan seluruh sesi lama dicabut."
    )
    updated = self._user_repo.get_by_id(user.id)
    if not updated:
      raise NotFoundError("Pengguna tidak ditemukan.")
    return updated

  def update_own_profile(
      self,
      user: User,
      full_name: Optional[str] = None,
      email: Optional[str] = None,
      username: Optional[str] = None,
  ) -> User:
    """Memperbarui username login, nama lengkap, dan email milik pengguna sendiri."""
    clean_name = full_name.strip() if full_name is not None else None
    if clean_name is not None and not clean_name:
      raise ValidationError("Nama lengkap tidak boleh kosong.")
    clean_username = username.strip() if username is not None else None
    if clean_username is not None:
      if len(clean_username) < 3 or " " in clean_username:
        raise ValidationError(
            "Username minimal 3 karakter dan tidak boleh mengandung spasi."
        )
    clean_email = email.strip() if email is not None else None
    updated = self._user_repo.update_account_profile(
        user.id, full_name=clean_name, email=clean_email, username=clean_username
    )
    if not updated:
      raise NotFoundError("Pengguna tidak ditemukan.")
    self._user_repo.log_audit(
        user.id,
        "update_profile",
        "user",
        user.id,
        f"Pengaturan akun diperbarui (username={updated.username}).",
    )
    return updated

  def list_active_sessions(self, user: User, current_raw_token: Optional[str]) -> List[Dict[str, object]]:
    """Mengembalikan daftar sesi aktif milik pengguna saat ini (tanpa token_hash)."""
    now = self._clock().replace(microsecond=0)
    now_iso = now.isoformat()
    idle_mins = getattr(self._config, "session_idle_timeout_minutes", 60)
    idle_cutoff_iso = (now - timedelta(minutes=idle_mins)).isoformat()
    curr_hash = hash_token(current_raw_token) if current_raw_token else None
    rows = self._user_repo.list_active_sessions(
        user.id, now_iso=now_iso, idle_cutoff_iso=idle_cutoff_iso, current_token_hash=curr_hash
    )
    for r in rows:
      r["device_label"] = self._summarize_user_agent(str(r.get("user_agent") or ""))
    return rows

  def revoke_session_by_id(
      self, user: User, session_id: int, current_raw_token: Optional[str]
  ) -> Dict[str, object]:
    """Mencabut satu sesi aktif milik pengguna sendiri (anti-IDOR)."""
    curr_hash = hash_token(current_raw_token) if current_raw_token else None
    revoked, revoked_current = self._user_repo.revoke_session_by_id(
        session_id, user.id, current_token_hash=curr_hash
    )
    if not revoked:
      raise NotFoundError("Sesi aktif tidak ditemukan.")
    self._user_repo.log_audit(
        user.id, "revoke_session", "session", session_id, f"Sesi #{session_id} dicabut oleh pengguna."
    )
    return {"status": "revoked", "session_id": session_id, "revoked_current": revoked_current}

  def logout_all_devices(
      self, user: User, current_raw_token: Optional[str], keep_current: bool = False
  ) -> Dict[str, object]:
    """Mencabut seluruh sesi aktif pengguna di semua perangkat."""
    if keep_current and current_raw_token:
      curr_hash = hash_token(current_raw_token)
      revoked_cnt = self._user_repo.revoke_other_user_sessions(user.id, curr_hash)
      self._user_repo.log_audit(
          user.id, "logout_other_devices", "session", user.id,
          f"{revoked_cnt} sesi di perangkat lain dicabut.",
      )
      return {"status": "ok", "revoked_current": False, "revoked_others": revoked_cnt}
    self._user_repo.revoke_all_user_sessions(user.id)
    self._user_repo.log_audit(
        user.id, "logout_all_devices", "session", user.id, "Seluruh sesi di semua perangkat dicabut."
    )
    return {"status": "ok", "revoked_current": True}

  @staticmethod
  def require_role(user: User, expected_role: Role) -> None:
    """Memastikan pengguna memiliki peran yang dipersyaratkan."""
    if expected_role == Role.TEACHER and user.role == Role.ADMIN:
      return
    if user.role != expected_role:
      raise AuthorizationError(
          f"Akses ditolak: fitur ini khusus untuk peran '{expected_role.value}'."
      )

  @staticmethod
  def require_roles(user: User, allowed_roles: Sequence[Role]) -> None:
    """Memastikan pengguna memiliki salah satu peran yang diizinkan."""
    if user.role not in allowed_roles:
      allowed_txt = ", ".join(r.value for r in allowed_roles)
      raise AuthorizationError(
          f"Akses ditolak: fitur ini khusus untuk peran ({allowed_txt})."
      )
