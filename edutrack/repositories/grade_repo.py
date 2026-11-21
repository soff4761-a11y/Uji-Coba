"""Repositori komponen penilaian, nilai peserta didik, dan riwayat perubahan nilai."""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from edutrack.domain.models import Assessment, AssessmentStatus, LearningMaterial
from edutrack.repositories.database import Database, utc_now_iso


class GradeRepository:
  """Akses data persisten untuk komponen penilaian, nilai, dan audit nilai."""

  def __init__(self, db: Database) -> None:
    self._db = db

  @staticmethod
  def _row_to_assessment(row: sqlite3.Row) -> Assessment:
    return Assessment(
        id=int(row["id"]),
        class_id=int(row["class_id"]),
        period_id=int(row["period_id"]),
        title=str(row["title"]),
        category=str(row["category"]),
        assessment_date=str(row["assessment_date"]),
        description=str(row["description"]),
        max_score=float(row["max_score"]),
        weight=float(row["weight"]),
        status=AssessmentStatus(row["status"]),
        created_at=str(row["created_at"]),
        material_id=(int(row["material_id"]) if row["material_id"] is not None else None) if "material_id" in row.keys() else None,
        is_graded=bool(row["is_graded"]) if "is_graded" in row.keys() and row["is_graded"] is not None else True,
    )

  def create_assessment(
      self,
      class_id: int,
      period_id: int,
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
    now = utc_now_iso()
    with self._db.connection() as conn:
      cur = conn.execute(
          """
          INSERT INTO assessments (
            class_id, period_id, material_id, title, category, assessment_date,
            description, max_score, weight, status, is_graded, created_at, updated_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          """,
          (
              class_id,
              period_id,
              material_id,
              title,
              category,
              assessment_date,
              description,
              max_score,
              weight,
              status.value,
              self._db.bool_val(bool(is_graded)),
              now,
              now,
          ),
      )
      row = conn.execute(
          "SELECT * FROM assessments WHERE id = ?", (int(cur.lastrowid),)
      ).fetchone()
    return self._row_to_assessment(row)

  def get_assessment(self, assessment_id: int) -> Optional[Assessment]:
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT * FROM assessments WHERE id = ?", (assessment_id,)
      ).fetchone()
    return self._row_to_assessment(row) if row else None

  def list_assessments(
      self,
      class_id: int,
      published_only: bool = False,
  ) -> List[Assessment]:
    with self._db.connection() as conn:
      if published_only:
        rows = conn.execute(
            """
            SELECT * FROM assessments
            WHERE class_id = ? AND status = 'published'
            ORDER BY assessment_date ASC, id ASC
            """,
            (class_id,),
        ).fetchall()
      else:
        rows = conn.execute(
            """
            SELECT * FROM assessments
            WHERE class_id = ?
            ORDER BY assessment_date ASC, id ASC
            """,
            (class_id,),
        ).fetchall()
    return [self._row_to_assessment(r) for r in rows]

  def update_assessment(
      self,
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
  ) -> Optional[Assessment]:
    now = utc_now_iso()
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT * FROM assessments WHERE id = ?", (assessment_id,)
      ).fetchone()
      if not row:
        return None
      next_material_id = material_id if update_material_id else row["material_id"]
      cur_is_graded = bool(row["is_graded"]) if "is_graded" in row.keys() and row["is_graded"] is not None else True
      next_is_graded = cur_is_graded if is_graded is None else bool(is_graded)
      conn.execute(
          """
          UPDATE assessments
          SET title = ?, category = ?, assessment_date = ?, description = ?,
              max_score = ?, weight = ?, status = ?, material_id = ?, is_graded = ?, updated_at = ?
          WHERE id = ?
          """,
          (
              title if title is not None else row["title"],
              category if category is not None else row["category"],
              assessment_date if assessment_date is not None else row["assessment_date"],
              description if description is not None else row["description"],
              max_score if max_score is not None else row["max_score"],
              weight if weight is not None else row["weight"],
              status.value if status is not None else row["status"],
              next_material_id,
              self._db.bool_val(next_is_graded),
              now,
              assessment_id,
          ),
      )
      updated = conn.execute(
          "SELECT * FROM assessments WHERE id = ?", (assessment_id,)
      ).fetchone()
    return self._row_to_assessment(updated)

  def delete_assessment(self, assessment_id: int) -> None:
    with self._db.connection() as conn:
      conn.execute(
          "DELETE FROM correction_requests WHERE target_type = 'grade' AND target_id = ?",
          (assessment_id,),
      )
      conn.execute("DELETE FROM grade_history WHERE assessment_id = ?", (assessment_id,))
      conn.execute("DELETE FROM grades WHERE assessment_id = ?", (assessment_id,))
      conn.execute("DELETE FROM assessments WHERE id = ?", (assessment_id,))

  def reset_grades_for_assessment(self, assessment_id: int) -> int:
    """Menghapus permanen seluruh nilai, riwayat nilai, dan koreksi terkait untuk satu asesmen."""
    with self._db.connection() as conn:
      cnt_row = conn.execute(
          "SELECT COUNT(*) AS cnt FROM grades WHERE assessment_id = ?", (assessment_id,)
      ).fetchone()
      cleared = int(cnt_row["cnt"]) if cnt_row else 0
      conn.execute(
          "DELETE FROM correction_requests WHERE target_type = 'grade' AND target_id = ?",
          (assessment_id,),
      )
      conn.execute("DELETE FROM grade_history WHERE assessment_id = ?", (assessment_id,))
      conn.execute("DELETE FROM grades WHERE assessment_id = ?", (assessment_id,))
      return cleared

  def reveal_student_grade(
      self, assessment_id: int, student_id: int, revealed_at_iso: str
  ) -> Optional[Dict[str, Any]]:
    """Mencatat timestamp revealed_at (idempoten) untuk nilai siswa pada asesmen tertentu."""
    with self._db.connection() as conn:
      row = conn.execute(
          """
          SELECT g.id AS grade_id, g.score, COALESCE(g.feedback, '') AS feedback, g.revealed_at,
                 a.id AS assessment_id, a.title, a.category, a.max_score, a.status, a.is_graded
          FROM grades g
          JOIN assessments a ON a.id = g.assessment_id
          WHERE g.assessment_id = ? AND g.student_id = ?
          """,
          (assessment_id, student_id),
      ).fetchone()
      if not row:
        return None
      d = dict(row)
      d["is_graded"] = bool(d.get("is_graded", 1))
      if d["revealed_at"] is None and d["score"] is not None:
        conn.execute(
            "UPDATE grades SET revealed_at = ? WHERE id = ?",
            (revealed_at_iso, int(d["grade_id"])),
        )
        d["revealed_at"] = revealed_at_iso
      return d

  def upsert_grade(
      self,
      assessment_id: int,
      student_id: int,
      score: Optional[float],
      feedback: str,
      actor_user_id: int,
      reason: str = "",
  ) -> Dict[str, Any]:
    """Menyimpan atau memperbarui nilai dan mencatat riwayat perubahan."""
    now = utc_now_iso()
    with self._db.connection() as conn:
      existing = conn.execute(
          "SELECT * FROM grades WHERE assessment_id = ? AND student_id = ?",
          (assessment_id, student_id),
      ).fetchone()

      if existing:
        old_score = existing["score"]
        old_feedback = existing["feedback"]
        if old_score != score or old_feedback != feedback:
          next_revealed = None if score is None else existing["revealed_at"]
          conn.execute(
              """
              UPDATE grades
              SET score = ?, feedback = ?, updated_by = ?, updated_at = ?, revealed_at = ?
              WHERE id = ?
              """,
              (score, feedback, actor_user_id, now, next_revealed, int(existing["id"])),
          )
          conn.execute(
              """
              INSERT INTO grade_history (
                assessment_id, student_id, old_score, new_score,
                old_feedback, new_feedback, changed_by, reason, changed_at
              ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
              """,
              (
                  assessment_id,
                  student_id,
                  old_score,
                  score,
                  old_feedback,
                  feedback,
                  actor_user_id,
                  reason or "Pembaruan nilai",
                  now,
              ),
          )
      else:
        conn.execute(
            """
            INSERT INTO grades (
              assessment_id, student_id, score, feedback, updated_by, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (assessment_id, student_id, score, feedback, actor_user_id, now),
        )
        conn.execute(
            """
            INSERT INTO grade_history (
              assessment_id, student_id, old_score, new_score,
              old_feedback, new_feedback, changed_by, reason, changed_at
            ) VALUES (?, ?, NULL, ?, NULL, ?, ?, ?, ?)
            """,
            (
                assessment_id,
                student_id,
                score,
                feedback,
                actor_user_id,
                reason or "Input nilai awal",
                now,
            ),
        )

      row = conn.execute(
          "SELECT * FROM grades WHERE assessment_id = ? AND student_id = ?",
          (assessment_id, student_id),
      ).fetchone()
    return dict(row)

  def list_grades_for_class(self, class_id: int) -> List[Dict[str, Any]]:
    """Mengembalikan seluruh nilai untuk komponen penilaian pada sebuah kelas."""
    with self._db.connection() as conn:
      rows = conn.execute(
          """
          SELECT g.assessment_id, g.student_id, g.score, g.feedback, g.updated_at,
                 a.max_score, a.weight, a.status AS assessment_status,
                 a.title AS assessment_title, a.category, a.assessment_date,
                 a.is_graded
          FROM grades g
          JOIN assessments a ON a.id = g.assessment_id
          WHERE a.class_id = ?
          ORDER BY a.assessment_date ASC, a.id ASC
          """,
          (class_id,),
      ).fetchall()
    result = []
    for r in rows:
      d = dict(r)
      d["is_graded"] = bool(d.get("is_graded", 1))
      result.append(d)
    return result

  def list_grades_for_student(
      self,
      student_id: int,
      published_only: bool = True,
      class_id: Optional[int] = None,
      period_id: Optional[int] = None,
      material_id: Optional[int] = None,
  ) -> List[Dict[str, Any]]:
    """Mengembalikan daftar penilaian beserta nilai milik seorang peserta didik.

    Menampilkan seluruh penilaian di kelas aktif (serta riwayat nilai dari kelas
    sebelumnya apabila peserta didik pernah dipindahkan kelas), termasuk relasi
    materi pembelajaran (LEFT JOIN) agar penilaian lama tetap kompatibel.
    """
    clauses = ["(a.class_id = s.current_class_id OR g.student_id = ?)"]
    params: List[Any] = [student_id]
    if published_only:
      clauses.append("a.status = 'published'")
    if class_id is not None:
      clauses.append("a.class_id = ?")
      params.append(class_id)
    if period_id is not None:
      clauses.append("a.period_id = ?")
      params.append(period_id)
    if material_id is not None:
      if material_id == 0:
        clauses.append("a.material_id IS NULL")
      else:
        clauses.append("a.material_id = ?")
        params.append(material_id)

    query = f"""
      SELECT a.id AS assessment_id, a.class_id, c.name AS class_name,
             a.period_id, a.material_id,
             COALESCE(lm.title, 'Belum Dikelompokkan') AS material_title,
             a.title, a.category, a.assessment_date,
             a.description, a.max_score, a.weight, a.status, a.is_graded,
             g.score, COALESCE(g.feedback, '') AS feedback, g.updated_at, g.revealed_at
      FROM students s
      JOIN assessments a ON (
        a.class_id = s.current_class_id
        OR EXISTS (
          SELECT 1 FROM grades g2
          WHERE g2.assessment_id = a.id AND g2.student_id = s.id
        )
      )
      JOIN classes c ON c.id = a.class_id
      LEFT JOIN learning_materials lm ON lm.id = a.material_id
      LEFT JOIN grades g ON g.assessment_id = a.id AND g.student_id = s.id
      WHERE s.id = ? AND {' AND '.join(clauses)}
      ORDER BY a.assessment_date ASC, a.id ASC
    """
    with self._db.connection() as conn:
      rows = conn.execute(query, [student_id] + params).fetchall()
    result = []
    for r in rows:
      d = dict(r)
      d["is_graded"] = bool(d.get("is_graded", 1))
      result.append(d)
    return result

  def list_grade_history(
      self,
      class_id: Optional[int] = None,
      assessment_id: Optional[int] = None,
      student_id: Optional[int] = None,
      limit: int = 100,
  ) -> List[Dict[str, Any]]:
    """Mengembalikan riwayat perubahan nilai untuk akuntabilitas."""
    clauses: List[str] = ["1=1"]
    params: List[Any] = []
    if class_id is not None:
      clauses.append("a.class_id = ?")
      params.append(class_id)
    if assessment_id is not None:
      clauses.append("h.assessment_id = ?")
      params.append(assessment_id)
    if student_id is not None:
      clauses.append("h.student_id = ?")
      params.append(student_id)
    params.append(limit)
    query = f"""
      SELECT h.*, a.title AS assessment_title, s.full_name AS student_name,
             u.full_name AS changed_by_name, u.username AS changed_by_username
      FROM grade_history h
      JOIN assessments a ON a.id = h.assessment_id
      JOIN students s ON s.id = h.student_id
      JOIN users u ON u.id = h.changed_by
      WHERE {' AND '.join(clauses)}
      ORDER BY h.id DESC
      LIMIT ?
    """
    with self._db.connection() as conn:
      rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]

  def list_grades_for_assessment(self, assessment_id: int) -> List[Dict[str, Any]]:
    """Mengambil seluruh nilai tersimpan untuk satu komponen penilaian."""
    with self._db.connection() as conn:
      rows = conn.execute(
          "SELECT * FROM grades WHERE assessment_id = ?", (assessment_id,)
      ).fetchall()
    return [dict(r) for r in rows]

  @staticmethod
  def _row_to_material(row: sqlite3.Row) -> LearningMaterial:
    return LearningMaterial(
        id=int(row["id"]),
        class_id=int(row["class_id"]),
        period_id=int(row["period_id"]),
        teacher_id=int(row["teacher_id"]),
        title=str(row["title"]),
        description=str(row["description"]),
        sort_order=int(row["sort_order"]),
        is_archived=bool(row["is_archived"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )

  def create_material(
      self,
      class_id: int,
      period_id: int,
      teacher_id: int,
      title: str,
      description: str = "",
      sort_order: Optional[int] = None,
  ) -> LearningMaterial:
    now = utc_now_iso()
    with self._db.connection() as conn:
      if sort_order is None:
        max_row = conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) AS m FROM learning_materials WHERE class_id = ?",
            (class_id,),
        ).fetchone()
        sort_order = int(max_row["m"]) + 1 if max_row else 1
      cur = conn.execute(
          """
          INSERT INTO learning_materials (
            class_id, period_id, teacher_id, title, description,
            sort_order, is_archived, created_at, updated_at
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
          """,
          (class_id, period_id, teacher_id, title, description, int(sort_order), self._db.bool_val(False), now, now),
      )
      row = conn.execute(
          "SELECT * FROM learning_materials WHERE id = ?", (int(cur.lastrowid),)
      ).fetchone()
    return self._row_to_material(row)

  def get_material(self, material_id: int) -> Optional[LearningMaterial]:
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT * FROM learning_materials WHERE id = ?", (material_id,)
      ).fetchone()
    return self._row_to_material(row) if row else None

  def list_materials(
      self, class_id: int, include_archived: bool = False
  ) -> List[LearningMaterial]:
    with self._db.connection() as conn:
      if include_archived:
        rows = conn.execute(
            "SELECT * FROM learning_materials WHERE class_id = ? ORDER BY sort_order ASC, id ASC",
            (class_id,),
        ).fetchall()
      else:
        rows = conn.execute(
            "SELECT * FROM learning_materials WHERE class_id = ? AND is_archived = ? ORDER BY sort_order ASC, id ASC",
            (class_id, self._db.bool_val(False)),
        ).fetchall()
    return [self._row_to_material(r) for r in rows]

  def update_material(
      self,
      material_id: int,
      title: Optional[str] = None,
      description: Optional[str] = None,
      sort_order: Optional[int] = None,
      is_archived: Optional[bool] = None,
  ) -> Optional[LearningMaterial]:
    now = utc_now_iso()
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT * FROM learning_materials WHERE id = ?", (material_id,)
      ).fetchone()
      if not row:
        return None
      conn.execute(
          """
          UPDATE learning_materials
          SET title = ?, description = ?, sort_order = ?, is_archived = ?, updated_at = ?
          WHERE id = ?
          """,
          (
              title if title is not None else row["title"],
              description if description is not None else row["description"],
              int(sort_order) if sort_order is not None else int(row["sort_order"]),
              self._db.bool_val(bool(is_archived) if is_archived is not None else bool(row["is_archived"])),
              now,
              material_id,
          ),
      )
      updated = conn.execute(
          "SELECT * FROM learning_materials WHERE id = ?", (material_id,)
      ).fetchone()
    return self._row_to_material(updated)

  def count_assessments_for_material(self, material_id: int) -> int:
    with self._db.connection() as conn:
      row = conn.execute(
          "SELECT COUNT(*) AS cnt FROM assessments WHERE material_id = ?", (material_id,)
      ).fetchone()
    return int(row["cnt"]) if row else 0

  def delete_material(self, material_id: int) -> None:
    with self._db.connection() as conn:
      conn.execute("DELETE FROM learning_materials WHERE id = ?", (material_id,))
