"""Logika domain murni untuk rekapitulasi dan analisis kehadiran.

Aturan invarian penting:
- Persentase kehadiran dihitung berdasarkan jumlah pertemuan yang benar-benar
  tercatat, bukan perkiraan jumlah hari kalender.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from edutrack.domain.errors import ValidationError
from edutrack.domain.models import AttendanceStatus


@dataclass(frozen=True)
class AttendanceSummary:
  """Ringkasan rekapitulasi kehadiran peserta didik atau kelas."""

  total_recorded: int
  hadir: int
  sakit: int
  izin: int
  alpa: int
  attendance_percentage: float | None
  absence_percentage: float | None
  needs_attention: bool


def summarize_attendance(
    statuses: Sequence[AttendanceStatus | str],
    high_absence_threshold_pct: float = 20.0,
) -> AttendanceSummary:
  """Menghitung jumlah status dan persentase kehadiran dari catatan pertemuan.

  Args:
    statuses: Daftar status kehadiran yang benar-benar tercatat.
    high_absence_threshold_pct: Ambang persentase ketidakhadiran (sakit+izin+alpa)
      yang menandai perlunya tindak lanjut guru (0..100).

  Returns:
    AttendanceSummary berisi hitungan tiap status, persentase kehadiran, dan
    indikator kebutuhan perhatian.

  Raises:
    ValidationError: Jika terdapat status tidak dikenal atau ambang di luar
      rentang [0, 100].
  """
  if not (0.0 <= high_absence_threshold_pct <= 100.0):
    raise ValidationError(
        "Ambang persentase ketidakhadiran harus antara 0 dan 100."
    )

  counts = {
      AttendanceStatus.HADIR: 0,
      AttendanceStatus.SAKIT: 0,
      AttendanceStatus.IZIN: 0,
      AttendanceStatus.ALPA: 0,
  }

  for raw in statuses:
    try:
      st = (
          raw
          if isinstance(raw, AttendanceStatus)
          else AttendanceStatus(str(raw).lower().strip())
      )
    except ValueError as exc:
      raise ValidationError(f"Status kehadiran tidak valid: '{raw}'.") from exc
    counts[st] += 1

  total = len(statuses)
  if total == 0:
    return AttendanceSummary(
        total_recorded=0,
        hadir=0,
        sakit=0,
        izin=0,
        alpa=0,
        attendance_percentage=None,
        absence_percentage=None,
        needs_attention=False,
    )

  hadir = counts[AttendanceStatus.HADIR]
  absent = total - hadir
  att_pct = round((hadir / total) * 100.0, 2)
  abs_pct = round((absent / total) * 100.0, 2)

  return AttendanceSummary(
      total_recorded=total,
      hadir=hadir,
      sakit=counts[AttendanceStatus.SAKIT],
      izin=counts[AttendanceStatus.IZIN],
      alpa=counts[AttendanceStatus.ALPA],
      attendance_percentage=att_pct,
      absence_percentage=abs_pct,
      needs_attention=abs_pct >= high_absence_threshold_pct,
  )
