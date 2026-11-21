"""Unit test untuk modul domain/grading.py (happy path, edge/empty, error)."""

from __future__ import annotations

import unittest

from edutrack.domain.errors import ValidationError
from edutrack.domain.grading import (
    WeightedScoreItem,
    compute_class_statistics,
    compute_final_score,
    compute_learning_trend,
    normalize_score,
)
from edutrack.domain.models import CalculationMode


class GradingDomainTest(unittest.TestCase):
  """Menguji perhitungan nilai, statistik kelas, dan indikasi tren belajar."""

  # --- Happy Path ---

  def test_weighted_final_score_happy_path(self) -> None:
    items = [
        WeightedScoreItem(score=80.0, max_score=100.0, weight=20.0),
        WeightedScoreItem(score=90.0, max_score=100.0, weight=30.0),
        WeightedScoreItem(score=45.0, max_score=50.0, weight=50.0),  # norm = 90.0
    ]
    # (80*20 + 90*30 + 90*50) / 100 = 88.0
    result = compute_final_score(items, mode=CalculationMode.WEIGHTED)
    self.assertIsNotNone(result)
    self.assertAlmostEqual(result, 88.0, places=2)

  def test_unweighted_final_score_happy_path(self) -> None:
    items = [
        WeightedScoreItem(score=70.0, max_score=100.0, weight=10.0),
        WeightedScoreItem(score=90.0, max_score=100.0, weight=90.0),
    ]
    result = compute_final_score(items, mode=CalculationMode.UNWEIGHTED)
    self.assertAlmostEqual(result, 80.0, places=2)

  def test_class_statistics_and_distribution_happy_path(self) -> None:
    stats = compute_class_statistics([95.0, 82.0, 75.0, 65.0, 50.0, None], mastery_threshold=75.0)
    self.assertEqual(stats.total_students, 6)
    self.assertEqual(stats.graded_count, 5)
    self.assertAlmostEqual(stats.average, 73.4, places=2)
    self.assertAlmostEqual(stats.highest, 95.0, places=2)
    self.assertAlmostEqual(stats.lowest, 50.0, places=2)
    self.assertAlmostEqual(stats.median_score, 75.0, places=2)
    self.assertEqual(stats.mastery_count, 3)
    self.assertAlmostEqual(stats.mastery_percentage, 60.0, places=2)
    self.assertEqual(stats.distribution, {"90-100": 1, "80-89": 1, "70-79": 1, "60-69": 1, "<60": 1})

  def test_learning_trend_indicators(self) -> None:
    up = compute_learning_trend([70.0, 74.0, 82.0, 88.0])
    self.assertEqual(up["indicator"], "Meningkat")
    self.assertAlmostEqual(up["delta"], 13.0, places=2)

    down = compute_learning_trend([90.0, 88.0, 75.0, 70.0])
    self.assertEqual(down["indicator"], "Menurun")

    flat = compute_learning_trend([80.0, 81.0, 80.5, 81.5])
    self.assertEqual(flat["indicator"], "Stabil")

  # --- Edge / Empty Cases ---

  def test_none_is_distinguished_from_zero(self) -> None:
    # Nilai None diabaikan, sedangkan nilai 0.0 tetap dihitung!
    with_none = compute_final_score([
        WeightedScoreItem(score=80.0, max_score=100.0, weight=50.0),
        WeightedScoreItem(score=None, max_score=100.0, weight=50.0),
    ])
    with_zero = compute_final_score([
        WeightedScoreItem(score=80.0, max_score=100.0, weight=50.0),
        WeightedScoreItem(score=0.0, max_score=100.0, weight=50.0),
    ])
    self.assertAlmostEqual(with_none, 80.0, places=2)
    self.assertAlmostEqual(with_zero, 40.0, places=2)

  def test_empty_and_all_none_scores(self) -> None:
    self.assertIsNone(compute_final_score([]))
    self.assertIsNone(compute_final_score([WeightedScoreItem(score=None)]))
    stats = compute_class_statistics([None, None])
    self.assertEqual(stats.graded_count, 0)
    self.assertIsNone(stats.average)
    self.assertIsNone(stats.mastery_percentage)
    trend = compute_learning_trend([80.0, None])
    self.assertEqual(trend["indicator"], "Data Belum Cukup")
    self.assertIsNone(trend["delta"])

  def test_zero_weights_fallback_to_simple_average(self) -> None:
    res = compute_final_score([
        WeightedScoreItem(score=60.0, max_score=100.0, weight=0.0),
        WeightedScoreItem(score=80.0, max_score=100.0, weight=0.0),
    ])
    self.assertAlmostEqual(res, 70.0, places=2)

  # --- Error / Invalid Cases ---

  def test_invalid_inputs_raise_validation_error(self) -> None:
    with self.assertRaises(ValidationError):
      normalize_score(105.0, 100.0)
    with self.assertRaises(ValidationError):
      normalize_score(-1.0, 100.0)
    with self.assertRaises(ValidationError):
      normalize_score(50.0, 0.0)
    with self.assertRaises(ValidationError):
      compute_final_score([WeightedScoreItem(score=80.0, weight=-5.0)])
    with self.assertRaises(ValidationError):
      compute_class_statistics([80.0], mastery_threshold=120.0)
    with self.assertRaises(ValidationError):
      compute_learning_trend([80.0, 85.0], stability_band=-1.0)


if __name__ == "__main__":
  unittest.main()
