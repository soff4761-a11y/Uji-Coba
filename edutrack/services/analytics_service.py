"""Layanan analitik dan visualisasi perkembangan nilai serta rekapitulasi kehadiran."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import math
from typing import Any, Dict, List, Optional, Sequence

from edutrack.configs.app_config import AppConfig
from edutrack.domain.attendance_calc import summarize_attendance
from edutrack.domain.errors import AuthorizationError, NotFoundError, ValidationError
from edutrack.domain.grading import (
    WeightedScoreItem,
    compute_class_statistics,
    compute_final_score,
    compute_learning_trend,
    normalize_score,
)
from edutrack.domain.models import AssessmentStatus, Role, SURPRISE_REVEAL_CATEGORIES, User
from edutrack.repositories.academic_repo import AcademicRepository
from edutrack.repositories.attendance_repo import AttendanceRepository
from edutrack.repositories.grade_repo import GradeRepository
from edutrack.services.auth_service import AuthService


def _bucket_date(date_str: str, granularity: str) -> str:
  """Mengelompokkan tanggal YYYY-MM-DD ke bucket harian/mingguan/bulanan/tahunan."""
  if granularity == "daily":
    return date_str
  if granularity == "monthly":
    return date_str[:7]
  if granularity == "yearly":
    return date_str[:4]
  if granularity == "weekly":
    try:
      dt = datetime.strptime(date_str, "%Y-%m-%d")
      iso_year, iso_week, _ = dt.isocalendar()
      return f"{iso_year}-W{iso_week:02d}"
    except ValueError:
      return date_str[:7]
  return date_str[:7]


def evaluate_student_ews(
    final_score: Optional[float],
    mastery_threshold: float,
    alpa_count: int,
    alpa_threshold: int,
    unsubmitted_checklist_count: int = 0,
    unsubmitted_checklist_threshold: int = 3,
) -> Dict[str, Any]:
  """Mengevaluasi status Early Warning System (EWS) seorang peserta didik.

  Args:
    final_score: Nilai akhir skala 0..100 atau None jika belum ada nilai.
    mastery_threshold: Ambang ketuntasan (KKM) kelas pada rentang 0..100.
    alpa_count: Jumlah ketidakhadiran tanpa keterangan (>= 0).
    alpa_threshold: Ambang jumlah alpa pemicu EWS (>= 1).

  Returns:
    Dictionary berisi ``is_triggered``, ``severity`` ('kritis'|'perhatian'|'aman'),
    ``title``, ``kkm``, ``alpa_threshold``, ``final_score``, ``alpa_count``,
    ``triggers``, ``reasons``, dan ``message``.

  Raises:
    ValidationError: Jika parameter berada di luar rentang valid atau non-finite.
  """
  if not math.isfinite(mastery_threshold) or not (0.0 <= mastery_threshold <= 100.0):
    raise ValidationError("mastery_threshold harus berupa angka valid antara 0 dan 100.")
  if final_score is not None and (
      not math.isfinite(final_score) or not (0.0 <= final_score <= 100.0)
  ):
    raise ValidationError("final_score harus berupa angka valid antara 0 dan 100.")
  if alpa_count < 0:
    raise ValidationError("alpa_count tidak boleh negatif.")
  if alpa_threshold < 1:
    raise ValidationError("alpa_threshold minimal 1.")
  if unsubmitted_checklist_count < 0:
    raise ValidationError("unsubmitted_checklist_count tidak boleh negatif.")
  if unsubmitted_checklist_threshold < 1:
    raise ValidationError("unsubmitted_checklist_threshold minimal 1.")

  below_kkm = final_score is not None and float(final_score) < float(mastery_threshold)
  alpa_over = int(alpa_count) >= int(alpa_threshold)
  checklist_over = int(unsubmitted_checklist_count) >= int(unsubmitted_checklist_threshold)
  is_triggered = below_kkm or alpa_over or checklist_over

  triggers: List[str] = []
  reasons: List[str] = []
  if below_kkm:
    triggers.append("below_kkm")
    reasons.append(f"Nilai akhir ({final_score}) di bawah KKM ({mastery_threshold})")
  if alpa_over:
    triggers.append("alpa_exceeded")
    reasons.append(
        f"Jumlah alpa ({alpa_count}x) mencapai/melewati batas ({alpa_threshold}x)"
    )
  if checklist_over:
    triggers.append("unsubmitted_checklist")
    reasons.append(
        f"Belum mengumpulkan {int(unsubmitted_checklist_count)} tugas pengumpulan "
        f"(batas peringatan: {int(unsubmitted_checklist_threshold)} tugas)"
    )

  if len(triggers) >= 2:
    severity = "kritis"
    title = "Peringatan Kritis (EWS)"
  elif is_triggered:
    severity = "perhatian"
    title = "Peringatan Dini (EWS)"
  else:
    severity = "aman"
    title = ""

  message = (
      f"Status akademik melewati batas EWS: {'; '.join(reasons)}."
      if is_triggered
      else ""
  )
  return {
      "is_triggered": is_triggered,
      "severity": severity,
      "title": title,
      "kkm": float(mastery_threshold),
      "alpa_threshold": int(alpa_threshold),
      "unsubmitted_checklist_threshold": int(unsubmitted_checklist_threshold),
      "final_score": final_score,
      "alpa_count": int(alpa_count),
      "unsubmitted_checklist_count": int(unsubmitted_checklist_count),
      "triggers": triggers,
      "reasons": reasons,
      "message": message,
  }


class AnalyticsService:
  """Mengolah data nilai & kehadiran menjadi data dashboard dan grafik."""

  def __init__(
      self,
      academic_repo: AcademicRepository,
      grade_repo: GradeRepository,
      attendance_repo: AttendanceRepository,
      config: AppConfig,
      attendance_service: Optional[Any] = None,
  ) -> None:
    self._academic_repo = academic_repo
    self._grade_repo = grade_repo
    self._attendance_repo = attendance_repo
    self._config = config
    self._attendance_service = attendance_service

  def get_teacher_dashboard(
      self,
      teacher: User,
      period_id: Optional[int] = None,
      class_id: Optional[int] = None,
  ) -> Dict[str, Any]:
    """Menyusun ringkasan dashboard guru yang dinamis terhadap pilihan kelas & periode."""
    AuthService.require_role(teacher, Role.TEACHER)
    periods = self._academic_repo.list_periods(teacher.id, include_archived=True)
    if period_id is None and periods:
      active = next((p for p in periods if p.is_active), periods[0])
      period_id = active.id

    classes = self._academic_repo.list_classrooms(
        teacher.id, period_id=period_id, include_archived=False
    )
    selected_classes = classes
    if class_id is not None:
      cls = self._academic_repo.get_classroom(class_id)
      if not cls:
        raise NotFoundError("Kelas tidak ditemukan.")
      if cls.teacher_id != teacher.id:
        raise AuthorizationError("Anda tidak berwenang melihat analitik kelas guru lain.")
      selected_classes = [cls]

    all_students = []
    all_final_scores: List[Optional[float]] = []
    all_att_statuses: List[str] = []
    attention_students: List[Dict[str, Any]] = []
    ews_candidates: List[Dict[str, Any]] = []
    per_class_mastery_count = 0
    category_scores: Dict[str, List[float]] = defaultdict(list)
    category_asmt_ids: Dict[str, set] = defaultdict(set)

    for cls in selected_classes:
      students = self._academic_repo.list_students(teacher.id, class_id=cls.id)
      all_students.extend(students)
      assessments = self._grade_repo.list_assessments(cls.id, published_only=False)
      grades = self._grade_repo.list_grades_for_class(cls.id)
      att_records = self._attendance_repo.list_records_for_class(cls.id)

      grade_map = {(int(g["student_id"]), int(g["assessment_id"])): g for g in grades}
      att_by_stu: Dict[int, List[str]] = defaultdict(list)
      for rec in att_records:
        att_by_stu[int(rec["student_id"])].append(str(rec["status"]))
        all_att_statuses.append(str(rec["status"]))

      # Rata-rata antarkomponen dikelompokkan per kategori penilaian bernilai
      for asmt in assessments:
        if not asmt.is_graded:
          continue
        cat_label = (asmt.category or "Lainnya").strip() or "Lainnya"
        category_asmt_ids[cat_label].add(asmt.id)
        for stu in students:
          g = grade_map.get((stu.id, asmt.id))
          if g and g["score"] is not None:
            category_scores[cat_label].append(
                normalize_score(float(g["score"]), asmt.max_score)
            )

      sorted_assessments = sorted(
          assessments, key=lambda a: (a.assessment_date, a.id)
      )
      published_checklists = [
          a for a in sorted_assessments
          if a.status == AssessmentStatus.PUBLISHED and not a.is_graded
      ]
      for stu in students:
        items = []
        chrono_scores: List[Optional[float]] = []
        for asmt in sorted_assessments:
          if not asmt.is_graded:
            continue
          g = grade_map.get((stu.id, asmt.id))
          sc = g["score"] if g else None
          items.append(
              WeightedScoreItem(score=sc, max_score=asmt.max_score, weight=asmt.weight)
          )
          if sc is not None:
            chrono_scores.append(normalize_score(float(sc), asmt.max_score))

        unsubmitted_cnt = sum(
            1
            for chk in published_checklists
            if (
                grade_map.get((stu.id, chk.id)) is None
                or grade_map[(stu.id, chk.id)]["score"] is None
                or float(grade_map[(stu.id, chk.id)]["score"]) < 1.0
            )
        )

        final_sc = compute_final_score(items, mode=cls.calculation_mode)
        all_final_scores.append(final_sc)
        if final_sc is not None and final_sc >= cls.mastery_threshold:
          per_class_mastery_count += 1
        att_sum = summarize_attendance(
            att_by_stu.get(stu.id, []),
            high_absence_threshold_pct=self._config.high_absence_threshold_pct,
        )
        trend = compute_learning_trend(chrono_scores)

        ews_candidates.append({
            "student_id": stu.id,
            "student_code": stu.student_code,
            "full_name": stu.full_name,
            "class_id": cls.id,
            "class_name": cls.name,
            "kkm": cls.mastery_threshold,
            "final_score": final_sc,
            "attendance_percentage": att_sum.attendance_percentage,
            "alpa_count": att_sum.alpa,
            "unsubmitted_checklist_count": unsubmitted_cnt,
        })

        reasons: List[str] = []
        if final_sc is not None and final_sc < cls.mastery_threshold:
          reasons.append(f"Nilai akhir ({final_sc}) di bawah KKM ({cls.mastery_threshold})")
        if att_sum.needs_attention:
          reasons.append(f"Ketidakhadiran tinggi ({att_sum.absence_percentage}%)")
        if trend["indicator"] == "Menurun":
          reasons.append(f"Tren nilai menurun ({trend['delta']} poin)")

        if reasons:
          attention_students.append({
              "student_id": stu.id,
              "student_code": stu.student_code,
              "full_name": stu.full_name,
              "class_id": cls.id,
              "class_name": cls.name,
              "kkm": cls.mastery_threshold,
              "final_score": final_sc,
              "attendance_percentage": att_sum.attendance_percentage,
              "alpa_count": att_sum.alpa,
              "trend": trend["indicator"],
              "reasons": reasons,
          })

    mastery_threshold = (
        selected_classes[0].mastery_threshold
        if len(selected_classes) == 1
        else self._config.default_mastery_threshold
    )
    grade_stats = compute_class_statistics(
        all_final_scores, mastery_threshold=mastery_threshold
    )
    per_class_mastery_pct = (
        round((per_class_mastery_count / grade_stats.graded_count) * 100.0, 2)
        if grade_stats.graded_count > 0
        else None
    )
    att_overall = summarize_attendance(
        all_att_statuses,
        high_absence_threshold_pct=self._config.high_absence_threshold_pct,
    )
    pending_corrections = self._attendance_repo.list_correction_requests_for_teacher(
        teacher.id
    )
    pending_count = sum(1 for c in pending_corrections if c["status"] == "pending")

    return {
        "selected_period_id": period_id,
        "selected_class_id": class_id,
        "total_classes": len(classes),
        "total_students": len(all_students),
        "pending_corrections": pending_count,
        "grade_statistics": {
            "graded_count": grade_stats.graded_count,
            "total_students": grade_stats.total_students,
            "average": grade_stats.average,
            "highest": grade_stats.highest,
            "lowest": grade_stats.lowest,
            "median_score": grade_stats.median_score,
            "mastery_count": per_class_mastery_count,
            "mastery_percentage": per_class_mastery_pct,
            "distribution": grade_stats.distribution,
        },
        "attendance_summary": {
            "total_recorded": att_overall.total_recorded,
            "hadir": att_overall.hadir,
            "sakit": att_overall.sakit,
            "izin": att_overall.izin,
            "alpa": att_overall.alpa,
            "attendance_percentage": att_overall.attendance_percentage,
        },
        "component_averages": [
            {
                "category": cat,
                "title": cat,
                "average": (
                    round(sum(category_scores[cat]) / len(category_scores[cat]), 2)
                    if category_scores[cat]
                    else None
                ),
                "graded_count": len(category_scores[cat]),
                "assessment_count": len(category_asmt_ids[cat]),
            }
            for cat in (
                [
                    c
                    for c in [
                        "Tugas",
                        "Kuis",
                        "Latihan",
                        "Proyek",
                        "Praktik",
                        "Asesmen Formatif",
                        "Asesmen Sumatif",
                        "Ujian",
                    ]
                    if c in category_asmt_ids
                ]
                + sorted(
                    c
                    for c in category_asmt_ids
                    if c
                    not in {
                        "Tugas",
                        "Kuis",
                        "Latihan",
                        "Proyek",
                        "Praktik",
                        "Asesmen Formatif",
                        "Asesmen Sumatif",
                        "Ujian",
                    }
                )
            )
        ],
        "attention_students": attention_students,
        "early_warning": self._build_ews_summary_from_attention(
            ews_candidates,
            self._config.ews_alpa_threshold,
            self._config.ews_unsubmitted_checklist_threshold,
        ),
    }

  @staticmethod
  def _build_ews_summary_from_attention(
      items: List[Dict[str, Any]],
      alpa_threshold: int,
      unsubmitted_checklist_threshold: int = 3,
  ) -> Dict[str, Any]:
    flagged: List[Dict[str, Any]] = []
    for it in items:
      kkm = float(it.get("kkm", 75.0))
      final_sc = it.get("final_score")
      alpa_cnt = int(it.get("alpa_count", 0))
      unsub_cnt = int(it.get("unsubmitted_checklist_count", 0))
      ev = evaluate_student_ews(
          final_score=final_sc,
          mastery_threshold=kkm,
          alpa_count=alpa_cnt,
          alpa_threshold=alpa_threshold,
          unsubmitted_checklist_count=unsub_cnt,
          unsubmitted_checklist_threshold=unsubmitted_checklist_threshold,
      )
      if not ev["is_triggered"]:
        continue
      flagged.append({
          "student_id": it["student_id"],
          "student_code": it["student_code"],
          "full_name": it["full_name"],
          "class_id": it["class_id"],
          "class_name": it["class_name"],
          "final_score": final_sc,
          "kkm": kkm,
          "alpa_count": alpa_cnt,
          "unsubmitted_checklist_count": unsub_cnt,
          "attendance_percentage": it.get("attendance_percentage"),
          "severity": ev["severity"],
          "triggers": ev["triggers"],
          "reasons": ev["reasons"],
      })
    flagged.sort(
        key=lambda x: (
            0 if x["severity"] == "kritis" else 1,
            -int(x["alpa_count"]),
            -int(x.get("unsubmitted_checklist_count", 0)),
            float(x["final_score"]) if x["final_score"] is not None else 999.0,
            str(x["full_name"]).lower(),
        )
    )
    return {
        "alpa_threshold": alpa_threshold,
        "unsubmitted_checklist_threshold": unsubmitted_checklist_threshold,
        "total_flagged": len(flagged),
        "critical_count": sum(1 for x in flagged if x["severity"] == "kritis"),
        "warning_count": sum(1 for x in flagged if x["severity"] == "perhatian"),
        "students": flagged,
    }

  def get_early_warning_report(
      self,
      teacher: User,
      class_id: Optional[int] = None,
      period_id: Optional[int] = None,
      alpa_threshold: Optional[int] = None,
  ) -> Dict[str, Any]:
    """Sistem Peringatan Dini (EWS) berbasis data nilai (analytics) dan alpa (attendance)."""
    AuthService.require_role(teacher, Role.TEACHER)
    threshold = self._config.ews_alpa_threshold if alpa_threshold is None else int(alpa_threshold)
    if threshold < 1:
      raise ValidationError("Ambang batas alpa minimal 1.")

    if class_id is not None:
      cls = self._academic_repo.get_classroom(class_id)
      if not cls:
        raise NotFoundError("Kelas tidak ditemukan.")
      if cls.teacher_id != teacher.id:
        raise AuthorizationError("Anda tidak berwenang melihat peringatan dini kelas guru lain.")
      selected_classes = [cls]
    else:
      selected_classes = self._academic_repo.list_classrooms(
          teacher.id, period_id=period_id, include_archived=False
      )

    candidates: List[Dict[str, Any]] = []
    for cls in selected_classes:
      students = self._academic_repo.list_students(teacher.id, class_id=cls.id)
      assessments = self._grade_repo.list_assessments(cls.id, published_only=False)
      grades = self._grade_repo.list_grades_for_class(cls.id)
      grade_map = {(int(g["student_id"]), int(g["assessment_id"])): g["score"] for g in grades}

      if self._attendance_service is not None:
        alpa_map = self._attendance_service.get_student_alpa_counts(teacher, cls.id)
      else:
        alpa_map = {}
        for rec in self._attendance_repo.list_records_for_class(cls.id):
          if str(rec["status"]) == "alpa":
            sid = int(rec["student_id"])
            alpa_map[sid] = alpa_map.get(sid, 0) + 1

      att_records = self._attendance_repo.list_records_for_class(cls.id)
      att_by_stu: Dict[int, List[str]] = defaultdict(list)
      for rec in att_records:
        att_by_stu[int(rec["student_id"])].append(str(rec["status"]))

      published_checklists = [
          a for a in assessments
          if a.status == AssessmentStatus.PUBLISHED and not a.is_graded
      ]
      for stu in students:
        w_items = [
            WeightedScoreItem(
                score=grade_map.get((stu.id, a.id)),
                max_score=a.max_score,
                weight=a.weight,
            )
            for a in assessments
            if a.is_graded
        ]
        unsub_cnt = sum(
            1
            for chk in published_checklists
            if (
                grade_map.get((stu.id, chk.id)) is None
                or float(grade_map[(stu.id, chk.id)]) < 1.0
            )
        )
        final_sc = compute_final_score(w_items, mode=cls.calculation_mode)
        att_sum = summarize_attendance(
            att_by_stu.get(stu.id, []),
            high_absence_threshold_pct=self._config.high_absence_threshold_pct,
        )
        candidates.append({
            "student_id": stu.id,
            "student_code": stu.student_code,
            "full_name": stu.full_name,
            "class_id": cls.id,
            "class_name": cls.name,
            "final_score": final_sc,
            "kkm": cls.mastery_threshold,
            "alpa_count": int(alpa_map.get(stu.id, att_sum.alpa)),
            "unsubmitted_checklist_count": unsub_cnt,
            "attendance_percentage": att_sum.attendance_percentage,
        })

    return self._build_ews_summary_from_attention(
        candidates, threshold, self._config.ews_unsubmitted_checklist_threshold
    )

  def get_student_progress_for_teacher(
      self, teacher: User, student_id: int
  ) -> Dict[str, Any]:
    """Grafik perkembangan nilai dan kehadiran individual untuk guru."""
    AuthService.require_role(teacher, Role.TEACHER)
    stu = self._academic_repo.get_student(student_id)
    if not stu:
      raise NotFoundError("Peserta didik tidak ditemukan.")
    if stu.teacher_id != teacher.id:
      raise AuthorizationError("Anda tidak berwenang melihat data peserta didik ini.")
    return self._build_student_analytics(stu.id, published_only=False)

  def compare_students_for_teacher(
      self,
      teacher: User,
      class_id: int,
      student_ids: Sequence[int],
      material_id: Optional[int] = None,
  ) -> Dict[str, Any]:
    """Membandingkan tren nilai beberapa peserta didik dalam satu kelas bagi guru."""
    AuthService.require_role(teacher, Role.TEACHER)
    cls = self._academic_repo.get_classroom(class_id)
    if not cls:
      raise NotFoundError("Kelas tidak ditemukan.")
    if cls.teacher_id != teacher.id:
      raise AuthorizationError("Anda tidak berwenang membandingkan kelas guru lain.")

    assessments = [
        a
        for a in self._grade_repo.list_assessments(class_id, published_only=False)
        if a.is_graded
    ]
    if material_id is not None:
      assessments = [a for a in assessments if a.material_id == material_id]
    grades = self._grade_repo.list_grades_for_class(class_id)
    grade_map = {(int(g["student_id"]), int(g["assessment_id"])): g for g in grades}

    series = []
    for sid in student_ids:
      stu = self._academic_repo.get_student(sid)
      if not stu or stu.teacher_id != teacher.id:
        raise AuthorizationError(f"Peserta didik #{sid} bukan dalam kewenangan Anda.")
      points = []
      for asmt in assessments:
        g = grade_map.get((stu.id, asmt.id))
        sc = (
            round(normalize_score(float(g["score"]), asmt.max_score), 2)
            if g and g["score"] is not None
            else None
        )
        points.append({
            "assessment_id": asmt.id,
            "title": asmt.title,
            "date": asmt.assessment_date,
            "score": sc,
        })
      series.append({
          "student_id": stu.id,
          "full_name": stu.full_name,
          "student_code": stu.student_code,
          "points": points,
      })

    return {
        "class_id": cls.id,
        "class_name": cls.name,
        "selected_material_id": material_id,
        "assessments": [
            {
                "id": a.id,
                "title": a.title,
                "date": a.assessment_date,
                "material_id": a.material_id,
            }
            for a in assessments
        ],
        "series": series,
    }

  def get_attendance_recap(
      self,
      teacher: User,
      class_id: int,
      granularity: str = "monthly",
      date_from: Optional[str] = None,
      date_to: Optional[str] = None,
  ) -> Dict[str, Any]:
    """Rekapitulasi kehadiran kelas berdasarkan harian/mingguan/bulanan/semester/tahunan."""
    AuthService.require_role(teacher, Role.TEACHER)
    cls = self._academic_repo.get_classroom(class_id)
    if not cls:
      raise NotFoundError("Kelas tidak ditemukan.")
    if cls.teacher_id != teacher.id:
      raise AuthorizationError("Anda tidak berwenang mengakses rekap kelas guru lain.")

    students = self._academic_repo.list_students(teacher.id, class_id=class_id)
    records = self._attendance_repo.list_records_for_class(
        class_id, date_from=date_from, date_to=date_to
    )

    by_student: Dict[int, List[str]] = defaultdict(list)
    by_bucket: Dict[str, List[str]] = defaultdict(list)
    all_statuses: List[str] = []

    for rec in records:
      st = str(rec["status"])
      by_student[int(rec["student_id"])].append(st)
      bkey = (
          f"Periode #{cls.period_id}"
          if granularity == "semester"
          else _bucket_date(str(rec["session_date"]), granularity)
      )
      by_bucket[bkey].append(st)
      all_statuses.append(st)

    student_recaps = []
    for stu in students:
      summary = summarize_attendance(
          by_student.get(stu.id, []),
          high_absence_threshold_pct=self._config.high_absence_threshold_pct,
      )
      student_recaps.append({
          "student_id": stu.id,
          "student_code": stu.student_code,
          "full_name": stu.full_name,
          "total_recorded": summary.total_recorded,
          "hadir": summary.hadir,
          "sakit": summary.sakit,
          "izin": summary.izin,
          "alpa": summary.alpa,
          "attendance_percentage": summary.attendance_percentage,
          "absence_percentage": summary.absence_percentage,
          "needs_attention": summary.needs_attention,
      })

    timeline = []
    for bkey in sorted(by_bucket.keys()):
      bsum = summarize_attendance(
          by_bucket[bkey],
          high_absence_threshold_pct=self._config.high_absence_threshold_pct,
      )
      timeline.append({
          "bucket": bkey,
          "total_recorded": bsum.total_recorded,
          "hadir": bsum.hadir,
          "sakit": bsum.sakit,
          "izin": bsum.izin,
          "alpa": bsum.alpa,
          "attendance_percentage": bsum.attendance_percentage,
      })

    overall = summarize_attendance(
        all_statuses,
        high_absence_threshold_pct=self._config.high_absence_threshold_pct,
    )
    return {
        "class_id": cls.id,
        "class_name": cls.name,
        "granularity": granularity,
        "overall": {
            "total_recorded": overall.total_recorded,
            "hadir": overall.hadir,
            "sakit": overall.sakit,
            "izin": overall.izin,
            "alpa": overall.alpa,
            "attendance_percentage": overall.attendance_percentage,
        },
        "timeline": timeline,
        "students": student_recaps,
    }

  def get_student_dashboard(
      self,
      student_user: User,
      period_id: Optional[int] = None,
      month: Optional[str] = None,
      material_id: Optional[int] = None,
  ) -> Dict[str, Any]:
    """Dashboard pribadi peserta didik: hanya memuat data miliknya sendiri."""
    AuthService.require_role(student_user, Role.STUDENT)
    profile = self._academic_repo.get_student_by_user_id(student_user.id)
    if not profile:
      raise NotFoundError("Profil peserta didik tidak ditemukan.")
    return self._build_student_analytics(
        profile.id, published_only=True, period_id=period_id, month=month, material_id=material_id
    )

  def _build_student_analytics(
      self,
      student_id: int,
      published_only: bool,
      period_id: Optional[int] = None,
      month: Optional[str] = None,
      material_id: Optional[int] = None,
  ) -> Dict[str, Any]:
    profile = self._academic_repo.get_student(student_id)
    if not profile:
      raise NotFoundError('Profil peserta didik tidak ditemukan.')
    classroom = self._academic_repo.get_classroom(profile.current_class_id)
    if not classroom:
      raise NotFoundError('Kelas peserta didik tidak ditemukan.')

    grade_rows = sorted(
        self._grade_repo.list_grades_for_student(
            student_id=profile.id, published_only=published_only, period_id=period_id, material_id=material_id
        ),
        key=lambda r: (str(r["assessment_date"]), int(r["assessment_id"])),
    )
    class_materials = self._grade_repo.list_materials(classroom.id, include_archived=False)
    items: List[WeightedScoreItem] = []
    timeline: List[Dict[str, Any]] = []
    checklist_tasks: List[Dict[str, Any]] = []
    by_category: Dict[str, List[float]] = defaultdict(list)

    for row in grade_rows:
      sc = row["score"]
      is_graded_row = bool(row.get("is_graded", True))
      if not is_graded_row:
        checklist_tasks.append({
            "assessment_id": int(row["assessment_id"]),
            "material_id": int(row["material_id"]) if row.get("material_id") is not None else None,
            "material_title": str(row.get("material_title") or "Belum Dikelompokkan"),
            "title": str(row["title"]),
            "category": str(row["category"]),
            "date": str(row["assessment_date"]),
            "class_name": str(row["class_name"]),
            "description": str(row["description"]),
            "submitted": sc is not None and float(sc) >= 1.0,
            "feedback": str(row["feedback"]),
            "status": str(row["status"]),
        })
        continue
      max_sc = float(row["max_score"])
      wt = float(row["weight"])
      items.append(WeightedScoreItem(score=sc, max_score=max_sc, weight=wt))
      norm_sc = round(normalize_score(float(sc), max_sc), 2) if sc is not None else None
      if norm_sc is not None:
        by_category[str(row["category"])].append(norm_sc)
      revealed_at = row.get("revealed_at")
      is_surprise = str(row["category"]).strip().lower() in SURPRISE_REVEAL_CATEGORIES
      needs_reveal = bool(published_only and is_surprise and sc is not None and not revealed_at)
      timeline.append({
          "assessment_id": int(row["assessment_id"]),
          "material_id": int(row["material_id"]) if row.get("material_id") is not None else None,
          "material_title": str(row.get("material_title") or "Belum Dikelompokkan"),
          "title": str(row["title"]),
          "category": str(row["category"]),
          "date": str(row["assessment_date"]),
          "class_name": str(row["class_name"]),
          "raw_score": sc,
          "max_score": max_sc,
          "normalized_score": norm_sc,
          "weight": wt,
          "description": str(row["description"]),
          "feedback": str(row["feedback"]),
          "status": str(row["status"]),
          "revealed_at": revealed_at,
          "needs_reveal": needs_reveal,
      })

    # Hitung jumlah tugas checklist & timeline lintas seluruh materi kelas
    all_published_rows = sorted(
        self._grade_repo.list_grades_for_student(
            student_id=profile.id, published_only=True, class_id=classroom.id, period_id=period_id
        ),
        key=lambda r: (str(r["assessment_date"]), int(r["assessment_id"])),
    )
    unsubmitted_checklist_count = sum(
        1
        for r in all_published_rows
        if (
            not bool(r.get("is_graded", True))
            and (r["score"] is None or float(r["score"]) < 1.0)
        )
    )
    all_grade_timeline: List[Dict[str, Any]] = []
    pending_reveals: List[Dict[str, Any]] = []
    for r in all_published_rows:
      if not bool(r.get("is_graded", True)):
        continue
      rsc = r["score"]
      rmax = float(r["max_score"])
      rnorm = round(normalize_score(float(rsc), rmax), 2) if rsc is not None else None
      r_rev = r.get("revealed_at")
      r_surprise = str(r["category"]).strip().lower() in SURPRISE_REVEAL_CATEGORIES
      r_needs = bool(published_only and r_surprise and rsc is not None and not r_rev)
      entry = {
          "assessment_id": int(r["assessment_id"]),
          "material_id": int(r["material_id"]) if r.get("material_id") is not None else None,
          "material_title": str(r.get("material_title") or "Belum Dikelompokkan"),
          "title": str(r["title"]),
          "category": str(r["category"]),
          "date": str(r["assessment_date"]),
          "raw_score": rsc,
          "max_score": rmax,
          "normalized_score": rnorm,
          "feedback": str(r["feedback"]),
          "revealed_at": r_rev,
          "needs_reveal": r_needs,
      }
      all_grade_timeline.append(entry)
      if r_needs:
        pending_reveals.append(entry)

    final_score = compute_final_score(items, mode=classroom.calculation_mode)
    trend = compute_learning_trend([p["normalized_score"] for p in timeline])

    category_comparison = [
        {
            "category": cat,
            "average": round(sum(vals) / len(vals), 2),
            "count": len(vals),
        }
        for cat, vals in sorted(by_category.items())
    ]

    att_records = self._attendance_repo.list_records_for_student(
        student_id=profile.id, month=month, period_id=period_id
    )
    att_summary = summarize_attendance(
        [r["status"] for r in att_records],
        high_absence_threshold_pct=self._config.high_absence_threshold_pct,
    )

    return {
        "student": {
            "id": profile.id,
            "student_code": profile.student_code,
            "full_name": profile.full_name,
            "username": profile.username,
            "account_status": profile.account_status.value,
        },
        "classroom": {
            "id": classroom.id,
            "name": classroom.name,
            "education_level": classroom.education_level,
            "academic_year": classroom.academic_year,
            "mastery_threshold": classroom.mastery_threshold,
            "calculation_mode": classroom.calculation_mode.value,
            "allow_student_report_download": classroom.allow_student_report_download,
        },
        "enrollments": self._academic_repo.list_student_enrollments(profile.id),
        "grade_summary": {
            "final_score": final_score,
            "graded_assessments": sum(1 for p in timeline if p["normalized_score"] is not None),
            "total_assessments": len(timeline),
            "trend_indicator": trend["indicator"],
            "trend_delta": trend["delta"],
        },
        "grade_timeline": timeline,
        "all_grade_timeline": all_grade_timeline,
        "pending_reveals": pending_reveals,
        "checklist_tasks": checklist_tasks,
        "materials": [
            {"id": m.id, "title": m.title, "description": m.description, "sort_order": m.sort_order}
            for m in class_materials
        ],
        "announcements": [
            {
                "id": ann.id,
                "class_id": ann.class_id,
                "title": ann.title,
                "category": ann.category,
                "content": ann.content,
                "is_pinned": ann.is_pinned,
                "created_at": ann.created_at,
                "updated_at": ann.updated_at,
            }
            for ann in self._academic_repo.list_announcements(classroom.id)
        ],
        "selected_material_id": material_id,
        "category_comparison": category_comparison,
        "attendance_summary": {
            "total_recorded": att_summary.total_recorded,
            "hadir": att_summary.hadir,
            "sakit": att_summary.sakit,
            "izin": att_summary.izin,
            "alpa": att_summary.alpa,
            "attendance_percentage": att_summary.attendance_percentage,
            "absence_percentage": att_summary.absence_percentage,
        },
        "attendance_records": att_records,
        "early_warning": evaluate_student_ews(
            final_score=final_score,
            mastery_threshold=classroom.mastery_threshold,
            alpa_count=att_summary.alpa,
            alpa_threshold=self._config.ews_alpa_threshold,
            unsubmitted_checklist_count=unsubmitted_checklist_count,
            unsubmitted_checklist_threshold=self._config.ews_unsubmitted_checklist_threshold,
        ),
    }
