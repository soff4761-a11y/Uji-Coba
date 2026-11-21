"""Layanan pencatatan kehadiran, rekap otomatis, audit kehadiran, dan permintaan koreksi."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, List, Optional, Sequence

from edutrack.configs.app_config import AppConfig
from edutrack.domain.attendance_calc import summarize_attendance
from edutrack.domain.errors import AuthorizationError, NotFoundError, ValidationError
from edutrack.domain.models import (
    AttendanceSession,
    AttendanceStatus,
    CorrectionStatus,
    Role,
    User,
)
from edutrack.repositories.academic_repo import AcademicRepository
from edutrack.repositories.attendance_repo import AttendanceRepository
from edutrack.repositories.grade_repo import GradeRepository
from edutrack.repositories.user_repo import UserRepository
from edutrack.services.auth_service import AuthService


class AttendanceService:
  """Mengelola sesi pertemuan, pencatatan presensi anti-duplikasi, dan koreksi."""

  def __init__(
      self,
      attendance_repo: AttendanceRepository,
      academic_repo: AcademicRepository,
      grade_repo: GradeRepository,
      user_repo: UserRepository,
      config: AppConfig,
  ) -> None:
    self._attendance_repo = attendance_repo
    self._academic_repo = academic_repo
    self._grade_repo = grade_repo
    self._user_repo = user_repo
    self._config = config

  def _get_owned_class(self, teacher: User, class_id: int):
    AuthService.require_role(teacher, Role.TEACHER)
    classroom = self._academic_repo.get_classroom(class_id)
    if not classroom:
      raise NotFoundError("Kelas tidak ditemukan.")
    if classroom.teacher_id != teacher.id:
      raise AuthorizationError("Akses ditolak: kelas ini bukan milik Anda.")
    return classroom

  def _get_owned_session(self, teacher: User, session_id: int) -> AttendanceSession:
    AuthService.require_role(teacher, Role.TEACHER)
    session = self._attendance_repo.get_session(session_id)
    if not session:
      raise NotFoundError("Sesi pertemuan tidak ditemukan.")
    self._get_owned_class(teacher, session.class_id)
    return session

  @staticmethod
  def _validate_iso_date(raw_date: str) -> str:
    clean = (raw_date or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", clean):
      raise ValidationError("Tanggal pertemuan wajib berformat YYYY-MM-DD yang valid.")
    try:
      datetime.strptime(clean, "%Y-%m-%d")
    except ValueError as exc:
      raise ValidationError("Tanggal pertemuan wajib berformat YYYY-MM-DD yang valid.") from exc
    return clean

  def create_session(
      self,
      teacher: User,
      class_id: int,
      session_date: str,
      meeting_number: int,
      topic: str = "",
      mark_all_present: bool = False,
  ) -> Dict[str, Any]:
    """Membuat sesi pertemuan baru dan opsional langsung menandai semua hadir."""
    classroom = self._get_owned_class(teacher, class_id)
    clean_date = self._validate_iso_date(session_date)
    if meeting_number < 1:
      raise ValidationError("Nomor pertemuan minimal 1.")

    session = self._attendance_repo.create_session(
        class_id=class_id,
        period_id=classroom.period_id,
        session_date=clean_date,
        meeting_number=int(meeting_number),
        topic=topic.strip(),
        created_by=teacher.id,
    )

    records: List[Dict[str, Any]] = []
    if mark_all_present:
      students = self._academic_repo.list_students(teacher.id, class_id=class_id)
      for stu in students:
        rec = self._attendance_repo.upsert_record(
            session_id=session.id,
            student_id=stu.id,
            status=AttendanceStatus.HADIR,
            note="",
            actor_user_id=teacher.id,
            reason="Tandai semua hadir otomatis",
        )
        records.append(rec)

    self._user_repo.log_audit(
        teacher.id,
        "create_attendance_session",
        "attendance_session",
        session.id,
        f"Kelas #{class_id}, tanggal {session.session_date}, pertemuan #{session.meeting_number}",
    )
    return {"session": session, "records": records}

  def list_sessions(
      self,
      teacher: User,
      class_id: int,
      date_from: Optional[str] = None,
      date_to: Optional[str] = None,
  ) -> List[AttendanceSession]:
    self._get_owned_class(teacher, class_id)
    return self._attendance_repo.list_sessions(
        class_id, date_from=date_from, date_to=date_to
    )

  def get_session_detail(self, teacher: User, session_id: int) -> Dict[str, Any]:
    session = self._get_owned_session(teacher, session_id)
    students = self._academic_repo.list_students(teacher.id, class_id=session.class_id)
    existing_records = self._attendance_repo.list_records_for_session(session_id)
    by_student = {int(r["student_id"]): r for r in existing_records}

    roster = []
    for stu in students:
      rec = by_student.get(stu.id)
      roster.append({
          "student_id": stu.id,
          "student_code": stu.student_code,
          "full_name": stu.full_name,
          "status": rec["status"] if rec else None,
          "note": rec["note"] if rec else "",
          "updated_at": rec["updated_at"] if rec else None,
      })
    return {"session": session, "records": roster}

  def save_session_attendance(
      self,
      teacher: User,
      session_id: int,
      entries: Sequence[Dict[str, Any]],
      reason: str = "",
  ) -> List[Dict[str, Any]]:
    """Menyimpan atau mengoreksi kehadiran peserta didik pada sesi tertentu."""
    self._get_owned_session(teacher, session_id)
    saved: List[Dict[str, Any]] = []
    for entry in entries:
      student_id = int(entry["student_id"])
      student = self._academic_repo.get_student(student_id)
      if not student or student.teacher_id != teacher.id:
        raise AuthorizationError(
            f"Peserta didik #{student_id} bukan dalam kewenangan Anda."
        )
      try:
        status = AttendanceStatus(str(entry["status"]).lower().strip())
      except (KeyError, ValueError) as exc:
        raise ValidationError(
            f"Status kehadiran tidak valid untuk peserta didik #{student_id}."
        ) from exc
      note = str(entry.get("note") or "").strip()
      rec = self._attendance_repo.upsert_record(
          session_id=session_id,
          student_id=student_id,
          status=status,
          note=note,
          actor_user_id=teacher.id,
          reason=reason,
      )
      saved.append(rec)

    self._user_repo.log_audit(
        teacher.id,
        "save_attendance",
        "attendance_session",
        session_id,
        f"{len(saved)} catatan kehadiran diperbarui.",
    )
    return saved

  def update_session(
      self,
      teacher: User,
      session_id: int,
      session_date: Optional[str] = None,
      meeting_number: Optional[int] = None,
      topic: Optional[str] = None,
  ) -> AttendanceSession:
    """Mengubah tanggal, nomor pertemuan, atau topik sesi kehadiran."""
    self._get_owned_session(teacher, session_id)
    clean_date = self._validate_iso_date(session_date) if session_date is not None else None
    if meeting_number is not None and int(meeting_number) < 1:
      raise ValidationError("Nomor pertemuan minimal 1.")
    updated = self._attendance_repo.update_session(
        session_id=session_id,
        session_date=clean_date,
        meeting_number=meeting_number,
        topic=topic,
    )
    if not updated:
      raise NotFoundError("Sesi pertemuan tidak ditemukan.")
    self._user_repo.log_audit(
        teacher.id,
        "update_attendance_session",
        "attendance_session",
        session_id,
        f"tanggal={updated.session_date}, pertemuan=#{updated.meeting_number}, topik={updated.topic}",
    )
    return updated

  def delete_session(self, teacher: User, session_id: int) -> None:
    """Menghapus sesi kehadiran beserta catatan presensinya."""
    session = self._get_owned_session(teacher, session_id)
    self._attendance_repo.delete_session(session_id)
    self._user_repo.log_audit(
        teacher.id,
        "delete_attendance_session",
        "attendance_session",
        session_id,
        f"Sesi #{session.meeting_number} ({session.session_date}) dihapus.",
    )

  def delete_all_sessions_for_class(self, teacher: User, class_id: int) -> int:
    """Menghapus permanen seluruh sesi pertemuan beserta catatan kehadiran pada suatu kelas."""
    cls = self._get_owned_class(teacher, class_id)
    deleted = self._attendance_repo.delete_all_sessions_for_class(cls.id)
    self._user_repo.log_audit(
        teacher.id,
        "delete_all_attendance_sessions",
        "classroom",
        cls.id,
        f"{deleted} sesi pertemuan di kelas {cls.name} dihapus permanen.",
    )
    return deleted

  def reset_session(self, teacher: User, session_id: int) -> int:
    """Mereset seluruh catatan kehadiran pada sesi tertentu agar bisa diisi ulang."""
    self._get_owned_session(teacher, session_id)
    cleared = self._attendance_repo.reset_session_records(session_id)
    self._user_repo.log_audit(
        teacher.id,
        "reset_attendance_session",
        "attendance_session",
        session_id,
        f"{cleared} catatan kehadiran direset.",
    )
    return cleared

  def mark_all_present(self, teacher: User, session_id: int) -> List[Dict[str, Any]]:
    """Menandai seluruh peserta didik di kelas sesi tersebut sebagai hadir."""
    session = self._get_owned_session(teacher, session_id)
    students = self._academic_repo.list_students(teacher.id, class_id=session.class_id)
    entries = [
        {"student_id": stu.id, "status": AttendanceStatus.HADIR.value, "note": ""}
        for stu in students
    ]
    return self.save_session_attendance(
        teacher, session_id, entries, reason="Tandai semua hadir"
    )

  def list_attendance_history(
      self, teacher: User, class_id: int
  ) -> List[Dict[str, Any]]:
    self._get_owned_class(teacher, class_id)
    return self._attendance_repo.list_attendance_history(class_id=class_id)

  def get_student_attendance(
      self,
      student_user: User,
      month: Optional[str] = None,
      period_id: Optional[int] = None,
      date_from: Optional[str] = None,
      date_to: Optional[str] = None,
  ) -> Dict[str, Any]:
    """Mengembalikan riwayat & rekap kehadiran khusus milik peserta didik sendiri."""
    AuthService.require_role(student_user, Role.STUDENT)
    profile = self._academic_repo.get_student_by_user_id(student_user.id)
    if not profile:
      raise NotFoundError("Profil peserta didik tidak ditemukan.")

    records = self._attendance_repo.list_records_for_student(
        student_id=profile.id,
        month=month,
        period_id=period_id,
        date_from=date_from,
        date_to=date_to,
    )
    summary = summarize_attendance(
        [r["status"] for r in records],
        high_absence_threshold_pct=self._config.high_absence_threshold_pct,
    )
    return {"student": profile, "summary": summary, "records": records}

  # --- Student Correction Requests ---

  def submit_correction_request(
      self,
      student_user: User,
      target_type: str,
      target_id: int,
      message: str,
  ) -> Dict[str, Any]:
    """Mengajukan permintaan koreksi nilai/kehadiran oleh peserta didik tanpa mengubah data."""
    AuthService.require_role(student_user, Role.STUDENT)
    profile = self._academic_repo.get_student_by_user_id(student_user.id)
    if not profile:
      raise NotFoundError("Profil peserta didik tidak ditemukan.")

    clean_type = target_type.strip().lower()
    if clean_type not in ("grade", "attendance"):
      raise ValidationError("target_type harus 'grade' atau 'attendance'.")
    if not message or len(message.strip()) < 5:
      raise ValidationError("Pesan permintaan koreksi minimal 5 karakter.")

    # Validasi target benar-benar berada dalam ruang lingkup kelas/data peserta didik.
    if clean_type == "grade":
      asmt = self._grade_repo.get_assessment(target_id)
      if not asmt or asmt.status.value != "published":
        raise NotFoundError("Penilaian tidak ditemukan atau belum dipublikasikan.")
      cls = self._academic_repo.get_classroom(asmt.class_id)
      if not cls or cls.teacher_id != profile.teacher_id:
        raise AuthorizationError("Penilaian tidak terkait dengan akun Anda.")
    else:
      records = self._attendance_repo.list_records_for_student(profile.id)
      if not any(int(r["id"]) == target_id or int(r["session_id"]) == target_id for r in records):
        raise NotFoundError("Catatan kehadiran tidak ditemukan pada riwayat Anda.")

    req = self._attendance_repo.create_correction_request(
        student_id=profile.id,
        teacher_id=profile.teacher_id,
        target_type=clean_type,
        target_id=target_id,
        message=message.strip(),
    )
    self._user_repo.log_audit(
        student_user.id,
        "submit_correction_request",
        "correction_request",
        req["id"],
        f"{clean_type} #{target_id}",
    )
    return req

  def list_student_corrections(self, student_user: User) -> List[Dict[str, Any]]:
    AuthService.require_role(student_user, Role.STUDENT)
    profile = self._academic_repo.get_student_by_user_id(student_user.id)
    if not profile:
      raise NotFoundError("Profil peserta didik tidak ditemukan.")
    return self._attendance_repo.list_correction_requests_for_student(profile.id)

  def list_teacher_corrections(
      self, teacher: User, status: Optional[CorrectionStatus] = None
  ) -> List[Dict[str, Any]]:
    AuthService.require_role(teacher, Role.TEACHER)
    return self._attendance_repo.list_correction_requests_for_teacher(
        teacher.id, status=status
    )

  def respond_correction_request(
      self,
      teacher: User,
      request_id: int,
      status: CorrectionStatus,
      teacher_response: str,
  ) -> Dict[str, Any]:
    AuthService.require_role(teacher, Role.TEACHER)
    updated = self._attendance_repo.update_correction_request(
        request_id=request_id,
        teacher_id=teacher.id,
        status=status,
        teacher_response=teacher_response.strip(),
    )
    if not updated:
      raise NotFoundError("Permintaan koreksi tidak ditemukan.")
    self._user_repo.log_audit(
        teacher.id,
        "respond_correction_request",
        "correction_request",
        request_id,
        f"status={status.value}",
    )
    return updated

  def delete_teacher_correction(self, teacher: User, request_id: int) -> Dict[str, Any]:
    """Menghapus permanen catatan permintaan koreksi oleh guru pemilik."""
    AuthService.require_role(teacher, Role.TEACHER)
    outcome = self._attendance_repo.delete_teacher_correction(request_id, teacher.id)
    if outcome == "not_found":
      raise NotFoundError("Permintaan koreksi tidak ditemukan.")
    if outcome == "forbidden":
      raise AuthorizationError("Anda tidak berwenang menghapus permintaan koreksi milik guru lain.")
    self._user_repo.log_audit(
        teacher.id,
        "delete_teacher_correction",
        "correction_request",
        request_id,
        "outcome=deleted",
    )
    return {"status": "deleted", "message": "Catatan permintaan koreksi berhasil dihapus."}

  def delete_student_correction(self, student_user: User, request_id: int) -> Dict[str, Any]:
    """Menghapus permintaan koreksi milik siswa (pending -> hapus, diproses -> sembunyikan tanpa hapus catatan guru)."""
    AuthService.require_role(student_user, Role.STUDENT)
    profile = self._academic_repo.get_student_by_user_id(student_user.id)
    if not profile:
      raise NotFoundError("Profil peserta didik tidak ditemukan.")
    outcome = self._attendance_repo.delete_or_hide_student_correction(request_id, profile.id)
    if outcome == "not_found":
      raise NotFoundError("Permintaan koreksi tidak ditemukan.")
    if outcome == "forbidden":
      raise AuthorizationError("Anda tidak berwenang menghapus permintaan koreksi milik peserta didik lain.")
    self._user_repo.log_audit(
        student_user.id,
        "delete_student_correction",
        "correction_request",
        request_id,
        f"outcome={outcome}",
    )
    msg = (
        "Permintaan koreksi berhasil dihapus."
        if outcome == "deleted"
        else "Riwayat permintaan koreksi disembunyikan dari dashboard Anda (catatan tindak lanjut guru tetap terjaga)."
    )
    return {"status": outcome, "message": msg}

  def get_student_alpa_counts(self, teacher: User, class_id: int) -> Dict[int, int]:
    """Menghitung jumlah ketidakhadiran tanpa keterangan (alpa) per peserta didik pada satu kelas."""
    self._get_owned_class(teacher, class_id)
    records = self._attendance_repo.list_records_for_class(class_id)
    counts: Dict[int, int] = {}
    for rec in records:
      if str(rec["status"]) == "alpa":
        sid = int(rec["student_id"])
        counts[sid] = counts.get(sid, 0) + 1
    return counts
