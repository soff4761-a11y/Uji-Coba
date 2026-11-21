"""Repositori sesi kehadiran, catatan kehadiran, audit kehadiran, dan permintaan koreksi."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from edutrack.domain.errors import ConflictError
from edutrack.domain.models import AttendanceSession, AttendanceStatus, CorrectionStatus
from edutrack.repositories.database import Database, DatabaseIntegrityError, utc_now_iso


class AttendanceRepository:
  """Akses data persisten untuk sesi pertemuan, presensi, dan koreksi."""

  def __init__(self, db: Database) -> None:
    self._db = db

  @staticmethod
  def _row_to_session(row: sqlite3.Row) -> AttendanceSession:
    return AttendanceSession(
        id=int(row["id"]),
        class_id=int(row["class_id"]),
        period_id=int(row["period_id"]),
        session_date=str(row["session_date"]),
        meeting_number=int(row["meeting_number"]),
        topic=str(row["topic"]),
        created_at=str(row["created_at"]),
    )

  def create_session(
      self,
      class_id: int,
      period_id: int,
      session_date: str,
      meeting_number: int,
      topic: str,
      created_by: int,
  ) -> AttendanceSession:
    now = utc_now_iso()
    try:
      with self._db.connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO attendance_sessions (
              class_id, period_id, session_date, meeting_number, topic, created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (class_id, period_id, session_date, meeting_number, topic, created_by, now),
        )
        row = conn.execute(
            "SELECT * FROM attendance_sessions WHERE id = ?", (int(cur.lastrowid),)
        ).fetchone()
    except DatabaseIntegrityError as exc:
      raise ConflictError(
          f"Sesi pertemuan #{meeting_number} pada tanggal {session_date} untuk kelas ini sudah tercatat."
      ) from exc
    return self._row_to_session(row)

  def update_session(
      self,
      session_id: int,
      session_date: Optional[str] = None,
      meeting_number: Optional[int] = None,
      topic: Optional[str] = None,
  ) -> Optional[AttendanceSession]:
    existing = self.get_session(session_id)
    if not existing:
      return None
    new_date = session_date.strip() if session_date is not None else existing.session_date
    new_meeting = int(meeting_number) if meeting_number is not None else existing.meeting_number
    new_topic = topic.strip() if topic is not None else existing.topic
    try:
      with self._db.connection() as conn:
        conn.execute(
            """
            UPDATE attendance_sessions
            SET session_date = ?, meeting_number = ?, topic = ?
            WHERE id = ?
            """,
            (new_date, new_meeting, new_topic, session_id),
        )
        row = conn.execute(
            "SELECT * FROM attendance_sessions WHERE id = ?", (session_id,)
        ).fetchone()
    except DatabaseIntegrityError as exc:
      raise ConflictError(
          f"Sesi pertemuan #{new_meeting} pada tanggal {new_date} untuk kelas ini sudah tercatat."
      ) from exc
    return self._row_to_session(row) if row else None

  def delete_session(self, session_id: int) -> bool:
    with self._db.connection() as conn:
      conn.execute(
          """
          DELETE FROM correction_requests
          WHERE target_type = 'attendance'
            AND student_id IN (
              SELECT student_id FROM attendance_records WHERE session_id = ?
              UNION
              SELECT id FROM students WHERE current_class_id = (
                SELECT class_id FROM attendance_sessions WHERE id = ?
              )
            )
            AND (
              target_id = ?
              OR target_id IN (SELECT id FROM attendance_records WHERE session_id = ?)
            )
          """,
          (session_id, session_id, session_id, session_id),
      )
      conn.execute("DELETE FROM attendance_history WHERE session_id = ?", (session_id,))
      conn.execute("DELETE FROM attendance_records WHERE session_id = ?", (session_id,))
      cur = conn.execute("DELETE FROM attendance_sessions WHERE id = ?", (session_id,))
      return cur.rowcount != 0

  def delete_all_sessions_for_class(self, class_id: int) -> int:
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT COUNT(*) AS cnt FROM attendance_sessions WHERE class_id = ?",
          (class_id,),
      ).fetchone()
      count = int(row["cnt"]) if row else 0
      if count == 0:
        return 0
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
            AND (
              target_id IN (SELECT id FROM attendance_sessions WHERE class_id = ?)
              OR target_id IN (
                SELECT id FROM attendance_records
                WHERE session_id IN (SELECT id FROM attendance_sessions WHERE class_id = ?)
              )
            )
          """,
          (class_id, class_id, class_id, class_id),
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
      return count

  def reset_session_records(self, session_id: int) -> int:
    with self._db.connection() as conn:
      rows = conn.execute(
          "SELECT COUNT(*) AS cnt FROM attendance_records WHERE session_id = ?", (session_id,)
      ).fetchone()
      count = int(rows["cnt"]) if rows else 0
      conn.execute(
          """
          DELETE FROM correction_requests
          WHERE target_type = 'attendance'
            AND student_id IN (
              SELECT student_id FROM attendance_records WHERE session_id = ?
              UNION
              SELECT id FROM students WHERE current_class_id = (
                SELECT class_id FROM attendance_sessions WHERE id = ?
              )
            )
            AND (
              target_id = ?
              OR target_id IN (SELECT id FROM attendance_records WHERE session_id = ?)
            )
          """,
          (session_id, session_id, session_id, session_id),
      )
      conn.execute("DELETE FROM attendance_history WHERE session_id = ?", (session_id,))
      conn.execute("DELETE FROM attendance_records WHERE session_id = ?", (session_id,))
      return count

  def get_session(self, session_id: int) -> Optional[AttendanceSession]:
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT * FROM attendance_sessions WHERE id = ?", (session_id,)
      ).fetchone()
    return self._row_to_session(row) if row else None

  def list_sessions(
      self,
      class_id: int,
      date_from: Optional[str] = None,
      date_to: Optional[str] = None,
  ) -> List[AttendanceSession]:
    clauses = ["class_id = ?"]
    params: List[Any] = [class_id]
    if date_from:
      clauses.append("session_date >= ?")
      params.append(date_from)
    if date_to:
      clauses.append("session_date <= ?")
      params.append(date_to)
    query = f"""
      SELECT * FROM attendance_sessions
      WHERE {' AND '.join(clauses)}
      ORDER BY session_date DESC, meeting_number DESC
    """
    with self._db.connection() as conn:
      rows = conn.execute(query, params).fetchall()
    return [self._row_to_session(r) for r in rows]

  def upsert_record(
      self,
      session_id: int,
      student_id: int,
      status: AttendanceStatus,
      note: str,
      actor_user_id: int,
      reason: str = "",
  ) -> Dict[str, Any]:
    """Mencatat atau mengoreksi kehadiran tanpa duplikasi dan menyimpan riwayat."""
    now = utc_now_iso()
    with self._db.connection() as conn:
      existing = conn.execute(
          "SELECT * FROM attendance_records WHERE session_id = ? AND student_id = ?",
          (session_id, student_id),
      ).fetchone()
      if existing:
        if existing["status"] != status.value or existing["note"] != note:
          conn.execute(
              """
              UPDATE attendance_records
              SET status = ?, note = ?, updated_by = ?, updated_at = ?
              WHERE id = ?
              """,
              (status.value, note, actor_user_id, now, int(existing["id"])),
          )
          conn.execute(
              """
              INSERT INTO attendance_history (
                session_id, student_id, old_status, new_status,
                old_note, new_note, changed_by, reason, changed_at
              ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
              """,
              (
                  session_id,
                  student_id,
                  existing["status"],
                  status.value,
                  existing["note"],
                  note,
                  actor_user_id,
                  reason or "Koreksi kehadiran",
                  now,
              ),
          )
      else:
        conn.execute(
            """
            INSERT INTO attendance_records (
              session_id, student_id, status, note, updated_by, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, student_id, status.value, note, actor_user_id, now),
        )
        conn.execute(
            """
            INSERT INTO attendance_history (
              session_id, student_id, old_status, new_status,
              old_note, new_note, changed_by, reason, changed_at
            ) VALUES (?, ?, NULL, ?, NULL, ?, ?, ?, ?)
            """,
            (
                session_id,
                student_id,
                status.value,
                note,
                actor_user_id,
                reason or "Pencatatan kehadiran awal",
                now,
            ),
        )

      row = conn.execute(
          "SELECT * FROM attendance_records WHERE session_id = ? AND student_id = ?",
          (session_id, student_id),
      ).fetchone()
    return dict(row)

  def list_records_for_session(self, session_id: int) -> List[Dict[str, Any]]:
    with self._db.connection() as conn:
      rows = conn.execute(
          """
          SELECT r.*, s.full_name AS student_name, s.student_code
          FROM attendance_records r
          JOIN students s ON s.id = r.student_id
          WHERE r.session_id = ?
          ORDER BY s.full_name ASC
          """,
          (session_id,),
      ).fetchall()
    return [dict(r) for r in rows]

  def list_records_for_class(
      self,
      class_id: int,
      date_from: Optional[str] = None,
      date_to: Optional[str] = None,
  ) -> List[Dict[str, Any]]:
    clauses = ["ses.class_id = ?"]
    params: List[Any] = [class_id]
    if date_from:
      clauses.append("ses.session_date >= ?")
      params.append(date_from)
    if date_to:
      clauses.append("ses.session_date <= ?")
      params.append(date_to)
    query = f"""
      SELECT r.id, r.session_id, r.student_id, r.status, r.note, r.updated_at,
             ses.session_date, ses.meeting_number, ses.topic, ses.period_id,
             s.full_name AS student_name, s.student_code
      FROM attendance_records r
      JOIN attendance_sessions ses ON ses.id = r.session_id
      JOIN students s ON s.id = r.student_id
      WHERE {' AND '.join(clauses)}
      ORDER BY ses.session_date ASC, ses.meeting_number ASC
    """
    with self._db.connection() as conn:
      rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]

  def list_records_for_student(
      self,
      student_id: int,
      month: Optional[str] = None,
      period_id: Optional[int] = None,
      date_from: Optional[str] = None,
      date_to: Optional[str] = None,
  ) -> List[Dict[str, Any]]:
    clauses = ["r.student_id = ?"]
    params: List[Any] = [student_id]
    if month:
      clauses.append("substr(ses.session_date, 1, 7) = ?")
      params.append(month)
    if period_id is not None:
      clauses.append("ses.period_id = ?")
      params.append(period_id)
    if date_from:
      clauses.append("ses.session_date >= ?")
      params.append(date_from)
    if date_to:
      clauses.append("ses.session_date <= ?")
      params.append(date_to)

    query = f"""
      SELECT r.id, r.session_id, r.student_id, r.status, r.note, r.updated_at,
             ses.session_date, ses.meeting_number, ses.topic, ses.class_id,
             c.name AS class_name, ses.period_id
      FROM attendance_records r
      JOIN attendance_sessions ses ON ses.id = r.session_id
      JOIN classes c ON c.id = ses.class_id
      WHERE {' AND '.join(clauses)}
      ORDER BY ses.session_date DESC, ses.meeting_number DESC
    """
    with self._db.connection() as conn:
      rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]

  def list_attendance_history(
      self, class_id: Optional[int] = None, limit: int = 100
  ) -> List[Dict[str, Any]]:
    clauses = ["1=1"]
    params: List[Any] = []
    if class_id is not None:
      clauses.append("ses.class_id = ?")
      params.append(class_id)
    params.append(limit)
    query = f"""
      SELECT h.*, ses.session_date, ses.meeting_number,
             s.full_name AS student_name, u.full_name AS changed_by_name
      FROM attendance_history h
      JOIN attendance_sessions ses ON ses.id = h.session_id
      JOIN students s ON s.id = h.student_id
      JOIN users u ON u.id = h.changed_by
      WHERE {' AND '.join(clauses)}
      ORDER BY h.id DESC
      LIMIT ?
    """
    with self._db.connection() as conn:
      rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]

  # --- Correction Requests ---

  def create_correction_request(
      self,
      student_id: int,
      teacher_id: int,
      target_type: str,
      target_id: int,
      message: str,
  ) -> Dict[str, Any]:
    now = utc_now_iso()
    with self._db.connection() as conn:
      cur = conn.execute(
          """
          INSERT INTO correction_requests (
            student_id, teacher_id, target_type, target_id, message,
            status, teacher_response, created_at, updated_at
          ) VALUES (?, ?, ?, ?, ?, 'pending', '', ?, ?)
          """,
          (student_id, teacher_id, target_type, target_id, message, now, now),
      )
      row = conn.execute(
          "SELECT * FROM correction_requests WHERE id = ?", (int(cur.lastrowid),)
      ).fetchone()
    return dict(row)

  def list_correction_requests_for_teacher(
      self, teacher_id: int, status: Optional[CorrectionStatus] = None
  ) -> List[Dict[str, Any]]:
    clauses = ["cr.teacher_id = ?"]
    params: List[Any] = [teacher_id]
    if status is not None:
      clauses.append("cr.status = ?")
      params.append(status.value)
    query = f"""
      SELECT cr.*, s.full_name AS student_name, s.student_code, c.name AS class_name
      FROM correction_requests cr
      JOIN students s ON s.id = cr.student_id
      JOIN classes c ON c.id = s.current_class_id
      WHERE {' AND '.join(clauses)}
      ORDER BY cr.id DESC
    """
    with self._db.connection() as conn:
      rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]

  def list_correction_requests_for_student(
      self, student_id: int
  ) -> List[Dict[str, Any]]:
    with self._db.connection() as conn:
      rows = conn.execute(
          """
          SELECT * FROM correction_requests
          WHERE student_id = ? AND COALESCE(hidden_by_student, ?) = ?
          ORDER BY id DESC
          """,
          (student_id, self._db.bool_val(False), self._db.bool_val(False)),
      ).fetchall()
    return [dict(r) for r in rows]

  def update_correction_request(
      self,
      request_id: int,
      teacher_id: int,
      status: CorrectionStatus,
      teacher_response: str,
  ) -> Optional[Dict[str, Any]]:
    now = utc_now_iso()
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT * FROM correction_requests WHERE id = ? AND teacher_id = ?",
          (request_id, teacher_id),
      ).fetchone()
      if not row:
        return None
      conn.execute(
          """
          UPDATE correction_requests
          SET status = ?, teacher_response = ?, updated_at = ?
          WHERE id = ?
          """,
          (status.value, teacher_response, now, request_id),
      )
      updated = conn.execute(
          "SELECT * FROM correction_requests WHERE id = ?", (request_id,)
      ).fetchone()
    return dict(updated)

  def delete_or_hide_student_correction(
      self, request_id: int, student_id: int
  ) -> str:
    """Menghapus koreksi pending atau menyembunyikan koreksi terproses secara atomik (anti-TOCTOU).

    Returns:
      'deleted' | 'hidden' | 'not_found' | 'forbidden'
    """
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT id, student_id, status, COALESCE(hidden_by_student, ?) AS hidden_by_student FROM correction_requests WHERE id = ?",
          (self._db.bool_val(False), request_id),
      ).fetchone()
      if not row:
        return "not_found"
      if int(row["student_id"]) != student_id:
        return "forbidden"
      if str(row["status"]) == "pending":
        conn.execute(
            "DELETE FROM correction_requests WHERE id = ? AND student_id = ? AND status = 'pending'",
            (request_id, student_id),
        )
        still_there = conn.execute(
            "SELECT id FROM correction_requests WHERE id = ?", (request_id,)
        ).fetchone()
        if not still_there:
          return "deleted"
      conn.execute(
          "UPDATE correction_requests SET hidden_by_student = ? WHERE id = ? AND student_id = ?",
          (self._db.bool_val(True), request_id, student_id),
      )
      return "hidden"

  def delete_teacher_correction(self, request_id: int, teacher_id: int) -> str:
    """Menghapus permanen catatan permintaan koreksi milik guru (anti-IDOR).

    Returns:
      'deleted' | 'not_found' | 'forbidden'
    """
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT id, teacher_id FROM correction_requests WHERE id = ?",
          (request_id,),
      ).fetchone()
      if not row:
        return "not_found"
      if int(row["teacher_id"]) != teacher_id:
        return "forbidden"
      conn.execute(
          "DELETE FROM correction_requests WHERE id = ? AND teacher_id = ?",
          (request_id, teacher_id),
      )
      return "deleted"
