"""Layanan pengelolaan komponen penilaian, input nilai, publikasi, dan audit nilai."""

from __future__ import annotations

import io
import math
import openpyxl

from typing import Any, Dict, List, Optional, Sequence

from edutrack.domain.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from edutrack.domain.grading import (
    WeightedScoreItem,
    compute_class_statistics,
    compute_final_score,
    normalize_score,
)
from edutrack.domain.models import Assessment, AssessmentStatus, CalculationMode, LearningMaterial, Role, SURPRISE_REVEAL_CATEGORIES, User
from edutrack.repositories.academic_repo import AcademicRepository
from edutrack.repositories.grade_repo import GradeRepository
from edutrack.repositories.user_repo import UserRepository
from edutrack.services.auth_service import AuthService


class GradeService:
  """Mengelola penilaian, entri nilai individual/massal, publikasi, dan rekap nilai."""

  def __init__(
      self,
      grade_repo: GradeRepository,
      academic_repo: AcademicRepository,
      user_repo: UserRepository,
  ) -> None:
    self._grade_repo = grade_repo
    self._academic_repo = academic_repo
    self._user_repo = user_repo

  def _get_owned_class(self, teacher: User, class_id: int):
    AuthService.require_role(teacher, Role.TEACHER)
    classroom = self._academic_repo.get_classroom(class_id)
    if not classroom:
      raise NotFoundError("Kelas tidak ditemukan.")
    if classroom.teacher_id != teacher.id:
      raise AuthorizationError("Akses ditolak: kelas ini bukan milik Anda.")
    return classroom

  def _get_owned_assessment(self, teacher: User, assessment_id: int) -> Assessment:
    AuthService.require_role(teacher, Role.TEACHER)
    assessment = self._grade_repo.get_assessment(assessment_id)
    if not assessment:
      raise NotFoundError("Komponen penilaian tidak ditemukan.")
    self._get_owned_class(teacher, assessment.class_id)
    return assessment

  def create_assessment(
      self,
      teacher: User,
      class_id: int,
      title: str,
      category: str,
      assessment_date: str,
      description: str = "",
      max_score: float = 100.0,
      weight: float = 1.0,
      status: AssessmentStatus = AssessmentStatus.DRAFT,
      material_id: Optional[int] = None,
      is_graded: bool = True,
  ) -> Assessment:
    classroom = self._get_owned_class(teacher, class_id)
    if not title.strip() or not category.strip() or not assessment_date.strip():
      raise ValidationError("Nama penilaian, kategori, dan tanggal wajib diisi.")
    graded_flag = bool(is_graded)
    if not graded_flag:
      max_score = 1.0
      weight = 0.0
    else:
      if not math.isfinite(max_score) or max_score <= 0:
        raise ValidationError("Rentang nilai maksimum harus berupa angka valid lebih besar dari 0.")
      if not math.isfinite(weight) or weight < 0:
        raise ValidationError("Bobot penilaian harus berupa angka valid dan tidak boleh negatif.")

    if material_id is not None:
      mat = self._grade_repo.get_material(material_id)
      if not mat or mat.class_id != class_id:
        raise ValidationError("Materi pembelajaran tidak ditemukan pada kelas ini.")
    assessment = self._grade_repo.create_assessment(
        class_id=class_id,
        period_id=classroom.period_id,
        title=title.strip(),
        category=category.strip(),
        assessment_date=assessment_date.strip(),
        description=description.strip(),
        max_score=float(max_score),
        weight=float(weight),
        status=status,
        material_id=material_id,
        is_graded=graded_flag,
    )
    self._user_repo.log_audit(
        teacher.id,
        "create_assessment",
        "assessment",
        assessment.id,
        f"{assessment.title} ({assessment.category}, status={assessment.status.value})",
    )
    return assessment

  def list_assessments(self, teacher: User, class_id: int) -> List[Assessment]:
    self._get_owned_class(teacher, class_id)
    return self._grade_repo.list_assessments(class_id, published_only=False)

  def update_assessment(
      self,
      teacher: User,
      assessment_id: int,
      title: Optional[str] = None,
      category: Optional[str] = None,
      assessment_date: Optional[str] = None,
      description: Optional[str] = None,
      max_score: Optional[float] = None,
      weight: Optional[float] = None,
      status: Optional[AssessmentStatus] = None,
      material_id: Optional[int] = None,
      update_material_id: bool = False,
      is_graded: Optional[bool] = None,
  ) -> Assessment:
    existing = self._get_owned_assessment(teacher, assessment_id)
    if title is not None and not title.strip():
      raise ValidationError("Nama penilaian tidak boleh kosong.")
    if category is not None and not category.strip():
      raise ValidationError("Kategori penilaian tidak boleh kosong.")
    if assessment_date is not None and not assessment_date.strip():
      raise ValidationError("Tanggal penilaian tidak boleh kosong.")
    if is_graded is not None and bool(is_graded) != existing.is_graded:
      existing_grades = self._grade_repo.list_grades_for_assessment(assessment_id)
      if any(g.get("score") is not None for g in existing_grades):
        raise ValidationError(
            "Jenis tugas tidak dapat diubah karena sudah memiliki data nilai atau pengumpulan."
        )
    effective_is_graded = existing.is_graded if is_graded is None else bool(is_graded)
    if not effective_is_graded:
      max_score = 1.0
      weight = 0.0
    else:
      if max_score is not None and (not math.isfinite(max_score) or max_score <= 0):
        raise ValidationError("Rentang nilai maksimum harus berupa angka valid > 0.")
      if weight is not None and (not math.isfinite(weight) or weight < 0):
        raise ValidationError("Bobot penilaian harus berupa angka valid dan tidak boleh negatif.")

    if update_material_id and material_id is not None:
      mat = self._grade_repo.get_material(material_id)
      if not mat or mat.class_id != existing.class_id:
        raise ValidationError("Materi pembelajaran tidak ditemukan pada kelas ini.")
    updated = self._grade_repo.update_assessment(
        assessment_id=assessment_id,
        title=title.strip() if title is not None else None,
        category=category.strip() if category is not None else None,
        assessment_date=assessment_date.strip() if assessment_date is not None else None,
        description=description.strip() if description is not None else None,
        max_score=float(max_score) if max_score is not None else None,
        weight=float(weight) if weight is not None else None,
        status=status,
        material_id=material_id,
        update_material_id=update_material_id,
        is_graded=effective_is_graded,
    )
    if updated is None:
      raise NotFoundError("Komponen penilaian tidak ditemukan.")
    self._user_repo.log_audit(
        teacher.id,
        "update_assessment",
        "assessment",
        assessment_id,
        f"status={updated.status.value}, weight={updated.weight}",
    )
    return updated

  def delete_assessment(self, teacher: User, assessment_id: int) -> None:
    assessment = self._get_owned_assessment(teacher, assessment_id)
    self._grade_repo.delete_assessment(assessment_id)
    self._user_repo.log_audit(
        teacher.id,
        "delete_assessment",
        "assessment",
        assessment_id,
        f"Penilaian '{assessment.title}' dihapus permanen.",
    )

  def reset_assessment_grades(self, teacher: User, assessment_id: int) -> Dict[str, Any]:
    """Menghapus permanen seluruh nilai & riwayat pada satu komponen penilaian agar mulai dari nol."""
    assessment = self._get_owned_assessment(teacher, assessment_id)
    cleared = self._grade_repo.reset_grades_for_assessment(assessment_id)
    self._user_repo.log_audit(
        teacher.id,
        "reset_assessment_grades",
        "assessment",
        assessment_id,
        f"Reset permanen nilai '{assessment.title}' ({cleared} entri dihapus).",
    )
    return {"status": "reset", "cleared": cleared}

  def reveal_student_grade(self, student_user: User, assessment_id: int) -> Dict[str, Any]:
    """Membuka nilai kejutan Ujian/Asesmen Sumatif milik siswa dan mencatat revealed_at di database."""
    AuthService.require_role(student_user, Role.STUDENT)
    profile = self._academic_repo.get_student_by_user_id(student_user.id)
    if not profile:
      raise NotFoundError("Profil peserta didik tidak ditemukan.")
    from edutrack.repositories.database import utc_now_iso  # pylint: disable=import-outside-toplevel
    rec = self._grade_repo.reveal_student_grade(assessment_id, profile.id, utc_now_iso())
    if not rec or str(rec["status"]) != AssessmentStatus.PUBLISHED.value:
      raise NotFoundError("Nilai penilaian tidak ditemukan atau belum dipublikasikan.")
    if not rec["is_graded"] or str(rec["category"]).strip().lower() not in SURPRISE_REVEAL_CATEGORIES:
      raise ValidationError("Fitur buka nilai kejutan hanya berlaku untuk Ujian dan Asesmen Sumatif.")
    if rec["score"] is None:
      raise ValidationError("Nilai untuk penilaian ini belum tersedia.")
    norm_sc = round(normalize_score(float(rec["score"]), float(rec["max_score"])), 2)
    return {
        "assessment_id": int(rec["assessment_id"]),
        "title": str(rec["title"]),
        "category": str(rec["category"]),
        "raw_score": float(rec["score"]),
        "max_score": float(rec["max_score"]),
        "normalized_score": norm_sc,
        "feedback": str(rec["feedback"]),
        "revealed_at": str(rec["revealed_at"]),
    }

  def save_grades_bulk(
      self,
      teacher: User,
      assessment_id: int,
      entries: Sequence[Dict[str, Any]],
      reason: str = "",
  ) -> List[Dict[str, Any]]:
    """Menyimpan nilai satu atau banyak peserta didik sekaligus untuk satu penilaian.

    Nilai ``None`` diizinkan untuk menandakan nilai belum diinput (berbeda dari 0).
    """
    assessment = self._get_owned_assessment(teacher, assessment_id)
    validated_entries: List[tuple[int, Optional[float], str]] = []
    seen_student_ids: set[int] = set()

    for entry in entries:
      try:
        student_id = int(entry["student_id"])
      except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("student_id pada entri nilai tidak valid.") from exc
      if student_id in seen_student_ids:
        raise ValidationError(
            f"Duplikat entri nilai untuk peserta didik #{student_id} dalam satu permintaan."
        )
      seen_student_ids.add(student_id)

      student = self._academic_repo.get_student(student_id)
      if not student or student.teacher_id != teacher.id:
        raise AuthorizationError(
            f"Peserta didik #{student_id} bukan dalam kewenangan Anda."
        )
      raw_score = entry.get("score")
      score: Optional[float] = None
      if not assessment.is_graded:
        if raw_score is None or raw_score is False or (isinstance(raw_score, str) and raw_score.strip() == ""):
          score = None
        elif raw_score is True:
          score = 1.0
        else:
          try:
            num = float(raw_score.strip().replace(",", ".")) if isinstance(raw_score, str) else float(raw_score)
          except (TypeError, ValueError) as exc:
            raise ValidationError(
                f"Status checklist untuk peserta didik #{student_id} tidak valid."
            ) from exc
          if not math.isfinite(num) or num not in (0.0, 1.0):
            raise ValidationError(
                "Untuk tugas checklist (tidak dinilai), nilai hanya boleh 1 (sudah mengumpulkan) atau kosong."
            )
          score = 1.0 if num == 1.0 else None
      elif raw_score is not None and not (isinstance(raw_score, str) and raw_score.strip() == ""):
        try:
          score = (
              float(raw_score.strip().replace(",", "."))
              if isinstance(raw_score, str)
              else float(raw_score)
          )
        except (TypeError, ValueError) as exc:
          raise ValidationError(
              f"Nilai untuk peserta didik #{student_id} harus berupa angka yang valid."
          ) from exc
        if not math.isfinite(score):
          raise ValidationError(
              f"Nilai untuk peserta didik #{student_id} harus berupa angka yang valid."
          )
        normalize_score(score, assessment.max_score)

      feedback = str(entry.get("feedback") or "").strip()
      validated_entries.append((student_id, score, feedback))

    saved: List[Dict[str, Any]] = []
    for student_id, score, feedback in validated_entries:
      row = self._grade_repo.upsert_grade(
          assessment_id=assessment_id,
          student_id=student_id,
          score=score,
          feedback=feedback,
          actor_user_id=teacher.id,
          reason=reason,
      )
      saved.append(row)

    self._user_repo.log_audit(
        teacher.id,
        "save_grades",
        "assessment",
        assessment_id,
        f"{len(saved)} entri nilai disimpan.",
    )
    return saved

  def get_class_gradebook(self, teacher: User, class_id: int, material_id: Optional[int] = None) -> Dict[str, Any]:
    """Mengembalikan matriks buku nilai lengkap, pengelompokan materi, nilai akhir, dan statistik."""
    classroom = self._get_owned_class(teacher, class_id)
    students = self._academic_repo.list_students(teacher.id, class_id=class_id)
    materials = self._grade_repo.list_materials(class_id, include_archived=True)
    all_assessments = self._grade_repo.list_assessments(class_id, published_only=False)
    if material_id is None:
      assessments = all_assessments
    elif material_id == 0:
      assessments = [a for a in all_assessments if a.material_id is None]
    else:
      assessments = [a for a in all_assessments if a.material_id == material_id]

    all_grades = self._grade_repo.list_grades_for_class(class_id)
    grade_map: Dict[tuple[int, int], Dict[str, Any]] = {
        (int(g["student_id"]), int(g["assessment_id"])): g for g in all_grades
    }

    material_titles: Dict[str, str] = {"0": "Belum Dikelompokkan"}
    for mat in materials:
      material_titles[str(mat.id)] = mat.title

    rows: List[Dict[str, Any]] = []
    final_scores: List[Optional[float]] = []

    for stu in students:
      items: List[WeightedScoreItem] = []
      scores_by_assessment: Dict[int, Dict[str, Any]] = {}
      for asmt in assessments:
        rec = grade_map.get((stu.id, asmt.id))
        sc = rec["score"] if rec else None
        fb = rec["feedback"] if rec else ""
        if asmt.status == AssessmentStatus.PUBLISHED and asmt.is_graded:
          items.append(
              WeightedScoreItem(score=sc, max_score=asmt.max_score, weight=asmt.weight)
          )
        scores_by_assessment[asmt.id] = {
            "score": sc,
            "feedback": fb,
            "updated_at": rec["updated_at"] if rec else None,
        }

      # Hitung rata-rata per materi berdasarkan seluruh penilaian terpublikasi kelas
      mat_buckets: Dict[str, List[WeightedScoreItem]] = {}
      for asmt in all_assessments:
        if asmt.status != AssessmentStatus.PUBLISHED or not asmt.is_graded:
          continue
        rec = grade_map.get((stu.id, asmt.id))
        sc = rec["score"] if rec else None
        key = str(asmt.material_id) if asmt.material_id is not None else "0"
        mat_buckets.setdefault(key, []).append(
            WeightedScoreItem(score=sc, max_score=asmt.max_score, weight=asmt.weight)
        )
      material_averages: Dict[str, Optional[float]] = {
          k: compute_final_score(v, mode=classroom.calculation_mode)
          for k, v in mat_buckets.items()
      }

      final_score = compute_final_score(items, mode=classroom.calculation_mode)
      final_scores.append(final_score)
      rows.append({
          "student_id": stu.id,
          "student_code": stu.student_code,
          "full_name": stu.full_name,
          "account_status": stu.account_status.value,
          "scores": scores_by_assessment,
          "material_averages": material_averages,
          "final_score": final_score,
          "is_mastered": (
              final_score >= classroom.mastery_threshold
              if final_score is not None
              else None
          ),
      })

    material_summary: List[Dict[str, Any]] = []
    for mat in materials:
      m_key = str(mat.id)
      m_scores = [r["material_averages"].get(m_key) for r in rows if r["material_averages"].get(m_key) is not None]
      m_count = sum(1 for a in all_assessments if a.material_id == mat.id)
      is_arch = bool(getattr(mat, "is_archived", False))
      material_summary.append({
          "id": mat.id,
          "material_id": mat.id,
          "title": mat.title,
          "description": getattr(mat, "description", ""),
          "is_archived": is_arch,
          "status": "archived" if is_arch else "active",
          "sort_order": mat.sort_order,
          "assessment_count": m_count,
          "class_average": round(sum(m_scores) / len(m_scores), 2) if m_scores else None,
      })
    ungrouped_count = sum(1 for a in all_assessments if a.material_id is None)
    if ungrouped_count > 0:
      u_scores = [r["material_averages"].get("0") for r in rows if r["material_averages"].get("0") is not None]
      material_summary.append({
          "id": 0,
          "material_id": 0,
          "title": "Belum Dikelompokkan",
          "description": "Penilaian lama atau umum tanpa materi.",
          "is_archived": False,
          "status": "active",
          "sort_order": 9999,
          "assessment_count": ungrouped_count,
          "class_average": round(sum(u_scores) / len(u_scores), 2) if u_scores else None,
      })

    stats = compute_class_statistics(
        final_scores, mastery_threshold=classroom.mastery_threshold
    )
    return {
        "classroom": classroom,
        "materials": materials,
        "material_titles": material_titles,
        "material_summary": material_summary,
        "selected_material_id": material_id,
        "all_assessments_count": len(all_assessments),
        "assessments": assessments,
        "rows": rows,
        "statistics": stats,
    }

  def list_grade_history(
      self,
      teacher: User,
      class_id: int,
      assessment_id: Optional[int] = None,
      student_id: Optional[int] = None,
  ) -> List[Dict[str, Any]]:
    self._get_owned_class(teacher, class_id)
    return self._grade_repo.list_grade_history(
        class_id=class_id, assessment_id=assessment_id, student_id=student_id
    )

  def get_student_published_grades(
      self, student_user: User, period_id: Optional[int] = None
  ) -> Dict[str, Any]:
    """Mengembalikan nilai yang sudah dipublikasikan khusus milik peserta didik."""
    AuthService.require_role(student_user, Role.STUDENT)
    profile = self._academic_repo.get_student_by_user_id(student_user.id)
    if not profile:
      raise NotFoundError("Profil peserta didik tidak ditemukan.")

    records = self._grade_repo.list_grades_for_student(
        student_id=profile.id, published_only=True, period_id=period_id
    )

    classroom = None
    if period_id is not None:
      if records:
        classroom = self._academic_repo.get_classroom(int(records[-1]["class_id"]))
      else:
        enrollments = self._academic_repo.list_student_enrollments(profile.id)
        for enr in reversed(enrollments):
          if enr.get("period_id") is not None and int(enr["period_id"]) == int(period_id):
            classroom = self._academic_repo.get_classroom(int(enr["class_id"]))
            if classroom is not None:
              break
    else:
      if profile.current_class_id is not None:
        classroom = self._academic_repo.get_classroom(profile.current_class_id)
      if classroom is None and records:
        classroom = self._academic_repo.get_classroom(int(records[-1]["class_id"]))

    items = [
        WeightedScoreItem(
            score=r["score"], max_score=float(r["max_score"]), weight=float(r["weight"])
        )
        for r in records
        if bool(r.get("is_graded", True))
    ]
    calc_mode = (
        classroom.calculation_mode
        if classroom is not None
        else CalculationMode.WEIGHTED
    )
    final_score = compute_final_score(items, mode=calc_mode)
    return {
        "student": profile,
        "classroom": classroom,
        "final_score": final_score,
        "assessments": records,
    }

  @staticmethod
  def _norm_cell(val: Any) -> str:
    if val is None:
      return ""
    if isinstance(val, float) and val.is_integer():
      return str(int(val))
    return str(val).strip()

  def generate_grade_import_template(self, teacher: User, assessment_id: int) -> tuple[str, bytes]:
    """Menghasilkan template Excel (.xlsx) impor nilai berisi konteks penilaian & daftar siswa kelas."""
    asmt = self._get_owned_assessment(teacher, assessment_id)
    if not asmt.is_graded:
      raise ValidationError(
          "Template impor Excel hanya tersedia untuk tugas bertipe Dinilai (Angka)."
      )
    classroom = self._academic_repo.get_classroom(asmt.class_id)
    period = self._academic_repo.get_period(asmt.period_id)
    students = self._academic_repo.list_students(teacher.id, class_id=asmt.class_id)
    existing_grades = {
        int(g["student_id"]): g for g in self._grade_repo.list_grades_for_assessment(asmt.id)
    }

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Template Nilai"
    ws.append(["TEMPLATE IMPOR NILAI PESERTA DIDIK — BAHASA INDONESIA"])
    ws.append(["Assessment ID", asmt.id])
    ws.append(["Kelas", classroom.name if classroom else f"#{asmt.class_id}"])
    ws.append(["Tingkat / Mapel", classroom.education_level if classroom else "-"])
    ws.append(["Tahun Pelajaran / Semester", f"{period.academic_year} ({period.semester})" if period else "-"])
    ws.append(["Kategori Penilaian", asmt.category])
    ws.append(["Nama Kegiatan / Asesmen", asmt.title])
    ws.append(["Tanggal Penilaian", asmt.assessment_date])
    ws.append(["Skor Maksimal", asmt.max_score])
    ws.append(["Status Publikasi", asmt.status.value])
    ws.append([])
    ws.append(["No.", "Identitas Peserta Didik", "Nama Peserta Didik", "Nilai", "Umpan Balik (Opsional)"])

    for idx, stu in enumerate(students, start=1):
      eg = existing_grades.get(stu.id)
      cur_score = "" if (not eg or eg["score"] is None) else eg["score"]
      cur_fb = eg["feedback"] if eg else ""
      ws.append([idx, stu.student_code, stu.full_name, cur_score, cur_fb])

    for col_letter, width in [("A", 26), ("B", 24), ("C", 30), ("D", 14), ("E", 32)]:
      ws.column_dimensions[col_letter].width = width

    guide = wb.create_sheet(title="Petunjuk Pengisian")
    guide.append(["Petunjuk Pengisian Template Impor Nilai"])
    guide.append(["1. Jangan ubah nilai 'Assessment ID' di baris ke-2 agar sistem memetakan nilai ke penilaian yang benar."])
    guide.append(["2. Isi kolom 'Nilai' dengan angka antara 0 sampai Skor Maksimal. Biarkan kosong jika belum dinilai (kosong tidak dianggap 0)."])
    guide.append(["3. Identitas Peserta Didik (NIS) digunakan untuk pencocokan unik agar tidak tertukar meskipun ada nama yang sama."])
    guide.append(["4. Nilai hasil impor mengikuti status Draft/Dipublikasikan; siswa tidak dapat melihat nilai Draft."])
    guide.column_dimensions["A"].width = 96

    buf = io.BytesIO()
    wb.save(buf)
    safe_title = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in asmt.title).strip("_") or "penilaian"
    return f"template_nilai_{safe_title}.xlsx", buf.getvalue()

  def _parse_and_validate_grade_import(
      self, teacher: User, assessment_id: int, filename: str, content: bytes
  ) -> Dict[str, Any]:
    asmt = self._get_owned_assessment(teacher, assessment_id)
    if not asmt.is_graded:
      raise ValidationError(
          "Impor nilai Excel hanya tersedia untuk tugas bertipe Dinilai (Angka)."
      )
    if not content:
      raise ValidationError("Berkas unggahan nilai kosong.")
    if not filename.lower().endswith(".xlsx"):
      raise ValidationError("Format berkas nilai harus Excel (.xlsx) sesuai template.")

    try:
      wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # pylint: disable=broad-except
      raise ValidationError(
          "Berkas Excel (.xlsx) tidak dapat dibaca atau rusak. Pastikan format berkas valid."
      ) from exc
    try:
      ws = wb.active
      if ws is None:
        raise ValidationError("Berkas Excel tidak memiliki lembar kerja aktif.")
      all_rows = list(ws.iter_rows(values_only=True))
    except ValidationError:
      raise
    except Exception as exc:  # pylint: disable=broad-except
      raise ValidationError(
          "Isi berkas Excel (.xlsx) rusak atau tidak dapat diproses."
      ) from exc
    finally:
      wb.close()
    if not all_rows:
      raise ValidationError("Berkas Excel kosong.")

    header_row_idx: Optional[int] = None
    headers: List[str] = []
    for idx, raw_row in enumerate(all_rows):
      cells = [self._norm_cell(c) for c in raw_row]
      lower_cells = [c.lower() for c in cells]
      if len(cells) >= 2 and lower_cells[0] == "assessment id" and cells[1]:
        try:
          file_asmt_id = int(float(cells[1]))
          if file_asmt_id != asmt.id:
            raise ValidationError(
                f"Template ini dibuat untuk penilaian #{file_asmt_id}, bukan penilaian terpilih (#{asmt.id} — {asmt.title})."
            )
        except ValueError:
          pass
      if any("identitas peserta didik" in c or c in ("nis", "student_code") for c in lower_cells) and any(
          c in ("nilai", "score") for c in lower_cells
      ):
        header_row_idx = idx
        headers = lower_cells
        break

    if header_row_idx is None:
      raise ValidationError(
          "Header tabel tidak ditemukan. Pastikan berkas memiliki kolom 'Identitas Peserta Didik' dan 'Nilai'."
      )

    students = self._academic_repo.list_students(teacher.id, class_id=asmt.class_id)
    by_code = {s.student_code.strip().lower(): s for s in students}
    existing_grades = {
        int(g["student_id"]): g for g in self._grade_repo.list_grades_for_assessment(asmt.id)
    }

    valid_rows: List[Dict[str, Any]] = []
    invalid_rows: List[Dict[str, Any]] = []
    seen_codes: set[str] = set()
    conflict_count = 0
    empty_count = 0

    for offset, raw_row in enumerate(all_rows[header_row_idx + 1:], start=header_row_idx + 2):
      if all(c is None or str(c).strip() == "" for c in raw_row):
        continue
      row_map = {
          headers[i]: (raw_row[i] if i < len(raw_row) else None)
          for i in range(len(headers))
      }
      code = self._norm_cell(
          row_map.get("identitas peserta didik") or row_map.get("nis") or row_map.get("student_code")
      )
      name = self._norm_cell(row_map.get("nama peserta didik") or row_map.get("nama"))
      raw_score = row_map.get("nilai") if "nilai" in row_map else row_map.get("score")
      feedback = self._norm_cell(row_map.get("umpan balik (opsional)") or row_map.get("umpan balik") or row_map.get("feedback"))

      if not code:
        invalid_rows.append({
            "row_number": offset,
            "column": "Identitas Peserta Didik",
            "reason": "Identitas peserta didik wajib diisi.",
            "student_code": "",
            "full_name": name,
            "raw_score": "" if raw_score is None else str(raw_score),
        })
        continue

      code_key = code.lower()
      if code_key in seen_codes:
        invalid_rows.append({
            "row_number": offset,
            "column": "Identitas Peserta Didik",
            "reason": f"Identitas '{code}' ganda di dalam berkas nilai.",
            "student_code": code,
            "full_name": name,
            "raw_score": "" if raw_score is None else str(raw_score),
        })
        continue
      seen_codes.add(code_key)

      student = by_code.get(code_key)
      if not student:
        invalid_rows.append({
            "row_number": offset,
            "column": "Identitas Peserta Didik",
            "reason": f"Peserta didik dengan identitas '{code}' tidak terdaftar di kelas ini.",
            "student_code": code,
            "full_name": name,
            "raw_score": "" if raw_score is None else str(raw_score),
        })
        continue

      score_str = "" if raw_score is None else str(raw_score).strip()
      if score_str == "":
        empty_count += 1
        existing_g = existing_grades.get(student.id)
        valid_rows.append({
            "row_number": offset,
            "student_id": student.id,
            "student_code": student.student_code,
            "full_name": student.full_name,
            "score": None,
            "feedback": feedback,
            "is_empty": True,
            "has_existing": bool(existing_g and existing_g["score"] is not None),
            "existing_score": existing_g["score"] if existing_g else None,
        })
        continue

      try:
        parsed_score = float(score_str.replace(",", "."))
        if math.isnan(parsed_score) or math.isinf(parsed_score):
          raise ValueError("Non-finite")
      except ValueError:
        invalid_rows.append({
            "row_number": offset,
            "column": "Nilai",
            "reason": f"Format nilai '{score_str}' tidak valid (harus berupa angka).",
            "student_code": student.student_code,
            "full_name": student.full_name,
            "raw_score": score_str,
        })
        continue

      if parsed_score < 0.0 or parsed_score > asmt.max_score:
        invalid_rows.append({
            "row_number": offset,
            "column": "Nilai",
            "reason": f"Nilai {parsed_score} di luar rentang 0 sampai {asmt.max_score}.",
            "student_code": student.student_code,
            "full_name": student.full_name,
            "raw_score": score_str,
        })
        continue

      existing_g = existing_grades.get(student.id)
      has_existing = bool(existing_g and existing_g["score"] is not None)
      if has_existing:
        conflict_count += 1

      valid_rows.append({
          "row_number": offset,
          "student_id": student.id,
          "student_code": student.student_code,
          "full_name": student.full_name,
          "score": parsed_score,
          "feedback": feedback,
          "is_empty": False,
          "has_existing": has_existing,
          "existing_score": existing_g["score"] if existing_g else None,
      })

    return {
        "assessment": {
            "id": asmt.id,
            "title": asmt.title,
            "category": asmt.category,
            "max_score": asmt.max_score,
            "status": asmt.status.value,
        },
        "total_rows": len(valid_rows) + len(invalid_rows),
        "valid_count": len(valid_rows),
        "conflict_count": conflict_count,
        "empty_count": empty_count,
        "invalid_count": len(invalid_rows),
        "valid_rows": valid_rows,
        "invalid_rows": invalid_rows,
    }

  def preview_grade_import(
      self, teacher: User, assessment_id: int, filename: str, content: bytes
  ) -> Dict[str, Any]:
    """Memvalidasi file unggahan nilai dan menampilkan pratinjau beserta deteksi konflik nilai lama."""
    return self._parse_and_validate_grade_import(teacher, assessment_id, filename, content)

  def confirm_grade_import(
      self,
      teacher: User,
      assessment_id: int,
      filename: str,
      content: bytes,
      conflict_mode: str = "skip",
  ) -> Dict[str, Any]:
    """Menyimpan nilai hasil impor sesuai kebijakan konflik ('skip' | 'overwrite' | 'cancel')."""
    mode = conflict_mode.strip().lower()
    if mode not in ("skip", "overwrite", "cancel"):
      raise ValidationError("conflict_mode harus 'skip', 'overwrite', atau 'cancel'.")

    preview = self._parse_and_validate_grade_import(teacher, assessment_id, filename, content)
    if mode == "cancel" and preview["conflict_count"] > 0:
      return {
          "status": "cancelled",
          "inserted": 0,
          "updated": 0,
          "skipped": preview["valid_count"],
          "failed": preview["invalid_count"],
          "message": "Impor dibatalkan karena ditemukan nilai yang sudah ada.",
      }

    inserted = 0
    updated = 0
    skipped = 0
    failed = preview["invalid_count"]
    entries_to_save: List[Dict[str, Any]] = []

    for r in preview["valid_rows"]:
      if r["is_empty"]:
        skipped += 1
        continue
      if r["has_existing"]:
        if mode == "skip":
          skipped += 1
          continue
        updated += 1
      else:
        inserted += 1
      entries_to_save.append({
          "student_id": r["student_id"],
          "score": r["score"],
          "feedback": r["feedback"],
      })

    if entries_to_save:
      self.save_grades_bulk(
          teacher,
          assessment_id,
          entries_to_save,
          reason=f"Impor nilai Excel (mode={mode})",
      )

    return {
        "status": "completed",
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "assessment_status": preview["assessment"]["status"],
    }

  def list_materials(
      self, teacher: User, class_id: int, include_archived: bool = False
  ) -> List[LearningMaterial]:
    self._get_owned_class(teacher, class_id)
    return self._grade_repo.list_materials(class_id, include_archived=include_archived)

  def create_material(
      self,
      teacher: User,
      class_id: int,
      title: str,
      description: str = "",
      sort_order: Optional[int] = None,
  ) -> LearningMaterial:
    classroom = self._get_owned_class(teacher, class_id)
    if not title or not title.strip():
      raise ValidationError("Judul materi pembelajaran wajib diisi.")
    mat = self._grade_repo.create_material(
        class_id=class_id,
        period_id=classroom.period_id,
        teacher_id=teacher.id,
        title=title.strip(),
        description=description.strip(),
        sort_order=sort_order,
    )
    self._user_repo.log_audit(
        teacher.id, "create_material", "learning_material", mat.id, f"Kelas #{class_id}: {mat.title}"
    )
    return mat

  def update_material(
      self,
      teacher: User,
      material_id: int,
      title: Optional[str] = None,
      description: Optional[str] = None,
      sort_order: Optional[int] = None,
      is_archived: Optional[bool] = None,
  ) -> LearningMaterial:
    existing = self._grade_repo.get_material(material_id)
    if not existing:
      raise NotFoundError("Materi pembelajaran tidak ditemukan.")
    self._get_owned_class(teacher, existing.class_id)
    if title is not None and not title.strip():
      raise ValidationError("Judul materi pembelajaran tidak boleh kosong.")
    updated = self._grade_repo.update_material(
        material_id=material_id,
        title=title.strip() if title is not None else None,
        description=description.strip() if description is not None else None,
        sort_order=sort_order,
        is_archived=is_archived,
    )
    if updated is None:
      raise NotFoundError("Materi pembelajaran tidak ditemukan.")
    self._user_repo.log_audit(
        teacher.id, "update_material", "learning_material", material_id, f"title={updated.title}, archived={updated.is_archived}"
    )
    return updated

  def delete_material(self, teacher: User, material_id: int) -> None:
    existing = self._grade_repo.get_material(material_id)
    if not existing:
      raise NotFoundError("Materi pembelajaran tidak ditemukan.")
    self._get_owned_class(teacher, existing.class_id)
    cnt = self._grade_repo.count_assessments_for_material(material_id)
    if cnt > 0:
      raise ConflictError(
          f"Materi '{existing.title}' masih memiliki {cnt} kegiatan penilaian. "
          "Arsipkan materi ini agar nilai dan riwayat akademik peserta didik tidak terlepas."
      )
    self._grade_repo.delete_material(material_id)
    self._user_repo.log_audit(
        teacher.id, "delete_material", "learning_material", material_id, f"Materi '{existing.title}' dihapus."
    )
