"""Utilitas kriptografi murni untuk kata sandi dan token autentikasi.

Menggunakan pustaka standar Python (hashlib.pbkdf2_hmac, hmac, secrets) agar
deterministik, aman, dan bebas ketergantungan eksternal.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from edutrack.domain.errors import ValidationError


MIN_PASSWORD_LENGTH = 8


def validate_password_strength(password: str) -> None:
  """Memvalidasi kebijakan kekuatan minimal kata sandi.

  Args:
    password: Kata sandi teks biasa yang akan divalidasi.

  Raises:
    ValidationError: Jika kata sandi kosong atau kurang dari panjang minimum.
  """
  if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
    raise ValidationError(
        f"Kata sandi minimal harus terdiri dari {MIN_PASSWORD_LENGTH} karakter."
    )
  if password.strip() != password:
    raise ValidationError(
        "Kata sandi tidak boleh diawali atau diakhiri spasi."
    )


def hash_password(password: str, iterations: int = 120_000) -> str:
  """Menghasilkan hash PBKDF2-HMAC-SHA256 beserta salt acak 16-byte.

  Format keluaran: ``pbkdf2_sha256$<iterations>$<salt_b64>$<digest_b64>``.

  Args:
    password: Kata sandi teks biasa.
    iterations: Jumlah iterasi PBKDF2 (minimal 10.000).

  Returns:
    String hash terenkode aman untuk disimpan di basis data.

  Raises:
    ValidationError: Jika password kosong atau iterations < 10.000.
  """
  if not isinstance(password, str) or not password:
    raise ValidationError("Kata sandi tidak boleh kosong.")
  if iterations < 10_000:
    raise ValidationError("Jumlah iterasi PBKDF2 minimal 10.000.")

  salt = secrets.token_bytes(16)
  digest = hashlib.pbkdf2_hmac(
      "sha256", password.encode("utf-8"), salt, iterations
  )
  salt_b64 = base64.b64encode(salt).decode("ascii")
  digest_b64 = base64.b64encode(digest).decode("ascii")
  return f"pbkdf2_sha256${iterations}${salt_b64}${digest_b64}"


def verify_password(password: str, stored_hash: str) -> bool:
  """Memverifikasi kata sandi terhadap hash tersimpan secara constant-time.

  Args:
    password: Kata sandi kandidat dari pengguna.
    stored_hash: String hash yang tersimpan di basis data.

  Returns:
    True jika cocok, False jika tidak cocok atau format hash rusak.
  """
  if not isinstance(password, str) or not isinstance(stored_hash, str):
    return False
  parts = stored_hash.split("$")
  if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
    return False
  try:
    iterations = int(parts[1])
    salt = base64.b64decode(parts[2].encode("ascii"))
    expected = base64.b64decode(parts[3].encode("ascii"))
  except (ValueError, TypeError):
    return False

  computed = hashlib.pbkdf2_hmac(
      "sha256", password.encode("utf-8"), salt, iterations
  )
  return hmac.compare_digest(computed, expected)


def generate_secure_token(num_bytes: int = 32) -> str:
  """Menghasilkan token acak aman berbasis URL-safe base64.

  Args:
    num_bytes: Panjang entropi dalam byte (minimal 16).

  Returns:
    Token acak URL-safe.

  Raises:
    ValidationError: Jika num_bytes < 16.
  """
  if num_bytes < 16:
    raise ValidationError("Panjang entropi token minimal 16 byte.")
  return secrets.token_urlsafe(num_bytes)


def hash_token(token: str) -> str:
  """Menghasilkan digest SHA-256 heksadesimal untuk menyimpan token sesi/pemulihan.

  Args:
    token: Token mentah.

  Returns:
    Digest SHA-256 dalam format hex lowercase.

  Raises:
    ValidationError: Jika token kosong.
  """
  if not isinstance(token, str) or not token.strip():
    raise ValidationError("Token tidak boleh kosong.")
  return hashlib.sha256(token.encode("utf-8")).hexdigest()
