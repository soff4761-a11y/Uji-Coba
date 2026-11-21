"""Unit test untuk modul domain/attendance_calc.py (happy path, edge/empty, error)."""

from __future__ import annotations

import unittest

from edutrack.domain.attendance_calc import summarize_attendance
from edutrack.domain.errors import ValidationError
from edutrack.domain.models import AttendanceStatus


class AttendanceCalcTest(unittest.TestCase):
  """Menguji perhitungan rekapitulasi kehadiran berbasis pertemuan tercatat."""

  def test_summarize_attendance_happy_path(self) -> None:
    statuses = [
        AttendanceStatus.HADIR,
        AttendanceStatus.HADIR,
        AttendanceStatus.HADIR,
        AttendanceStatus.SAKIT,
        AttendanceStatus.ALPA,
    ]
    summary = summarize_attendance(statuses, high_absence_threshold_pct=20.0)
    self.assertEqual(summary.total_recorded, 5)
    self.assertEqual(summary.hadir, 3)
    self.assertEqual(summary.sakit, 1)
    self.assertEqual(summary.izin, 0)
    self.assertEqual(summary.alpa, 1)
    self.assertAlmostEqual(summary.attendance_percentage, 60.0, places=2)
    self.assertAlmostEqual(summary.absence_percentage, 40.0, places=2)
    self.assertTrue(summary.needs_attention)

  def test_summarize_attendance_empty_edge_case(self) -> None:
    summary = summarize_attendance([])
    self.assertEqual(summary.total_recorded, 0)
    self.assertIsNone(summary.attendance_percentage)
    self.assertIsNone(summary.absence_percentage)
    self.assertFalse(summary.needs_attention)

  def test_summarize_attendance_all_present_boundary(self) -> None:
    summary = summarize_attendance(["hadir", "hadir", "hadir"], high_absence_threshold_pct=20.0)
    self.assertAlmostEqual(summary.attendance_percentage, 100.0, places=2)
    self.assertAlmostEqual(summary.absence_percentage, 0.0, places=2)
    self.assertFalse(summary.needs_attention)

  def test_summarize_attendance_invalid_inputs(self) -> None:
    with self.assertRaises(ValidationError):
      summarize_attendance(["hadir", "bolos"])
    with self.assertRaises(ValidationError):
      summarize_attendance(["hadir"], high_absence_threshold_pct=-5.0)
    with self.assertRaises(ValidationError):
      summarize_attendance(["hadir"], high_absence_threshold_pct=150.0)


if __name__ == "__main__":
  unittest.main()
