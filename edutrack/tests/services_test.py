"""Unit & integration test lapisan layanan (termasuk mock clock, impor CSV/XLSX, pindah kelas, backup/restore)."""

from __future__ import annotations

from datetime import datetime, timezone
import io
import tempfile
import unittest
from unittest.mock import MagicMock

import openpyxl

from edutrack.configs.app_config import AppConfig
from edutrack.domain.errors import AuthenticationError, AuthorizationError, ValidationError
from edutrack.domain.models import AccountStatus, AssessmentStatus, AttendanceStatus, Role, User
from edutrack.domain.security import hash_password
from edutrack.services.auth_service import AuthService
from edutrack.web.api import AppContainer


class AuthServiceMockTest(unittest.TestCase):
  """Menguji AuthService terisolasi menggunakan unittest.mock dan jam deterministik."""

  def test_login_and_deactivated_rejection_with_mock_repo(self) -> None:
    cfg = AppConfig(db_path=":memory:", pbkdf2_iterations=12_000, session_ttl_hours=2)
    repo = MagicMock()
    fixed_now = datetime(2026, 11, 19, 8, 0, 0, tzinfo=timezone.utc)
    service = AuthService(repo, cfg, clock=lambda: fixed_now)

    active_user = User(
        id=1, username="guru1", full_name="Guru Satu", role=Role.TEACHER,
        status=AccountStatus.ACTIVE, must_change_password=False, email=None, created_at="2026-11-19"
    )
    repo.get_auth_record_by_username.return_value = {
        "user": active_user,
        "password_hash": hash_password("SandiAman123", iterations=12_000),
    }

    res = service.login("guru1", "SandiAman123")
    self.assertEqual(res["user"].id, 1)
    self.assertEqual(res["expires_at"], "2026-11-19T10:00:00+00:00")
    repo.create_session.assert_called_once()

    # Akun dinonaktifkan harus ditolak
    deactivated = User(
        id=2, username="siswa_off", full_name="Siswa Off", role=Role.STUDENT,
        status=AccountStatus.DEACTIVATED, must_change_password=False, email=None, created_at="2026-11-19"
    )
    repo.get_auth_record_by_username.return_value = {
        "user": deactivated,
        "password_hash": hash_password("SandiAman123", iterations=12_000),
    }
    with self.assertRaises(AuthenticationError):
      service.login("siswa_off", "SandiAman123")

  def test_require_role_raises_authorization_error(self) -> None:
    student = User(
        id=3, username="s1", full_name="Siswa", role=Role.STUDENT,
        status=AccountStatus.ACTIVE, must_change_password=False, email=None, created_at="2026-11-19"
    )
    with self.assertRaises(AuthorizationError):
      AuthService.require_role(student, Role.TEACHER)


class ServicesIntegrationTest(unittest.TestCase):
  """Menguji impor CSV/Excel, pindah kelas preservasi riwayat, dan backup/restore SQLite."""

  def setUp(self) -> None:
    self._tmpdir = tempfile.TemporaryDirectory()
    db_path = f"{self._tmpdir.name}/test_edutrack.db"
    backup_dir = f"{self._tmpdir.name}/backups"
    self.config = AppConfig(
        db_path=db_path, backup_dir=backup_dir, pbkdf2_iterations=12_000
    )
    self.container = AppContainer(self.config)
    self.teacher = self.container.auth_service.register_teacher(
        "guru_uji", "GuruUji123!", "Ibu Siti"
    )
    self.period = self.container.classroom_service.create_period(
        self.teacher, "Ganjil 2026/2027", "2026/2027", "Ganjil"
    )
    self.cls1 = self.container.classroom_service.create_classroom(
        self.teacher, self.period.id, "X-A", "SMA X"
    )
    self.cls2 = self.container.classroom_service.create_classroom(
        self.teacher, self.period.id, "X-B", "SMA X"
    )

  def tearDown(self) -> None:
    self._tmpdir.cleanup()

  def test_csv_and_excel_student_import(self) -> None:
    csv_bytes = "nama,nis,catatan\nRina Wati,NIS001,Aktif\nBudi Jaya,NIS002,\n".encode("utf-8")
    res_csv = self.container.student_service.import_students(
        self.teacher, self.cls1.id, "siswa.csv", csv_bytes
    )
    self.assertEqual(res_csv["imported_count"], 2)
    self.assertEqual(res_csv["failed_count"], 0)

    # Uji impor Excel (.xlsx) dengan 1 valid & 1 duplikat NIS
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["nama_lengkap", "nomor_induk"])
    ws.append(["Sari Dewi", "NIS003"])
    ws.append(["Duplikat Rina", "NIS001"])
    buf = io.BytesIO()
    wb.save(buf)

    res_xlsx = self.container.student_service.import_students(
        self.teacher, self.cls1.id, "siswa.xlsx", buf.getvalue()
    )
    self.assertEqual(res_xlsx["imported_count"], 1)
    self.assertEqual(res_xlsx["failed_count"], 1)

    with self.assertRaises(ValidationError):
      self.container.student_service.import_students(
          self.teacher, self.cls1.id, "invalid.txt", b"hello"
      )

  def test_move_student_preserves_previous_grade_and_attendance_history(self) -> None:
    created = self.container.student_service.create_student_with_account(
        self.teacher, self.cls1.id, "Andi Saputra", "NIS100", account_status=AccountStatus.ACTIVE
    )
    stu = created["student"]
    asmt = self.container.grade_service.create_assessment(
        self.teacher, self.cls1.id, "Kuis 1", "Kuis", "2026-09-01", status=AssessmentStatus.PUBLISHED
    )
    self.container.grade_service.save_grades_bulk(
        self.teacher, asmt.id, [{"student_id": stu.id, "score": 88.0, "feedback": "Bagus"}]
    )
    sess = self.container.attendance_service.create_session(
        self.teacher, self.cls1.id, "2026-09-01", 1, mark_all_present=True
    )
    self.assertEqual(len(sess["records"]), 1)

    # Pindahkan ke kelas X-B
    moved = self.container.student_service.move_student(self.teacher, stu.id, self.cls2.id)
    self.assertEqual(moved.current_class_id, self.cls2.id)

    # Pastikan riwayat nilai & kehadiran di kelas X-A tetap tersimpan!
    stu_user = self.container.user_repo.get_by_id(stu.user_id)
    assert stu_user is not None
    dash = self.container.analytics_service.get_student_dashboard(stu_user)
    self.assertEqual(len(dash["enrollments"]), 2)
    self.assertEqual(len(dash["grade_timeline"]), 1)
    self.assertAlmostEqual(dash["grade_timeline"][0]["raw_score"], 88.0)
    self.assertEqual(dash["attendance_summary"]["hadir"], 1)

  def test_database_backup_and_restore(self) -> None:
    bak_name = self.container.db.create_backup("sebelum_ubah")
    backups = self.container.db.list_backups()
    self.assertTrue(any(b["filename"] == bak_name for b in backups))

    # Tambah kelas baru lalu restore ke snapshot sebelum kelas baru
    self.container.classroom_service.create_classroom(
        self.teacher, self.period.id, "X-C", "SMA X"
    )
    self.assertEqual(len(self.container.classroom_service.list_classrooms(self.teacher)), 3)

    self.container.db.restore_backup(bak_name)
    self.assertEqual(len(self.container.classroom_service.list_classrooms(self.teacher)), 2)


if __name__ == "__main__":
  unittest.main()
