"""Repositori periode akademik, kelas, peserta didik, dan riwayat perpindahan kelas."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from edutrack.domain.errors import ConflictError
from edutrack.domain.models import (
    AcademicPeriod,
    AccountStatus,
    CalculationMode,
    ClassAnnouncement,
  Classroom,
    StudentProfile,
)
from edutrack.repositories.database import Database, DatabaseIntegrityError, utc_now_iso


class AcademicRepository:
  """Akses data persisten untuk periode, kelas, peserta didik, dan enrollment."""

  def __init__(self, db: Database) -> None:
    self._db = db

  @staticmethod
  def _row_to_period(row: sqlite3.Row) -> AcademicPeriod:
    return AcademicPeriod(
        id=int(row["id"]),
        teacher_id=int(row["teacher_id"]),
        name=str(row["name"]),
        academic_year=str(row["academic_year"]),
        semester=str(row["semester"]),
        is_active=bool(row["is_active"]),
        is_archived=bool(row["is_archived"]),
        created_at=str(row["created_at"]),
    )

  @staticmethod
  def _row_to_classroom(row: sqlite3.Row) -> Classroom:
    return Classroom(
        id=int(row["id"]),
        teacher_id=int(row["teacher_id"]),
        period_id=int(row["period_id"]),
        name=str(row["name"]),
        education_level=str(row["education_level"]),
        academic_year=str(row["academic_year"]),
        description=str(row["description"]),
        calculation_mode=CalculationMode(row["calculation_mode"]),
        mastery_threshold=float(row["mastery_threshold"]),
        allow_student_report_download=bool(row["allow_student_report_download"]),
        is_archived=bool(row["is_archived"]),
        created_at=str(row["created_at"]),
    )

  @staticmethod
  def _row_to_student(row: sqlite3.Row) -> StudentProfile:
    return StudentProfile(
        id=int(row["id"]),
        user_id=int(row["user_id"]),
        teacher_id=int(row["teacher_id"]),
        current_class_id=int(row["current_class_id"]),
        student_code=str(row["student_code"]),
        full_name=str(row["full_name"]),
        username=str(row["username"]),
        account_status=AccountStatus(row["account_status"]),
        notes=str(row["notes"]),
        created_at=str(row["created_at"]),
    )

  # --- Academic Periods ---

  def create_period(
      self,
      teacher_id: int,
      name: str,
      academic_year: str,
      semester: str,
      is_active: bool = True,
  ) -> AcademicPeriod:
    """Membuat periode tahun pelajaran dan semester baru."""
    now = utc_now_iso()
    try:
      with self._db.connection() as conn:
        if is_active:
          conn.execute(
              "UPDATE academic_periods SET is_active = ? WHERE teacher_id = ?",
              (self._db.bool_val(False), teacher_id),
          )
        cur = conn.execute(
            """
            INSERT INTO academic_periods (
              teacher_id, name, academic_year, semester, is_active, is_archived, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (teacher_id, name, academic_year, semester, self._db.bool_val(is_active), self._db.bool_val(False), now),
        )
        row = conn.execute(
            "SELECT * FROM academic_periods WHERE id = ?", (int(cur.lastrowid),)
        ).fetchone()
    except DatabaseIntegrityError as exc:
      raise ConflictError(
          f"Periode {academic_year} ({semester}) sudah ada."
      ) from exc
    return self._row_to_period(row)

  def list_periods(
      self, teacher_id: int, include_archived: bool = True
  ) -> List[AcademicPeriod]:
    """Mengembalikan daftar periode milik guru."""
    with self._db.connection() as conn:
      if include_archived:
        rows = conn.execute(
            "SELECT * FROM academic_periods WHERE teacher_id = ? ORDER BY is_active DESC, id DESC",
            (teacher_id,),
        ).fetchall()
      else:
        rows = conn.execute(
            """
            SELECT * FROM academic_periods
            WHERE teacher_id = ? AND is_archived = ?
            ORDER BY is_active DESC, id DESC
            """,
            (teacher_id, self._db.bool_val(False)),
        ).fetchall()
    return [self._row_to_period(r) for r in rows]

  def get_period(self, period_id: int) -> Optional[AcademicPeriod]:
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT * FROM academic_periods WHERE id = ?", (period_id,)
      ).fetchone()
    return self._row_to_period(row) if row else None

  def set_period_state(
      self,
      period_id: int,
      teacher_id: int,
      is_active: Optional[bool] = None,
      is_archived: Optional[bool] = None,
  ) -> Optional[AcademicPeriod]:
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT * FROM academic_periods WHERE id = ? AND teacher_id = ?",
          (period_id, teacher_id),
      ).fetchone()
      if not row:
        return None
      if is_active:
        conn.execute(
            "UPDATE academic_periods SET is_active = ? WHERE teacher_id = ?",
            (self._db.bool_val(False), teacher_id),
        )
      next_active_b = bool(is_active) if is_active is not None else bool(row["is_active"])
      next_archived_b = bool(is_archived) if is_archived is not None else bool(row["is_archived"])
      if next_archived_b:
        next_active_b = False
      next_active = self._db.bool_val(next_active_b)
      next_archived = self._db.bool_val(next_archived_b)
      conn.execute(
          "UPDATE academic_periods SET is_active = ?, is_archived = ? WHERE id = ?",
          (next_active, next_archived, period_id),
      )
      updated = conn.execute(
          "SELECT * FROM academic_periods WHERE id = ?", (period_id,)
      ).fetchone()
    return self._row_to_period(updated)

  # --- Classrooms ---

  def create_classroom(
      self,
      teacher_id: int,
      period_id: int,
      name: str,
      education_level: str,
      academic_year: str,
      description: str = "",
      calculation_mode: CalculationMode = CalculationMode.WEIGHTED,
      mastery_threshold: float = 75.0,
      allow_student_report_download: bool = True,
  ) -> Classroom:
    now = utc_now_iso()
    with self._db.connection() as conn:
      cur = conn.execute(
          """
          INSERT INTO classes (
            teacher_id, period_id, name, education_level, academic_year,
            description, calculation_mode, mastery_threshold,
            allow_student_report_download, is_archived, created_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          """,
          (
              teacher_id,
              period_id,
              name,
              education_level,
              academic_year,
              description,
              calculation_mode.value,
              mastery_threshold,
              self._db.bool_val(allow_student_report_download),
              self._db.bool_val(False),
              now,
          ),
      )
      row = conn.execute(
          "SELECT * FROM classes WHERE id = ?", (int(cur.lastrowid),)
      ).fetchone()
    return self._row_to_classroom(row)

  def get_classroom(self, class_id: int) -> Optional[Classroom]:
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT * FROM classes WHERE id = ?", (class_id,)
      ).fetchone()
    return self._row_to_classroom(row) if row else None

  def list_classrooms(
      self,
      teacher_id: int,
      period_id: Optional[int] = None,
      include_archived: bool = False,
  ) -> List[Classroom]:
    clauses = ["teacher_id = ?"]
    params: List[Any] = [teacher_id]
    if period_id is not None:
      clauses.append("period_id = ?")
      params.append(period_id)
    if not include_archived:
      clauses.append("is_archived = ?")
      params.append(self._db.bool_val(False))
    query = f"SELECT * FROM classes WHERE {' AND '.join(clauses)} ORDER BY is_archived ASC, id DESC"
    with self._db.connection() as conn:
      rows = conn.execute(query, params).fetchall()
    return [self._row_to_classroom(r) for r in rows]

  def update_classroom(
      self,
      class_id: int,
      name: Optional[str] = None,
      education_level: Optional[str] = None,
      academic_year: Optional[str] = None,
      description: Optional[str] = None,
      calculation_mode: Optional[CalculationMode] = None,
      mastery_threshold: Optional[float] = None,
      allow_student_report_download: Optional[bool] = None,
      is_archived: Optional[bool] = None,
  ) -> Optional[Classroom]:
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT * FROM classes WHERE id = ?", (class_id,)
      ).fetchone()
      if not row:
        return None
      conn.execute(
          """
          UPDATE classes
          SET name = ?, education_level = ?, academic_year = ?, description = ?,
              calculation_mode = ?, mastery_threshold = ?,
              allow_student_report_download = ?, is_archived = ?
          WHERE id = ?
          """,
          (
              name if name is not None else row["name"],
              education_level if education_level is not None else row["education_level"],
              academic_year if academic_year is not None else row["academic_year"],
              description if description is not None else row["description"],
              (
                  calculation_mode.value
                  if calculation_mode is not None
                  else row["calculation_mode"]
              ),
              (
                  mastery_threshold
                  if mastery_threshold is not None
                  else row["mastery_threshold"]
              ),
              (
                  (self._db.bool_val(allow_student_report_download))
                  if allow_student_report_download is not None
                  else row["allow_student_report_download"]
              ),
              (
                  (self._db.bool_val(is_archived))
                  if is_archived is not None
                  else row["is_archived"]
              ),
              class_id,
          ),
      )
      updated = conn.execute(
          "SELECT * FROM classes WHERE id = ?", (class_id,)
      ).fetchone()
    return self._row_to_classroom(updated)

  def get_classroom_dependencies(self, class_id: int) -> Dict[str, int]:
    """Menghitung seluruh entitas yang terhubung ke kelas secara akurat."""
    with self._db.connection() as conn:
      students_cnt = int(
          conn.execute(
              "SELECT COUNT(*) AS cnt FROM students WHERE current_class_id = ?", (class_id,)
          ).fetchone()["cnt"]
      )
      enrollments_cnt = int(
          conn.execute(
              "SELECT COUNT(*) AS cnt FROM student_enrollments WHERE class_id = ?", (class_id,)
          ).fetchone()["cnt"]
      )
      assessments_cnt = int(
          conn.execute(
              "SELECT COUNT(*) AS cnt FROM assessments WHERE class_id = ?", (class_id,)
          ).fetchone()["cnt"]
      )
      grades_cnt = int(
          conn.execute(
              "SELECT COUNT(*) AS cnt FROM grades WHERE assessment_id IN (SELECT id FROM assessments WHERE class_id = ?)",
              (class_id,),
          ).fetchone()["cnt"]
      )
      att_sessions_cnt = int(
          conn.execute(
              "SELECT COUNT(*) AS cnt FROM attendance_sessions WHERE class_id = ?", (class_id,)
          ).fetchone()["cnt"]
      )
      att_records_cnt = int(
          conn.execute(
              "SELECT COUNT(*) AS cnt FROM attendance_records WHERE session_id IN (SELECT id FROM attendance_sessions WHERE class_id = ?)",
              (class_id,),
          ).fetchone()["cnt"]
      )
      materials_cnt = int(
          conn.execute(
              "SELECT COUNT(*) AS cnt FROM learning_materials WHERE class_id = ?", (class_id,)
          ).fetchone()["cnt"]
      )
      announcements_cnt = int(
          conn.execute(
              "SELECT COUNT(*) AS cnt FROM class_announcements WHERE class_id = ?", (class_id,)
          ).fetchone()["cnt"]
      )
    return {
        "students": students_cnt,
        "learning_materials": materials_cnt,
        "enrollments": enrollments_cnt,
        "assessments": assessments_cnt,
        "grades": grades_cnt,
        "attendance_sessions": att_sessions_cnt,
        "attendance_records": att_records_cnt,
    }

  def delete_classroom_atomic(self, class_id: int) -> None:
    """Menghapus kelas secara atomik dalam satu transaksi apabila tidak memiliki data terkait."""
    with self._db.connection() as conn:
      conn.execute("DELETE FROM classes WHERE id = ?", (class_id,))

  def delete_classroom(self, class_id: int) -> None:
    with self._db.connection() as conn:
      conn.execute("DELETE FROM classes WHERE id = ?", (class_id,))

  # --- Students & Enrollments ---

  def create_student(
      self,
      user_id: int,
      teacher_id: int,
      class_id: int,
      student_code: str,
      full_name: str,
      notes: str = "",
  ) -> StudentProfile:
    now = utc_now_iso()
    try:
      with self._db.connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO students (
              user_id, teacher_id, current_class_id, student_code, full_name, notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, teacher_id, class_id, student_code, full_name, notes, now),
        )
        student_id = int(cur.lastrowid)
        conn.execute(
            """
            INSERT INTO student_enrollments (student_id, class_id, enrolled_at)
            VALUES (?, ?, ?)
            """,
            (student_id, class_id, now),
        )
        row = conn.execute(
            """
            SELECT s.*, u.username, u.status AS account_status
            FROM students s
            JOIN users u ON u.id = s.user_id
            WHERE s.id = ?
            """,
            (student_id,),
        ).fetchone()
    except DatabaseIntegrityError as exc:
      raise ConflictError(
          f"Nomor induk/identitas '{student_code}' sudah terdaftar."
      ) from exc
    return self._row_to_student(row)

  def get_student(self, student_id: int) -> Optional[StudentProfile]:
    with self._db.connection() as conn:
      row = conn.execute(
          """
          SELECT s.*, u.username, u.status AS account_status
          FROM students s
          JOIN users u ON u.id = s.user_id
          WHERE s.id = ?
          """,
          (student_id,),
      ).fetchone()
    return self._row_to_student(row) if row else None

  def get_student_by_user_id(self, user_id: int) -> Optional[StudentProfile]:
    with self._db.connection() as conn:
      row = conn.execute(
          """
          SELECT s.*, u.username, u.status AS account_status
          FROM students s
          JOIN users u ON u.id = s.user_id
          WHERE s.user_id = ?
          """,
          (user_id,),
      ).fetchone()
    return self._row_to_student(row) if row else None

  def list_students(
      self,
      teacher_id: int,
      class_id: Optional[int] = None,
      status: Optional[AccountStatus] = None,
      search: Optional[str] = None,
  ) -> List[StudentProfile]:
    clauses = ["s.teacher_id = ?"]
    params: List[Any] = [teacher_id]
    if class_id is not None:
      clauses.append("s.current_class_id = ?")
      params.append(class_id)
    if status is not None:
      clauses.append("u.status = ?")
      params.append(status.value)
    if search and search.strip():
      term = f"%{search.strip()}%"
      clauses.append(
          "(LOWER(s.full_name) LIKE LOWER(?) OR LOWER(s.student_code) LIKE LOWER(?) OR LOWER(u.username) LIKE LOWER(?))"
      )
      params.extend([term, term, term])
    query = f"""
      SELECT s.*, u.username, u.status AS account_status
      FROM students s
      JOIN users u ON u.id = s.user_id
      WHERE {' AND '.join(clauses)}
      ORDER BY s.full_name ASC
    """
    with self._db.connection() as conn:
      rows = conn.execute(query, params).fetchall()
    return [self._row_to_student(r) for r in rows]

  def update_student_profile(
      self,
      student_id: int,
      full_name: Optional[str] = None,
      student_code: Optional[str] = None,
      notes: Optional[str] = None,
  ) -> Optional[StudentProfile]:
    now = utc_now_iso()
    try:
      with self._db.connection() as conn:
        row = conn.execute(
            "SELECT * FROM students WHERE id = ?", (student_id,)
        ).fetchone()
        if not row:
          return None
        next_name = full_name if full_name is not None else row["full_name"]
        next_code = student_code if student_code is not None else row["student_code"]
        next_notes = notes if notes is not None else row["notes"]
        conn.execute(
            """
            UPDATE students
            SET full_name = ?, student_code = ?, notes = ?
            WHERE id = ?
            """,
            (next_name, next_code, next_notes, student_id),
        )
        conn.execute(
            "UPDATE users SET full_name = ?, updated_at = ? WHERE id = ?",
            (next_name, now, int(row["user_id"])),
        )
        updated = conn.execute(
            """
            SELECT s.*, u.username, u.status AS account_status
            FROM students s
            JOIN users u ON u.id = s.user_id
            WHERE s.id = ?
            """,
            (student_id,),
        ).fetchone()
    except DatabaseIntegrityError as exc:
      raise ConflictError(
          f"Nomor induk '{student_code}' sudah digunakan peserta didik lain."
      ) from exc
    return self._row_to_student(updated)

  def move_student_class(self, student_id: int, new_class_id: int) -> Optional[StudentProfile]:
    """Memindahkan peserta didik ke kelas lain tanpa menghapus riwayat kelas lama."""
    now = utc_now_iso()
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT * FROM students WHERE id = ?", (student_id,)
      ).fetchone()
      if not row:
        return None
      conn.execute(
          """
          UPDATE student_enrollments
          SET left_at = ?
          WHERE student_id = ? AND left_at IS NULL
          """,
          (now, student_id),
      )
      conn.execute(
          """
          INSERT INTO student_enrollments (student_id, class_id, enrolled_at)
          VALUES (?, ?, ?)
          """,
          (student_id, new_class_id, now),
      )
      conn.execute(
          "UPDATE students SET current_class_id = ? WHERE id = ?",
          (new_class_id, student_id),
      )
      updated = conn.execute(
          """
          SELECT s.*, u.username, u.status AS account_status
          FROM students s
          JOIN users u ON u.id = s.user_id
          WHERE s.id = ?
          """,
          (student_id,),
      ).fetchone()
    return self._row_to_student(updated)

  def list_student_enrollments(self, student_id: int) -> List[Dict[str, Any]]:
    """Mengembalikan riwayat perpindahan kelas seorang peserta didik."""
    with self._db.connection() as conn:
      rows = conn.execute(
          """
          SELECT e.id, e.class_id, c.period_id, c.name AS class_name, c.academic_year,
                 e.enrolled_at, e.left_at
          FROM student_enrollments e
          JOIN classes c ON c.id = e.class_id
          WHERE e.student_id = ?
          ORDER BY e.id ASC
          """,
          (student_id,),
      ).fetchall()
    return [dict(r) for r in rows]

  def delete_student(self, student_id: int) -> None:
    """Menghapus profil peserta didik beserta akun user yang terhubung."""
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT user_id FROM students WHERE id = ?", (student_id,)
      ).fetchone()
      if not row:
        return
      user_id = int(row["user_id"])
      conn.execute("DELETE FROM grade_history WHERE student_id = ?", (student_id,))
      conn.execute("DELETE FROM attendance_history WHERE student_id = ?", (student_id,))
      conn.execute("DELETE FROM correction_requests WHERE student_id = ?", (student_id,))
      conn.execute("DELETE FROM grades WHERE student_id = ?", (student_id,))
      conn.execute("DELETE FROM attendance_records WHERE student_id = ?", (student_id,))
      conn.execute("DELETE FROM student_enrollments WHERE student_id = ?", (student_id,))
      conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
      conn.execute("DELETE FROM recovery_tokens WHERE user_id = ?", (user_id,))
      conn.execute("DELETE FROM audit_logs WHERE actor_user_id = ?", (user_id,))
      conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
      conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

  def get_bulk_student_delete_preview(
      self, teacher_id: int, class_id: int, student_ids: Optional[List[int]] = None
  ) -> Dict[str, Any]:
    """Menghitung jumlah peserta didik terdampak & riwayat akademiknya dalam kelas tertentu."""
    with self._db.connection() as conn:
      if student_ids:
        placeholders = ",".join("?" for _ in student_ids)
        rows = conn.execute(
            f"SELECT id, user_id, full_name, student_code FROM students WHERE teacher_id = ? AND current_class_id = ? AND id IN ({placeholders})",
            [teacher_id, class_id, *student_ids],
        ).fetchall()
      else:
        rows = conn.execute(
            "SELECT id, user_id, full_name, student_code FROM students WHERE teacher_id = ? AND current_class_id = ?",
            (teacher_id, class_id),
        ).fetchall()

      with_history = 0
      multi_class = 0
      for r in rows:
        sid = int(r["id"])
        g_cnt = int(conn.execute("SELECT COUNT(*) AS c FROM grades WHERE student_id = ?", (sid,)).fetchone()["c"])
        a_cnt = int(conn.execute("SELECT COUNT(*) AS c FROM attendance_records WHERE student_id = ?", (sid,)).fetchone()["c"])
        c_cnt = int(conn.execute("SELECT COUNT(*) AS c FROM correction_requests WHERE student_id = ?", (sid,)).fetchone()["c"])
        e_cnt = int(conn.execute("SELECT COUNT(DISTINCT class_id) AS c FROM student_enrollments WHERE student_id = ?", (sid,)).fetchone()["c"])
        if g_cnt > 0 or a_cnt > 0 or c_cnt > 0 or e_cnt > 1:
          with_history += 1
        if e_cnt > 1:
          multi_class += 1

    return {
        "total_selected": len(rows),
        "with_academic_history": with_history,
        "without_academic_history": len(rows) - with_history,
        "linked_to_other_classes": multi_class,
        "recommended_mode": "archive" if with_history > 0 else "permanent",
    }

  def bulk_archive_or_delete_students(
      self,
      teacher_id: int,
      class_id: int,
      student_ids: Optional[List[int]],
      delete_all: bool,
      mode: str,
  ) -> Dict[str, Any]:
    """Menjalankan arsip/nonaktifkan atau hapus permanen peserta didik secara atomik (all-or-nothing)."""
    now = utc_now_iso()
    with self._db.connection() as conn:
      if delete_all:
        rows = conn.execute(
            "SELECT id, user_id, full_name FROM students WHERE teacher_id = ? AND current_class_id = ?",
            (teacher_id, class_id),
        ).fetchall()
      else:
        ids = [int(x) for x in (student_ids or [])]
        if not ids:
          return {"affected_count": 0, "mode": mode, "student_ids": []}
        placeholders = ",".join("?" for _ in ids)
        rows = conn.execute(
            f"SELECT id, user_id, full_name FROM students WHERE teacher_id = ? AND current_class_id = ? AND id IN ({placeholders})",
            [teacher_id, class_id, *ids],
        ).fetchall()
        if len(rows) != len(set(ids)):
          raise ValueError("OUT_OF_SCOPE")

      if not rows:
        return {"affected_count": 0, "mode": mode, "student_ids": []}

      if mode == "permanent":
        blocked_names = []
        for r in rows:
          sid = int(r["id"])
          other_cls = int(
              conn.execute(
                  "SELECT COUNT(*) AS c FROM student_enrollments WHERE student_id = ? AND class_id != ?",
                  (sid, class_id),
              ).fetchone()["c"]
          )
          if other_cls > 0:
            blocked_names.append(str(r["full_name"]))
        if blocked_names:
          raise RuntimeError("MULTI_CLASS:" + ", ".join(blocked_names[:5]))

        for r in rows:
          sid = int(r["id"])
          uid = int(r["user_id"])
          conn.execute("DELETE FROM grade_history WHERE student_id = ?", (sid,))
          conn.execute("DELETE FROM attendance_history WHERE student_id = ?", (sid,))
          conn.execute("DELETE FROM correction_requests WHERE student_id = ?", (sid,))
          conn.execute("DELETE FROM grades WHERE student_id = ?", (sid,))
          conn.execute("DELETE FROM attendance_records WHERE student_id = ?", (sid,))
          conn.execute("DELETE FROM student_enrollments WHERE student_id = ?", (sid,))
          conn.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
          conn.execute("DELETE FROM recovery_tokens WHERE user_id = ?", (uid,))
          conn.execute("DELETE FROM audit_logs WHERE actor_user_id = ?", (uid,))
          conn.execute("DELETE FROM students WHERE id = ?", (sid,))
          conn.execute("DELETE FROM users WHERE id = ? AND role = 'student'", (uid,))
      else:
        for r in rows:
          uid = int(r["user_id"])
          conn.execute(
              "UPDATE users SET status = 'deactivated', updated_at = ? WHERE id = ? AND role = 'student'",
              (now, uid),
          )
          conn.execute(
              "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
              (now, uid),
          )

    return {
        "affected_count": len(rows),
        "mode": mode,
        "student_ids": [int(r["id"]) for r in rows],
    }

  # --- Papan Pengumuman Kelas ---

  @staticmethod
  def _row_to_announcement(row: sqlite3.Row) -> ClassAnnouncement:
    return ClassAnnouncement(
        id=int(row["id"]),
        class_id=int(row["class_id"]),
        teacher_id=int(row["teacher_id"]),
        title=str(row["title"]),
        category=str(row["category"]),
        content=str(row["content"]),
        is_pinned=bool(row["is_pinned"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )

  def create_announcement(
      self,
      class_id: int,
      teacher_id: int,
      title: str,
      content: str,
      category: str = "Umum",
      is_pinned: bool = False,
  ) -> ClassAnnouncement:
    now = utc_now_iso()
    with self._db.connection() as conn:
      cur = conn.execute(
          """
          INSERT INTO class_announcements (
            class_id, teacher_id, title, category, content, is_pinned, created_at, updated_at
          )
          VALUES (?, ?, ?, ?, ?, ?, ?, ?)
          """,
          (class_id, teacher_id, title, category, content, self._db.bool_val(is_pinned), now, now),
      )
      row = conn.execute(
          "SELECT * FROM class_announcements WHERE id = ?", (int(cur.lastrowid),)
      ).fetchone()
    return self._row_to_announcement(row)

  def get_announcement(self, announcement_id: int) -> Optional[ClassAnnouncement]:
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT * FROM class_announcements WHERE id = ?", (announcement_id,)
      ).fetchone()
    return self._row_to_announcement(row) if row else None

  def list_announcements(self, class_id: int) -> List[ClassAnnouncement]:
    with self._db.connection() as conn:
      rows = conn.execute(
          """
          SELECT * FROM class_announcements
          WHERE class_id = ?
          ORDER BY is_pinned DESC, id DESC
          """,
          (class_id,),
      ).fetchall()
    return [self._row_to_announcement(r) for r in rows]

  def update_announcement(
      self,
      announcement_id: int,
      title: Optional[str] = None,
      category: Optional[str] = None,
      content: Optional[str] = None,
      is_pinned: Optional[bool] = None,
  ) -> Optional[ClassAnnouncement]:
    now = utc_now_iso()
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT * FROM class_announcements WHERE id = ?", (announcement_id,)
      ).fetchone()
      if not row:
        return None
      conn.execute(
          """
          UPDATE class_announcements
          SET title = ?, category = ?, content = ?, is_pinned = ?, updated_at = ?
          WHERE id = ?
          """,
          (
              title if title is not None else row["title"],
              category if category is not None else row["category"],
              content if content is not None else row["content"],
              (self._db.bool_val(is_pinned)) if is_pinned is not None else row["is_pinned"],
              now,
              announcement_id,
          ),
      )
      updated = conn.execute(
          "SELECT * FROM class_announcements WHERE id = ?", (announcement_id,)
      ).fetchone()
    return self._row_to_announcement(updated) if updated else None

  def delete_announcement(self, announcement_id: int) -> bool:
    with self._db.connection() as conn:
      cur = conn.execute("DELETE FROM class_announcements WHERE id = ?", (announcement_id,))
    return int(getattr(cur, "rowcount", 0) or 0) > 0
