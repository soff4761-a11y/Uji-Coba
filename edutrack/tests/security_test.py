"""Unit test untuk modul domain/security.py (happy path, edge/empty, error)."""

from __future__ import annotations

import unittest

from edutrack.domain.errors import ValidationError
from edutrack.domain.security import (
    generate_secure_token,
    hash_password,
    hash_token,
    validate_password_strength,
    verify_password,
)


class SecurityDomainTest(unittest.TestCase):
  """Menguji hashing PBKDF2, verifikasi sandi, dan pembuatan token aman."""

  def test_hash_and_verify_password_happy_path(self) -> None:
    h1 = hash_password("Rahasia123!", iterations=15_000)
    h2 = hash_password("Rahasia123!", iterations=15_000)
    self.assertNotEqual(h1, h2)  # Salt acak harus berbeda
    self.assertTrue(verify_password("Rahasia123!", h1))
    self.assertFalse(verify_password("Salah123!", h1))

  def test_verify_malformed_hash_edge_case(self) -> None:
    self.assertFalse(verify_password("Rahasia123!", "plain_text_not_hash"))
    self.assertFalse(verify_password("Rahasia123!", "pbkdf2_sha256$abc$salt$digest"))
    self.assertFalse(verify_password("", ""))

  def test_token_generation_and_hashing(self) -> None:
    t1 = generate_secure_token(32)
    t2 = generate_secure_token(32)
    self.assertNotEqual(t1, t2)
    self.assertEqual(len(hash_token(t1)), 64)

  def test_invalid_security_parameters(self) -> None:
    with self.assertRaises(ValidationError):
      validate_password_strength("pendek")
    with self.assertRaises(ValidationError):
      validate_password_strength(" spasi1234 ")
    with self.assertRaises(ValidationError):
      hash_password("", iterations=15_000)
    with self.assertRaises(ValidationError):
      hash_password("Rahasia123!", iterations=500)
    with self.assertRaises(ValidationError):
      generate_secure_token(8)
    with self.assertRaises(ValidationError):
      hash_token("   ")


if __name__ == "__main__":
  unittest.main()
