"""Logika domain murni untuk perhitungan nilai, statistik kelas, dan tren belajar.

Aturan invarian penting:
1. Nilai None (belum diinput) dibedakan secara tegas dari nilai 0.0 dan TIDAK
   dihitung sebagai nol dalam rata-rata maupun nilai akhir.
2. Indikasi tren bersifat objektif dan deskriptif (Meningkat, Stabil, Menurun,
   Data Belum Cukup) tanpa melabeli kecerdasan atau karakter peserta didik.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Dict, List, Optional, Sequence

from edutrack.domain.errors import ValidationError
from edutrack.domain.models import CalculationMode


@dataclass(frozen=True)
class WeightedScoreItem:
  """Item nilai untuk perhitungan rata-rata atau nilai akhir berbobot.

  Attributes:
    score: Nilai mentah peserta didik, atau None jika belum diinput.
    max_score: Nilai maksimum komponen penilaian (> 0).
    weight: Bobot komponen penilaian (>= 0).
  """

  score: Optional[float]
  max_score: float = 100.0
  weight: float = 1.0


@dataclass(frozen=True)
class ClassStatistics:
  """Ringkasan statistik capaian kelas."""

  graded_count: int
  total_students: int
  average: Optional[float]
  highest: Optional[float]
  lowest: Optional[float]
  median_score: Optional[float]
  mastery_count: int
  mastery_percentage: Optional[float]
  distribution: Dict[str, int]


def normalize_score(score: float, max_score: float) -> float:
  """Menormalisasi nilai ke skala 0..100.

  Args:
    score: Nilai mentah peserta didik.
    max_score: Rentang nilai maksimum komponen (> 0).

  Returns:
    Nilai pada skala 0..100.

  Raises:
    ValidationError: Jika max_score <= 0 atau score di luar [0, max_score].
  """
  if max_score <= 0:
    raise ValidationError("Rentang nilai maksimum (max_score) harus > 0.")
  if score < 0 or score > max_score:
    raise ValidationError(
        f"Nilai ({score}) harus berada dalam rentang 0 hingga {max_score}."
    )
  return (score / max_score) * 100.0


def compute_final_score(
    items: Sequence[WeightedScoreItem],
    mode: CalculationMode = CalculationMode.WEIGHTED,
) -> Optional[float]:
  """Menghitung nilai akhir peserta didik secara otomatis.

  Nilai None (belum diinput) diabaikan sepenuhnya sehingga tidak dianggap 0.

  Args:
    items: Urutan komponen nilai peserta didik.
    mode: Metode perhitungan (WEIGHTED atau UNWEIGHTED).

  Returns:
    Nilai akhir terstandardisasi skala 0..100 dibulatkan 2 desimal, atau None
    apabila belum ada satu pun nilai yang diinput.

  Raises:
    ValidationError: Jika ada item dengan bobot negatif, max_score <= 0, atau
      score di luar rentang valid.
  """
  graded: List[tuple[float, float]] = []
  for item in items:
    if item.weight < 0:
      raise ValidationError("Bobot komponen penilaian tidak boleh negatif.")
    if item.max_score <= 0:
      raise ValidationError("Rentang nilai maksimum harus > 0.")
    if item.score is None:
      continue
    norm = normalize_score(item.score, item.max_score)
    graded.append((norm, item.weight))

  if not graded:
    return None

  if mode == CalculationMode.UNWEIGHTED:
    return round(sum(s for s, _ in graded) / len(graded), 2)

  total_weight = sum(w for _, w in graded)
  if total_weight <= 0:
    # Fallback ke rata-rata sederhana apabila semua bobot komponen bernilai 0.
    return round(sum(s for s, _ in graded) / len(graded), 2)

  weighted_sum = sum(s * w for s, w in graded)
  return round(weighted_sum / total_weight, 2)


def compute_class_statistics(
    scores: Sequence[Optional[float]],
    mastery_threshold: float = 75.0,
) -> ClassStatistics:
  """Menghitung statistik kelas lengkap dan distribusi nilai.

  Args:
    scores: Daftar nilai akhir (skala 0..100) per peserta didik; None untuk yang
      belum memiliki nilai.
    mastery_threshold: Batas kriteria ketuntasan (0..100).

  Returns:
    Objek ClassStatistics dengan rata-rata, tertinggi, terendah, median,
    distribusi rentang nilai, dan persentase ketuntasan.

  Raises:
    ValidationError: Jika mastery_threshold di luar [0, 100] atau ada nilai
      non-None di luar [0, 100].
  """
  if not (0.0 <= mastery_threshold <= 100.0):
    raise ValidationError("Kriteria ketuntasan harus antara 0 dan 100.")

  distribution: Dict[str, int] = {
      "90-100": 0,
      "80-89": 0,
      "70-79": 0,
      "60-69": 0,
      "<60": 0,
  }

  valid_scores: List[float] = []
  for sc in scores:
    if sc is None:
      continue
    if sc < 0.0 or sc > 100.0:
      raise ValidationError(f"Nilai statistik ({sc}) harus antara 0 dan 100.")
    valid_scores.append(float(sc))
    if sc >= 90.0:
      distribution["90-100"] += 1
    elif sc >= 80.0:
      distribution["80-89"] += 1
    elif sc >= 70.0:
      distribution["70-79"] += 1
    elif sc >= 60.0:
      distribution["60-69"] += 1
    else:
      distribution["<60"] += 1

  total_students = len(scores)
  if not valid_scores:
    return ClassStatistics(
        graded_count=0,
        total_students=total_students,
        average=None,
        highest=None,
        lowest=None,
        median_score=None,
        mastery_count=0,
        mastery_percentage=None,
        distribution=distribution,
    )

  mastery_count = sum(1 for sc in valid_scores if sc >= mastery_threshold)
  avg = round(sum(valid_scores) / len(valid_scores), 2)
  med = round(float(median(valid_scores)), 2)
  mastery_pct = round((mastery_count / len(valid_scores)) * 100.0, 2)

  return ClassStatistics(
      graded_count=len(valid_scores),
      total_students=total_students,
      average=avg,
      highest=round(max(valid_scores), 2),
      lowest=round(min(valid_scores), 2),
      median_score=med,
      mastery_count=mastery_count,
      mastery_percentage=mastery_pct,
      distribution=distribution,
  )


def compute_learning_trend(
    chronological_scores: Sequence[Optional[float]],
    stability_band: float = 2.0,
) -> Dict[str, Optional[float] | str]:
  """Menganalisis indikasi tren perkembangan nilai secara objektif.

  Membandingkan rata-rata paruh awal dan paruh akhir rangkaian nilai
  kronologis (atau dua nilai terakhir jika hanya ada 2 data).

  Args:
    chronological_scores: Nilai terurut waktu; nilai None diabaikan.
    stability_band: Ambang selisih poin untuk dikategorikan Stabil (>= 0).

  Returns:
    Dictionary berisi ``indicator`` ('Meningkat', 'Menurun', 'Stabil', atau
    'Data Belum Cukup') dan ``delta`` (selisih poin atau None).

  Raises:
    ValidationError: Jika stability_band < 0.
  """
  if stability_band < 0:
    raise ValidationError("stability_band tidak boleh negatif.")

  values = [float(s) for s in chronological_scores if s is not None]
  if len(values) < 2:
    return {"indicator": "Data Belum Cukup", "delta": None}

  mid = len(values) // 2
  first_half_avg = sum(values[:mid]) / mid
  second_half_avg = sum(values[mid:]) / (len(values) - mid)
  delta = round(second_half_avg - first_half_avg, 2)

  if delta > stability_band:
    indicator = "Meningkat"
  elif delta < -stability_band:
    indicator = "Menurun"
  else:
    indicator = "Stabil"

  return {"indicator": indicator, "delta": delta}
