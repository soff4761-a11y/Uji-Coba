"""Entitas domain dan enumerasi inti EduTrack."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Role(str, Enum):
  """Peran pengguna dalam sistem."""

  ADMIN = "admin"
  TEACHER = "teacher"
  STUDENT = "student"


class AccountStatus(str, Enum):
  """Status siklus hidup akun pengguna."""

  ACTIVE = "active"
  PENDING_ACTIVATION = "pending_activation"
  DEACTIVATED = "deactivated"


SURPRISE_REVEAL_CATEGORIES = frozenset({"ujian", "asesmen sumatif"})


class AssessmentStatus(str, Enum):
  """Status publikasi komponen penilaian."""

  DRAFT = "draft"
  PUBLISHED = "published"


class CalculationMode(str, Enum):
  """Metode perhitungan nilai akhir kelas."""

  WEIGHTED = "weighted"
  UNWEIGHTED = "unweighted"


class AttendanceStatus(str, Enum):
  """Status kehadiran peserta didik pada suatu pertemuan."""

  HADIR = "hadir"
  SAKIT = "sakit"
  IZIN = "izin"
  ALPA = "alpa"


class CorrectionStatus(str, Enum):
  """Status permintaan koreksi dari peserta didik kepada guru."""

  PENDING = "pending"
  REVIEWED = "reviewed"
  RESOLVED = "resolved"
  REJECTED = "rejected"


@dataclass(frozen=True)
class User:
  """Representasi akun pengguna (tanpa mengekspos hash sandi pada respons API)."""

  id: int
  username: str
  full_name: str
  role: Role
  status: AccountStatus
  must_change_password: bool
  email: Optional[str]
  created_at: str


@dataclass(frozen=True)
class AcademicPeriod:
  """Periode tahun pelajaran dan semester."""

  id: int
  teacher_id: int
  name: str
  academic_year: str
  semester: str
  is_active: bool
  is_archived: bool
  created_at: str


@dataclass(frozen=True)
class Classroom:
  """Entitas kelas yang dikelola oleh seorang guru."""

  id: int
  teacher_id: int
  period_id: int
  name: str
  education_level: str
  academic_year: str
  description: str
  calculation_mode: CalculationMode
  mastery_threshold: float
  allow_student_report_download: bool
  is_archived: bool
  created_at: str


@dataclass(frozen=True)
class StudentProfile:
  """Profil peserta didik yang terhubung dengan akun pengguna dan kelas aktif."""

  id: int
  user_id: int
  teacher_id: int
  current_class_id: int
  student_code: str
  full_name: str
  username: str
  account_status: AccountStatus
  notes: str
  created_at: str


@dataclass(frozen=True)
class LearningMaterial:
  """Materi pembelajaran / bab sebagai pengelompokan utama penilaian dalam kelas."""

  id: int
  class_id: int
  period_id: int
  teacher_id: int
  title: str
  description: str
  sort_order: int
  is_archived: bool
  created_at: str
  updated_at: str = ""


@dataclass(frozen=True)
class Assessment:
  """Komponen penilaian dalam sebuah kelas."""

  id: int
  class_id: int
  period_id: int
  title: str
  category: str
  assessment_date: str
  description: str
  max_score: float
  weight: float
  status: AssessmentStatus
  created_at: str
  material_id: Optional[int] = None
  is_graded: bool = True

@dataclass(frozen=True)
class GradeEntry:
  """Catatan nilai seorang peserta didik pada komponen penilaian tertentu.

  Catatan:
    score = None menandakan nilai BELUM DIMASUKKAN dan dibedakan secara tegas
    dari score = 0.0.
  """

  assessment_id: int
  student_id: int
  score: Optional[float]
  feedback: str
  updated_at: Optional[str]


@dataclass(frozen=True)
class AttendanceSession:
  """Sesi pertemuan pencatatan kehadiran untuk suatu kelas."""

  id: int
  class_id: int
  period_id: int
  session_date: str
  meeting_number: int
  topic: str
  created_at: str


@dataclass(frozen=True)
class AttendanceRecord:
  """Catatan status kehadiran peserta didik pada sesi pertemuan tertentu."""

  id: int
  session_id: int
  student_id: int
  status: AttendanceStatus
  note: str
  updated_at: str


@dataclass(frozen=True)
class ClassAnnouncement:
  """Pengumuman permanen searah dari guru untuk peserta didik pada kelas tertentu."""

  id: int
  class_id: int
  teacher_id: int
  title: str
  category: str
  content: str
  is_pinned: bool
  created_at: str
  updated_at: str
