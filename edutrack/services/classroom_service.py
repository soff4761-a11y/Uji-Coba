"""Layanan pengelolaan tahun pelajaran, semester, dan kelas oleh guru."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from edutrack.configs.app_config import AppConfig
from edutrack.domain.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from edutrack.domain.models import AcademicPeriod, CalculationMode, Classroom, Role, User
from edutrack.repositories.academic_repo import AcademicRepository
from edutrack.repositories.database import DatabaseIntegrityError
from edutrack.repositories.user_repo import UserRepository
from edutrack.services.auth_service import AuthService


class ClassroomService:
  """Mengelola siklus hidup periode akademik dan kelas dengan validasi kepemilikan."""

  def __init__(
      self,
      academic_repo: AcademicRepository,
      user_repo: UserRepository,
      config: AppConfig,
  ) -> None:
    self._academic_repo = academic_repo
    self._user_repo = user_repo
    self._config = config

  def create_period(
      self,
      teacher: User,
      name: str,
      academic_year: str,
      semester: str,
      is_active: bool = True,
  ) -> AcademicPeriod:
    """Membuat periode tahun pelajaran & semester baru milik guru."""
    AuthService.require_role(teacher, Role.TEACHER)
    if not name.strip() or not academic_year.strip() or not semester.strip():
      raise ValidationError("Nama periode, tahun pelajaran, dan semester wajib diisi.")
    period = self._academic_repo.create_period(
        teacher_id=teacher.id,
        name=name.strip(),
        academic_year=academic_year.strip(),
        semester=semester.strip(),
        is_active=is_active,
    )
    self._user_repo.log_audit(
        teacher.id, "create_period", "academic_period", period.id, period.name
    )
    return period

  def list_periods(
      self, teacher: User, include_archived: bool = True
  ) -> List[AcademicPeriod]:
    AuthService.require_role(teacher, Role.TEACHER)
    return self._academic_repo.list_periods(
        teacher.id, include_archived=include_archived
    )

  def update_period_state(
      self,
      teacher: User,
      period_id: int,
      is_active: Optional[bool] = None,
      is_archived: Optional[bool] = None,
  ) -> AcademicPeriod:
    AuthService.require_role(teacher, Role.TEACHER)
    existing = self._academic_repo.get_period(period_id)
    if not existing:
      raise NotFoundError("Periode akademik tidak ditemukan.")
    if existing.teacher_id != teacher.id:
      raise AuthorizationError("Anda tidak berwenang mengubah periode guru lain.")
    updated = self._academic_repo.set_period_state(
        period_id, teacher.id, is_active=is_active, is_archived=is_archived
    )
    if updated is None:
      raise NotFoundError("Periode akademik tidak ditemukan.")
    self._user_repo.log_audit(
        teacher.id,
        "update_period_state",
        "academic_period",
        period_id,
        f"active={updated.is_active}, archived={updated.is_archived}",
    )
    return updated

  def _resolve_or_create_default_period(self, teacher: User):
    periods = self._academic_repo.list_periods(teacher.id, include_archived=True)
    if periods:
      active = next((p for p in periods if p.is_active), None)
      return active or periods[0]
    return self._academic_repo.create_period(
        teacher_id=teacher.id,
        name="Umum",
        academic_year="-",
        semester="-",
        is_active=True,
    )

  def create_classroom(
      self,
      teacher: User,
      period_id: Optional[int] = None,
      name: str = "",
      education_level: str = "",
      academic_year: Optional[str] = None,
      description: str = "",
      calculation_mode: CalculationMode = CalculationMode.WEIGHTED,
      mastery_threshold: Optional[float] = None,
      allow_student_report_download: bool = True,
  ) -> Classroom:
    """Membuat kelas baru secara manual (periode opsional, otomatis dibuat jika kosong)."""
    AuthService.require_role(teacher, Role.TEACHER)
    if not name.strip() or not education_level.strip():
      raise ValidationError("Nama kelas dan tingkat pendidikan wajib diisi.")
    if period_id is None:
      period = self._resolve_or_create_default_period(teacher)
      period_id = period.id
    else:
      period = self._academic_repo.get_period(period_id)
      if not period:
        raise NotFoundError("Periode akademik tidak ditemukan.")
      if period.teacher_id != teacher.id:
        raise AuthorizationError("Anda tidak berwenang menggunakan periode guru lain.")

    threshold = (
        self._config.default_mastery_threshold
        if mastery_threshold is None
        else float(mastery_threshold)
    )
    if not (0.0 <= threshold <= 100.0):
      raise ValidationError("Kriteria ketuntasan (KKM) harus antara 0 dan 100.")

    classroom = self._academic_repo.create_classroom(
        teacher_id=teacher.id,
        period_id=period_id,
        name=name.strip(),
        education_level=education_level.strip(),
        academic_year=(academic_year or period.academic_year).strip(),
        description=description.strip(),
        calculation_mode=calculation_mode,
        mastery_threshold=threshold,
        allow_student_report_download=allow_student_report_download,
    )
    self._user_repo.log_audit(
        teacher.id, "create_classroom", "class", classroom.id, classroom.name
    )
    return classroom

  def get_owned_classroom(self, teacher: User, class_id: int) -> Classroom:
    """Mengambil kelas dan memvalidasi bahwa kelas benar-benar milik guru."""
    AuthService.require_role(teacher, Role.TEACHER)
    classroom = self._academic_repo.get_classroom(class_id)
    if not classroom:
      raise NotFoundError("Kelas tidak ditemukan.")
    if classroom.teacher_id != teacher.id:
      raise AuthorizationError("Akses ditolak: kelas ini bukan dalam kewenangan Anda.")
    return classroom

  def list_classrooms(
      self,
      teacher: User,
      period_id: Optional[int] = None,
      include_archived: bool = False,
  ) -> List[Classroom]:
    AuthService.require_role(teacher, Role.TEACHER)
    return self._academic_repo.list_classrooms(
        teacher.id, period_id=period_id, include_archived=include_archived
    )

  def update_classroom(
      self,
      teacher: User,
      class_id: int,
      name: Optional[str] = None,
      education_level: Optional[str] = None,
      academic_year: Optional[str] = None,
      description: Optional[str] = None,
      calculation_mode: Optional[CalculationMode] = None,
      mastery_threshold: Optional[float] = None,
      allow_student_report_download: Optional[bool] = None,
      is_archived: Optional[bool] = None,
  ) -> Classroom:
    self.get_owned_classroom(teacher, class_id)
    if name is not None and not name.strip():
      raise ValidationError("Nama kelas tidak boleh kosong.")
    if mastery_threshold is not None and not (0.0 <= mastery_threshold <= 100.0):
      raise ValidationError("Kriteria ketuntasan (KKM) harus antara 0 dan 100.")
    updated = self._academic_repo.update_classroom(
        class_id=class_id,
        name=name.strip() if name is not None else None,
        education_level=education_level.strip() if education_level is not None else None,
        academic_year=academic_year.strip() if academic_year is not None else None,
        description=description.strip() if description is not None else None,
        calculation_mode=calculation_mode,
        mastery_threshold=mastery_threshold,
        allow_student_report_download=allow_student_report_download,
        is_archived=is_archived,
    )
    if updated is None:
      raise NotFoundError("Kelas tidak ditemukan.")
    self._user_repo.log_audit(
        teacher.id,
        "update_classroom",
        "class",
        class_id,
        f"name={updated.name}, archived={updated.is_archived}",
    )
    return updated

  def get_classroom_dependencies(self, teacher: User, class_id: int) -> Dict[str, Any]:
    """Memeriksa relasi data kelas sebelum penghapusan agar data historis tetap terlindungi."""
    classroom = self.get_owned_classroom(teacher, class_id)
    counts = self._academic_repo.get_classroom_dependencies(class_id)
    has_related = any(counts.values())
    return {
        "class_id": classroom.id,
        "class_name": classroom.name,
        "is_archived": classroom.is_archived,
        "can_delete_safely": not has_related,
        "has_related_data": has_related,
        "counts": counts,
        "recommended_action": "archive" if has_related else "delete",
    }

  def delete_classroom(
      self,
      teacher: User,
      class_id: int,
      confirm_permanent: bool = False,
      force: bool = False,
  ) -> None:
    """Menghapus kelas secara aman dan atomik; menolak jika masih memiliki data terkait."""
    del force
    classroom = self.get_owned_classroom(teacher, class_id)
    if not confirm_permanent:
      raise ValidationError(
          "Konfirmasi penghapusan permanen (confirm_permanent=true) wajib diberikan."
      )
    counts = self._academic_repo.get_classroom_dependencies(class_id)
    if any(counts.values()):
      details = []
      if counts["students"]:
        details.append(f"{counts['students']} peserta didik")
      if counts["assessments"] or counts["grades"]:
        details.append(f"{counts['assessments']} penilaian / {counts['grades']} nilai")
      if counts["attendance_sessions"] or counts["attendance_records"]:
        details.append(f"{counts['attendance_sessions']} sesi / {counts['attendance_records']} catatan kehadiran")
      if counts["enrollments"] and not counts["students"]:
        details.append(f"{counts['enrollments']} riwayat kepindahan peserta didik")
      if counts.get("learning_materials"):
        details.append(f"{counts['learning_materials']} materi pembelajaran")
      if counts.get("announcements"):
        details.append(f"{counts['announcements']} pengumuman kelas")
      summary = ", ".join(details) if details else "data terkait lainnya"
      raise ConflictError(
          f"Kelas '{classroom.name}' tidak dapat dihapus permanen karena masih memiliki data terkait ({summary}). "
          "Gunakan fitur Arsipkan Kelas agar nilai dan riwayat kehadiran peserta didik tetap aman."
      )
    try:
      self._academic_repo.delete_classroom_atomic(class_id)
    except DatabaseIntegrityError as exc:
      raise ConflictError(
          f"Kelas '{classroom.name}' masih terhubung dengan data lain. Silakan arsipkan kelas ini."
      ) from exc
    self._user_repo.log_audit(
        teacher.id, "delete_classroom", "class", class_id, f"Kelas '{classroom.name}' dihapus permanen."
    )

  def reset_classroom_data(
      self,
      teacher: User,
      class_id: int,
      reset_grades: bool = True,
      reset_attendance: bool = True,
  ) -> Dict[str, int]:
    """Mereset data nilai dan/atau kehadiran pada kelas tertentu tanpa menghapus kelas maupun siswa."""
    classroom = self.get_owned_classroom(teacher, class_id)
    cleared_grades = 0
    cleared_attendance = 0
    with self._academic_repo._db.connection() as conn:  # pylint: disable=protected-access
      if reset_grades:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM grades WHERE assessment_id IN (SELECT id FROM assessments WHERE class_id = ?)",
            (class_id,),
        ).fetchone()
        cleared_grades = int(row["cnt"]) if row else 0
        conn.execute(
            "DELETE FROM correction_requests WHERE target_type = 'grade' AND target_id IN (SELECT id FROM assessments WHERE class_id = ?)",
            (class_id,),
        )
        conn.execute(
            "DELETE FROM grade_history WHERE assessment_id IN (SELECT id FROM assessments WHERE class_id = ?)",
            (class_id,),
        )
        conn.execute(
            "DELETE FROM grades WHERE assessment_id IN (SELECT id FROM assessments WHERE class_id = ?)",
            (class_id,),
        )
      if reset_attendance:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM attendance_records WHERE session_id IN (SELECT id FROM attendance_sessions WHERE class_id = ?)",
            (class_id,),
        ).fetchone()
        cleared_attendance = int(row["cnt"]) if row else 0
        conn.execute(
            """
            DELETE FROM correction_requests
            WHERE target_type = 'attendance'
              AND student_id IN (
                SELECT student_id FROM attendance_records
                WHERE session_id IN (SELECT id FROM attendance_sessions WHERE class_id = ?)
                UNION
                SELECT id FROM students WHERE current_class_id = ?
              )
            """,
            (class_id, class_id),
        )
        conn.execute(
            "DELETE FROM attendance_history WHERE session_id IN (SELECT id FROM attendance_sessions WHERE class_id = ?)",
            (class_id,),
        )
        conn.execute(
            "DELETE FROM attendance_records WHERE session_id IN (SELECT id FROM attendance_sessions WHERE class_id = ?)",
            (class_id,),
        )
        conn.execute("DELETE FROM attendance_sessions WHERE class_id = ?", (class_id,))
    self._user_repo.log_audit(
        teacher.id,
        "reset_classroom_data",
        "class",
        class_id,
        f"Reset kelas '{classroom.name}': nilai={cleared_grades}, kehadiran={cleared_attendance}",
    )
    return {
        "cleared_grades": cleared_grades,
        "cleared_attendance": cleared_attendance,
    }

  # --- Papan Pengumuman Kelas (Permanen, Searah Guru -> Siswa) ---

  _ALLOWED_ANNOUNCEMENT_CATEGORIES = frozenset({
      "Jadwal Ujian",
      "Perubahan Materi",
      "Tenggat Tugas",
      "Umum",
  })

  def list_announcements(self, teacher: User, class_id: int) -> List[ClassAnnouncement]:
    self.get_owned_classroom(teacher, class_id)
    return self._academic_repo.list_announcements(class_id)

  def list_announcements_for_student(self, student_user: User) -> List[ClassAnnouncement]:
    AuthService.require_role(student_user, Role.STUDENT)
    profile = self._academic_repo.get_student_by_user_id(student_user.id)
    if not profile:
      raise NotFoundError("Profil peserta didik tidak ditemukan.")
    return self._academic_repo.list_announcements(profile.current_class_id)

  def create_announcement(
      self,
      teacher: User,
      class_id: int,
      title: str,
      content: str,
      category: str = "Umum",
      is_pinned: bool = False,
  ) -> ClassAnnouncement:
    cls = self.get_owned_classroom(teacher, class_id)
    clean_title = (title or "").strip()
    clean_content = (content or "").strip()
    clean_cat = (category or "Umum").strip()
    if not clean_title or len(clean_title) > 150:
      raise ValidationError("Judul pengumuman wajib diisi (maksimal 150 karakter).")
    if not clean_content or len(clean_content) > 4000:
      raise ValidationError("Isi pengumuman wajib diisi (maksimal 4000 karakter).")
    if clean_cat not in self._ALLOWED_ANNOUNCEMENT_CATEGORIES:
      raise ValidationError("Kategori pengumuman harus: Jadwal Ujian, Perubahan Materi, Tenggat Tugas, atau Umum.")
    ann = self._academic_repo.create_announcement(
        class_id=cls.id,
        teacher_id=teacher.id,
        title=clean_title,
        content=clean_content,
        category=clean_cat,
        is_pinned=is_pinned,
    )
    self._user_repo.log_audit(
        teacher.id, "create_announcement", "class_announcement", ann.id,
        f"Pengumuman '{ann.title}' dibuat pada kelas '{cls.name}'.",
    )
    return ann

  def update_announcement(
      self,
      teacher: User,
      announcement_id: int,
      title: Optional[str] = None,
      category: Optional[str] = None,
      content: Optional[str] = None,
      is_pinned: Optional[bool] = None,
  ) -> ClassAnnouncement:
    AuthService.require_role(teacher, Role.TEACHER)
    existing = self._academic_repo.get_announcement(announcement_id)
    if not existing:
      raise NotFoundError("Pengumuman tidak ditemukan.")
    self.get_owned_classroom(teacher, existing.class_id)

    clean_title = title.strip() if title is not None else None
    if clean_title is not None and (not clean_title or len(clean_title) > 150):
      raise ValidationError("Judul pengumuman wajib diisi (maksimal 150 karakter).")
    clean_content = content.strip() if content is not None else None
    if clean_content is not None and (not clean_content or len(clean_content) > 4000):
      raise ValidationError("Isi pengumuman wajib diisi (maksimal 4000 karakter).")
    clean_cat = category.strip() if category is not None else None
    if clean_cat is not None and clean_cat not in self._ALLOWED_ANNOUNCEMENT_CATEGORIES:
      raise ValidationError("Kategori pengumuman tidak valid.")

    updated = self._academic_repo.update_announcement(
        announcement_id,
        title=clean_title,
        category=clean_cat,
        content=clean_content,
        is_pinned=is_pinned,
    )
    if not updated:
      raise NotFoundError("Pengumuman tidak ditemukan.")
    self._user_repo.log_audit(
        teacher.id, "update_announcement", "class_announcement", announcement_id,
        f"Pengumuman '{updated.title}' diperbarui.",
    )
    return updated

  def delete_announcement(self, teacher: User, announcement_id: int) -> None:
    AuthService.require_role(teacher, Role.TEACHER)
    existing = self._academic_repo.get_announcement(announcement_id)
    if not existing:
      raise NotFoundError("Pengumuman tidak ditemukan.")
    self.get_owned_classroom(teacher, existing.class_id)
    self._academic_repo.delete_announcement(announcement_id)
    self._user_repo.log_audit(
        teacher.id, "delete_announcement", "class_announcement", announcement_id,
        f"Pengumuman '{existing.title}' dihapus.",
    )
