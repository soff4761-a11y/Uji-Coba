"""Titik masuk eksekusi (CLI & ASGI) aplikasi EduTrack.

Mendukung inisialisasi data awal (demo seed) opsional agar aplikasi dapat
langsung dicoba oleh guru maupun peserta didik.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Optional

from edutrack.configs.app_config import AppConfig
from edutrack.domain.errors import ConflictError
from edutrack.domain.models import AccountStatus, AssessmentStatus, AttendanceStatus
from edutrack.web.api import AppContainer, create_app


def seed_initial_data(container: AppContainer) -> None:
  """Mengisi data awal contoh apabila belum ada akun guru di basis data."""
  with container.db.connection() as conn:
    row = conn.execute("SELECT 1 FROM users LIMIT 1").fetchone()
    if row is not None:
      return

  try:
    teacher = container.auth_service.register_teacher(
        username="guru_budi",
        password="GuruPassword123!",
        full_name="Budi Santoso, S.Pd.",
        email="budi.santoso@sekolah.sch.id",
    )
  except ConflictError:
    return
  period = container.classroom_service.create_period(
      teacher,
      name="Semester Ganjil 2026/2027",
      academic_year="2026/2027",
      semester="Ganjil",
      is_active=True,
  )
  cls_a = container.classroom_service.create_classroom(
      teacher,
      period_id=period.id,
      name="X-IPA-1",
      education_level="SMA Kelas X",
      academic_year="2026/2027",
      description="Matematika Wajib — Semester Ganjil",
      mastery_threshold=75.0,
      allow_student_report_download=True,
  )
  cls_b = container.classroom_service.create_classroom(
      teacher,
      period_id=period.id,
      name="X-IPA-2",
      education_level="SMA Kelas X",
      academic_year="2026/2027",
      description="Matematika Wajib — Semester Ganjil",
      mastery_threshold=75.0,
      allow_student_report_download=True,
  )

  sample_students = [
      ("Alya Rahmawati", "2026001", "alya_001", "SiswaPass123!"),
      ("Dimas Pratama", "2026002", "dimas_002", "SiswaPass123!"),
      ("Citra Lestari", "2026003", "citra_003", "SiswaPass123!"),
      ("Fajar Nugroho", "2026004", "fajar_004", "SiswaPass123!"),
  ]
  created_students = []
  for name, code, uname, pw in sample_students:
    res = container.student_service.create_student_with_account(
        teacher=teacher,
        class_id=cls_a.id,
        full_name=name,
        student_code=code,
        username=uname,
        initial_password=pw,
        account_status=AccountStatus.ACTIVE,
    )
    created_students.append(res["student"])

  container.student_service.create_student_with_account(
      teacher=teacher,
      class_id=cls_b.id,
      full_name="Nadia Kusuma",
      student_code="2026005",
      username="nadia_005",
      initial_password="SiswaPass123!",
      account_status=AccountStatus.PENDING_ACTIVATION,
  )

  # Penilaian contoh
  a1 = container.grade_service.create_assessment(
      teacher, cls_a.id, "Tugas Aljabar 1", "Tugas", "2026-08-10",
      description="Latihan persamaan linear dua variabel", max_score=100, weight=20,
      status=AssessmentStatus.PUBLISHED,
  )
  a2 = container.grade_service.create_assessment(
      teacher, cls_a.id, "Kuis Fungsi Kuadrat", "Kuis", "2026-09-02",
      description="Evaluasi formatif fungsi kuadrat", max_score=100, weight=30,
      status=AssessmentStatus.PUBLISHED,
  )
  a3 = container.grade_service.create_assessment(
      teacher, cls_a.id, "Asesmen Sumatif Tengah Semester", "Asesmen Sumatif", "2026-10-12",
      description="Penilaian tengah semester ganjil", max_score=100, weight=50,
      status=AssessmentStatus.PUBLISHED,
  )
  container.grade_service.create_assessment(
      teacher, cls_a.id, "Proyek Statistika (Draft)", "Proyek", "2026-11-10",
      description="Masih dalam proses koreksi guru", max_score=100, weight=20,
      status=AssessmentStatus.DRAFT,
  )

  scores_map = {
      a1.id: [(0, 82, "Langkah penyelesaian runtut."), (1, 74, "Perlu teliti tanda negatif."), (2, 90, "Sangat baik."), (3, 62, "Perlu latihan tambahan.")],
      a2.id: [(0, 86, "Peningkatan baik."), (1, 78, "Sudah memahami konsep dasar."), (2, 92, "Konsisten."), (3, 68, "Mulai membaik.")],
      a3.id: [(0, 91, "Capaian sangat baik."), (1, 80, "Tuntas."), (2, 95, "Sangat teliti."), (3, 65, "Perlu pendampingan remedial.")],
  }
  for aid, entries in scores_map.items():
    container.grade_service.save_grades_bulk(
        teacher,
        aid,
        [
            {"student_id": created_students[idx].id, "score": sc, "feedback": fb}
            for idx, sc, fb in entries
        ],
        reason="Data awal pembelajaran",
    )

  # Kehadiran contoh
  sessions_data = [
      ("2026-08-05", 1, "Pengantar Aljabar", [AttendanceStatus.HADIR, AttendanceStatus.HADIR, AttendanceStatus.HADIR, AttendanceStatus.HADIR]),
      ("2026-08-12", 2, "Sistem Persamaan Linear", [AttendanceStatus.HADIR, AttendanceStatus.SAKIT, AttendanceStatus.HADIR, AttendanceStatus.ALPA]),
      ("2026-09-02", 3, "Grafik Fungsi Kuadrat", [AttendanceStatus.HADIR, AttendanceStatus.HADIR, AttendanceStatus.IZIN, AttendanceStatus.ALPA]),
      ("2026-10-07", 4, "Review Tengah Semester", [AttendanceStatus.HADIR, AttendanceStatus.HADIR, AttendanceStatus.HADIR, AttendanceStatus.HADIR]),
  ]
  for sdate, mnum, topic, statuses in sessions_data:
    res = container.attendance_service.create_session(
        teacher, cls_a.id, sdate, mnum, topic=topic
    )
    container.attendance_service.save_session_attendance(
        teacher,
        res["session"].id,
        [
            {"student_id": created_students[idx].id, "status": st.value, "note": ""}
            for idx, st in enumerate(statuses)
        ],
        reason="Data kehadiran awal",
    )


def _load_dotenv_if_present(dotenv_path: Path = Path(".env")) -> None:
  """Memuat berkas .env lokal tanpa menimpa variabel lingkungan yang sudah ada."""
  if not dotenv_path.is_file():
    return
  for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
      continue
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip().strip('"').strip("'")
    if key and key not in os.environ:
      os.environ[key] = value


def build_application(
    db_path: Optional[str] = None, seed: Optional[bool] = None
):
  """Membangun instance ASGI FastAPI siap dijalankan (mendukung .env & AppConfig.from_env)."""
  _load_dotenv_if_present()
  env = dict(os.environ)
  if db_path is not None:
    env["EDUTRACK_DB_PATH"] = db_path
  config = AppConfig.from_env(env)
  app = create_app(config)
  should_seed = config.seed_demo_data if seed is None else seed
  if should_seed:
    seed_initial_data(app.state.container)
  return app


def main(argv: Optional[list[str]] = None) -> None:
  import uvicorn  # pylint: disable=import-outside-toplevel

  parser = argparse.ArgumentParser(description="Jalankan server web EduTrack.")
  parser.add_argument("--host", default="127.0.0.1", help="Host server")
  parser.add_argument("--port", type=int, default=8000, help="Port server")
  parser.add_argument("--db", default=None, help="Lokasi berkas SQLite (opsional, menimpa EDUTRACK_DB_PATH)")
  parser.add_argument(
      "--no-seed",
      action="store_true",
      help="Jangan mengisi akun dan data contoh awal.",
  )
  args = parser.parse_args(argv)
  app = build_application(db_path=args.db, seed=False if args.no_seed else None)
  uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
  main()
