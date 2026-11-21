"""Hierarki pengecualian (domain errors) aplikasi EduTrack.

Semua kesalahan bisnis dipetakan secara eksplisit ke kelas turunan DomainError
agar lapisan layanan dan API tidak pernah menelan error secara diam-diam.
"""

from __future__ import annotations

from typing import Dict, Optional


class DomainError(Exception):
  """Kesalahan dasar untuk seluruh aturan domain aplikasi."""

  http_status: int = 400

  def __init__(self, message: str, code: str = "domain_error", headers: Optional[Dict[str, str]] = None) -> None:
    super().__init__(message)
    self.message = message
    self.headers = headers
    self.code = code


class ValidationError(DomainError):
  """Input pengguna atau invarian domain tidak valid."""

  http_status: int = 400

  def __init__(self, message: str, code: str = "validation_error", headers: Optional[Dict[str, str]] = None) -> None:
    super().__init__(message, code=code, headers=headers)


class AuthenticationError(DomainError):
  """Kredensial tidak valid, akun nonaktif, atau sesi kedaluwarsa."""

  http_status: int = 401

  def __init__(self, message: str, code: str = "authentication_error", headers: Optional[Dict[str, str]] = None) -> None:
    super().__init__(message, code=code, headers=headers)


class AuthorizationError(DomainError):
  """Pengguna tidak memiliki hak akses terhadap sumber daya yang diminta."""

  http_status: int = 403

  def __init__(self, message: str, code: str = "authorization_error", headers: Optional[Dict[str, str]] = None) -> None:
    super().__init__(message, code=code, headers=headers)


class NotFoundError(DomainError):
  """Entitas yang diminta tidak ditemukan."""

  http_status: int = 404

  def __init__(self, message: str, code: str = "not_found", headers: Optional[Dict[str, str]] = None) -> None:
    super().__init__(message, code=code, headers=headers)


class ConflictError(DomainError):
  """Terjadi konflik keunikan atau state (mis. duplikasi akun/presensi)."""

  http_status: int = 409

  def __init__(self, message: str, code: str = "conflict_error", headers: Optional[Dict[str, str]] = None) -> None:
    super().__init__(message, code=code, headers=headers)


class RateLimitError(DomainError):
  """Kesalahan pembatasan laju permintaan (HTTP 429 Too Many Requests)."""

  http_status = 429

  def __init__(
      self,
      message: str = "Terlalu banyak percobaan. Silakan coba lagi nanti.",
      code: str = "rate_limit_exceeded",
      retry_after: int = 60,
  ) -> None:
    super().__init__(message, code=code, headers={"Retry-After": str(max(1, int(retry_after)))})
