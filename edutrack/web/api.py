"""Lapisan REST API FastAPI dengan injeksi dependensi dan penegakan RBAC sisi server."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import logging
import secrets
from pathlib import Path

logger = logging.getLogger(__name__)
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, File, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from edutrack.configs.app_config import AppConfig
from edutrack.domain.errors import DomainError, NotFoundError, ValidationError
from edutrack.domain.security import generate_secure_token
from edutrack.domain.models import (
    AccountStatus,
    AssessmentStatus,
    CalculationMode,
    CorrectionStatus,
    Role,
    User,
)
from edutrack.repositories.academic_repo import AcademicRepository
from edutrack.repositories.attendance_repo import AttendanceRepository
from edutrack.repositories.database import Database, to_iso_str
from edutrack.repositories.grade_repo import GradeRepository
from edutrack.repositories.user_repo import UserRepository
from edutrack.services.analytics_service import AnalyticsService
from edutrack.services.attendance_service import AttendanceService
from edutrack.services.auth_service import AuthService
from edutrack.services.classroom_service import ClassroomService
from edutrack.services.grade_service import GradeService
from edutrack.services.report_service import ReportService, iter_export_chunks
from edutrack.services.student_service import StudentService


# --- Pydantic Request Schemas ---


class LoginPayload(BaseModel):
  username: str
  password: str


class ChangePasswordPayload(BaseModel):
  current_password: str
  new_password: str


class ProfileUpdatePayload(BaseModel):
  full_name: Optional[str] = None
  email: Optional[str] = None
  username: Optional[str] = None


class LogoutAllPayload(BaseModel):
  keep_current: bool = False


class AnnouncementCreatePayload(BaseModel):
  title: str = Field(..., min_length=1, max_length=150)
  category: str = Field("Umum", min_length=1, max_length=60)
  content: str = Field(..., min_length=1, max_length=4000)
  is_pinned: bool = False


class AnnouncementUpdatePayload(BaseModel):
  title: Optional[str] = Field(None, min_length=1, max_length=150)
  category: Optional[str] = Field(None, min_length=1, max_length=60)
  content: Optional[str] = Field(None, min_length=1, max_length=4000)
  is_pinned: Optional[bool] = None


class StudentUsernamePayload(BaseModel):
  username: str = Field(..., min_length=3, max_length=64)



class PeriodCreatePayload(BaseModel):
  name: str
  academic_year: str
  semester: str
  is_active: bool = True


class PeriodStatePayload(BaseModel):
  is_active: Optional[bool] = None
  is_archived: Optional[bool] = None


class ClassroomCreatePayload(BaseModel):
  period_id: Optional[int] = None
  name: str
  education_level: str
  academic_year: Optional[str] = None
  description: str = ""
  calculation_mode: CalculationMode = CalculationMode.WEIGHTED
  mastery_threshold: Optional[float] = None
  allow_student_report_download: bool = True


class ClassroomUpdatePayload(BaseModel):
  name: Optional[str] = None
  education_level: Optional[str] = None
  academic_year: Optional[str] = None
  description: Optional[str] = None
  calculation_mode: Optional[CalculationMode] = None
  mastery_threshold: Optional[float] = None
  allow_student_report_download: Optional[bool] = None
  is_archived: Optional[bool] = None


class StudentCreatePayload(BaseModel):
  class_id: int
  full_name: str
  student_code: str
  username: Optional[str] = None
  initial_password: Optional[str] = None
  notes: str = ""
  account_status: AccountStatus = AccountStatus.PENDING_ACTIVATION


class StudentUpdatePayload(BaseModel):
  full_name: Optional[str] = None
  student_code: Optional[str] = None
  notes: Optional[str] = None
  account_status: Optional[AccountStatus] = None
  username: Optional[str] = None


class StudentMovePayload(BaseModel):
  target_class_id: int


class ResetStudentPasswordPayload(BaseModel):
  new_temporary_password: Optional[str] = None


class MaterialCreatePayload(BaseModel):
  title: str
  description: str = ""
  sort_order: Optional[int] = None


class MaterialUpdatePayload(BaseModel):
  title: Optional[str] = None
  description: Optional[str] = None
  sort_order: Optional[int] = None
  is_archived: Optional[bool] = None


class BulkDeleteStudentsPayload(BaseModel):
  delete_all: bool = False
  student_ids: List[int] = Field(default_factory=list)
  mode: str = "archive"
  confirm: bool = False


class AssessmentCreatePayload(BaseModel):
  title: str
  category: str
  assessment_date: str
  description: str = ""
  max_score: float = 100.0
  weight: float = 1.0
  status: AssessmentStatus = AssessmentStatus.DRAFT
  material_id: Optional[int] = None
  is_graded: bool = True


class AssessmentUpdatePayload(BaseModel):
  title: Optional[str] = None
  category: Optional[str] = None
  assessment_date: Optional[str] = None
  description: Optional[str] = None
  max_score: Optional[float] = None
  weight: Optional[float] = None
  status: Optional[AssessmentStatus] = None
  material_id: Optional[int] = None
  is_graded: Optional[bool] = None


class GradeItemPayload(BaseModel):
  student_id: int
  score: Optional[float] = None
  feedback: str = ""


class BulkGradesPayload(BaseModel):
  entries: List[GradeItemPayload] = Field(default_factory=list)
  reason: str = ""


class AttendanceSessionCreatePayload(BaseModel):
  session_date: str
  meeting_number: int = 1
  topic: str = ""
  mark_all_present: bool = False


class ClassroomResetPayload(BaseModel):
  reset_grades: bool = True
  reset_attendance: bool = True


class AttendanceSessionUpdatePayload(BaseModel):
  session_date: Optional[str] = None
  meeting_number: Optional[int] = None
  topic: Optional[str] = None


class AttendanceEntryPayload(BaseModel):
  student_id: int
  status: str
  note: str = ""


class AttendanceSavePayload(BaseModel):
  entries: List[AttendanceEntryPayload] = Field(default_factory=list)
  reason: str = ""


class CorrectionCreatePayload(BaseModel):
  target_type: str
  target_id: int
  message: str


class CorrectionRespondPayload(BaseModel):
  status: CorrectionStatus
  teacher_response: str = ""


class BackupCreatePayload(BaseModel):
  label: str = "manual"


class BackupRestorePayload(BaseModel):
  filename: str


class AppContainer:
  """Wadah dependensi seluruh repositori dan layanan aplikasi."""

  def __init__(self, config: AppConfig) -> None:
    self.config = config
    self.db = Database(config.db_path, backup_dir=config.backup_dir, database_url=config.database_url)
    self.user_repo = UserRepository(self.db)
    self.academic_repo = AcademicRepository(self.db)
    self.grade_repo = GradeRepository(self.db)
    self.attendance_repo = AttendanceRepository(self.db)

    self.auth_service = AuthService(self.user_repo, config)
    self.classroom_service = ClassroomService(
        self.academic_repo, self.user_repo, config
    )
    self.student_service = StudentService(
        self.academic_repo, self.user_repo, config
    )
    self.grade_service = GradeService(
        self.grade_repo, self.academic_repo, self.user_repo
    )
    self.attendance_service = AttendanceService(
        self.attendance_repo,
        self.academic_repo,
        self.grade_repo,
        self.user_repo,
        config,
    )
    self.analytics_service = AnalyticsService(
        self.academic_repo, self.grade_repo, self.attendance_repo, config,
        attendance_service=self.attendance_service,
    )
    self.report_service = ReportService(
        self.grade_service, self.analytics_service, self.academic_repo
    )


def _serialize(obj: Any) -> Any:
  """Mengonversi dataclass dan Enum secara rekursif untuk respons JSON."""
  if hasattr(obj, "__dataclass_fields__"):
    return {k: _serialize(v) for k, v in asdict(obj).items()}
  if isinstance(obj, list):
    return [_serialize(i) for i in obj]
  if isinstance(obj, dict):
    return {k: _serialize(v) for k, v in obj.items()}
  if isinstance(obj, datetime):
    return to_iso_str(obj)
  if hasattr(obj, "value"):
    return obj.value
  return obj


def create_app(config: Optional[AppConfig] = None) -> FastAPI:
  """Factory FastAPI utama dengan injeksi AppConfig."""
  cfg = config or AppConfig()
  container = AppContainer(cfg)
  app = FastAPI(title="Bahasa Indonesia — Sistem Administrasi Pembelajaran", version="1.0.0")

  @app.middleware("http")
  async def add_security_headers(request: Request, call_next):
    # Proteksi Double-Submit CSRF pada permintaan mutasi yang memakai cookie sesi HttpOnly
    if (
        request.method in ("POST", "PUT", "PATCH", "DELETE")
        and request.url.path != "/api/auth/login"
        and request.cookies.get(cfg.cookie_name)
    ):
      cookie_csrf = request.cookies.get(cfg.csrf_cookie_name, "")
      header_csrf = request.headers.get("X-CSRF-Token", "")
      if not cookie_csrf or not header_csrf or not secrets.compare_digest(cookie_csrf, header_csrf):
        return JSONResponse(
            status_code=403,
            content={
                "detail": "Verifikasi CSRF gagal. Muat ulang halaman lalu coba lagi.",
                "code": "csrf_failed",
            },
        )
    with container.db.request_scope():
      response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    path = request.url.path
    if path == "/sw.js":
      response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    elif path in ("/", "/manifest.json") or path.endswith(".html"):
      response.headers["Cache-Control"] = "no-cache, must-revalidate"
    elif path.startswith("/static/"):
      response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response
  app.state.container = container

  static_dir = Path(__file__).parent / "static"
  if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

  @app.exception_handler(DomainError)
  async def _handle_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"detail": exc.message, "code": exc.code},
        headers=getattr(exc, "headers", None),
    )

  @app.exception_handler(Exception)
  async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Terjadi kesalahan internal pada server. Silakan muat ulang halaman atau coba lagi.",
            "code": "internal_server_error",
        },
    )

  def _extract_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
      return auth_header[7:].strip()
    return request.cookies.get(cfg.cookie_name)

  def get_current_user(request: Request) -> User:
    return container.auth_service.authenticate_token(_extract_token(request))

  def get_current_teacher(user: User = Depends(get_current_user)) -> User:
    AuthService.require_roles(user, (Role.TEACHER, Role.ADMIN))
    return user

  def get_current_admin(user: User = Depends(get_current_user)) -> User:
    AuthService.require_role(user, Role.ADMIN)
    return user

  def get_current_student(user: User = Depends(get_current_user)) -> User:
    AuthService.require_role(user, Role.STUDENT)
    return user

  def _set_csrf_cookie(response: Response) -> str:
    token = generate_secure_token(32)
    response.set_cookie(
        key=cfg.csrf_cookie_name,
        value=token,
        httponly=False,
        samesite="lax",
        secure=cfg.cookie_secure,
        path="/",
        max_age=cfg.session_ttl_hours * 3600,
    )
    return token

  def _set_auth_cookies(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=cfg.cookie_name,
        value=raw_token,
        httponly=True,
        samesite="lax",
        secure=cfg.cookie_secure,
        path="/",
        max_age=cfg.session_ttl_hours * 3600,
    )
    _set_csrf_cookie(response)

  def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(key=cfg.cookie_name, path="/")
    response.delete_cookie(key=cfg.csrf_cookie_name, path="/")

  def _paginate(items: List[Any], limit: Optional[int], offset: int) -> tuple[List[Any], Dict[str, Any]]:
    if offset < 0:
      raise ValidationError("Parameter offset harus >= 0.")
    if limit is not None and (limit < 1 or limit > 500):
      raise ValidationError("Parameter limit harus antara 1 dan 500.")
    total = len(items)
    sliced = items[offset : offset + limit] if limit is not None else items[offset:]
    return sliced, {"total": total, "limit": limit, "offset": offset, "returned": len(sliced)}

  # --- Frontend Entry ---

  def _extract_client_ip(request: Request) -> str:
    vf = request.headers.get("x-vercel-forwarded-for")
    if vf:
      return vf.split(",")[0].strip()
    ri = request.headers.get("x-real-ip")
    if ri:
      return ri.strip()
    return request.client.host if request.client and request.client.host else "unknown"

  @app.get("/", include_in_schema=False)
  def serve_index() -> Response:
    index_path = static_dir / "index.html"
    if not index_path.exists():
      return JSONResponse({"status": "ok", "message": "Bahasa Indonesia API aktif."})
    return FileResponse(str(index_path))

  @app.get("/manifest.json", include_in_schema=False)
  def serve_manifest() -> Response:
    mpath = static_dir / "manifest.json"
    if not mpath.exists():
      raise NotFoundError("manifest.json tidak ditemukan.")
    return FileResponse(str(mpath), media_type="application/manifest+json")

  @app.get("/sw.js", include_in_schema=False)
  def serve_service_worker() -> Response:
    swpath = static_dir / "sw.js"
    if not swpath.exists():
      raise NotFoundError("sw.js tidak ditemukan.")
    return FileResponse(
        str(swpath),
        media_type="application/javascript; charset=utf-8",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )

  # --- Auth Endpoints ---

  @app.post("/api/auth/login")
  def login(payload: LoginPayload, request: Request, response: Response) -> Dict[str, Any]:
    result = container.auth_service.login(
        payload.username,
        payload.password,
        user_agent=request.headers.get("user-agent", ""),
        ip_address=_extract_client_ip(request),
    )
    _set_auth_cookies(response, str(result["token"]))
    return {
        "expires_at": result["expires_at"],
        "user": _serialize(result["user"]),
    }

  @app.post("/api/auth/logout")
  def logout(request: Request, response: Response) -> Dict[str, str]:
    container.auth_service.logout(_extract_token(request))
    _clear_auth_cookies(response)
    return {"status": "ok"}

  @app.get("/api/auth/me")
  def me(
      request: Request,
      response: Response,
      refresh_csrf: bool = False,
      user: User = Depends(get_current_user),
  ) -> Dict[str, Any]:
    if request.cookies.get(cfg.cookie_name) and (
        not request.cookies.get(cfg.csrf_cookie_name) or refresh_csrf
    ):
      _set_csrf_cookie(response)
    return {"user": _serialize(user)}

  @app.post("/api/auth/ping")
  def auth_ping(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return {
        "status": "active",
        "user_id": user.id,
        "idle_timeout_minutes": container.config.session_idle_timeout_minutes,
    }

  @app.post("/api/auth/change-password")
  def change_password(
      payload: ChangePasswordPayload,
      request: Request,
      response: Response,
      user: User = Depends(get_current_user),
  ) -> Dict[str, Any]:
    updated = container.auth_service.change_password(
        user, payload.current_password, payload.new_password
    )
    fresh = container.auth_service.issue_session(
        updated,
        user_agent=request.headers.get("user-agent", ""),
        ip_address=_extract_client_ip(request),
    )
    _set_auth_cookies(response, str(fresh["token"]))
    return {"user": _serialize(updated), "sessions_revoked": True}

  @app.get("/api/health")
  def health_check() -> JSONResponse:
    backend = "postgresql" if container.db.is_postgres else "sqlite"
    try:
      with container.db.connection() as conn:
        conn.execute("SELECT 1").fetchone()
      return JSONResponse(
          status_code=200,
          content={"status": "ok", "database_backend": backend, "database_connected": True},
      )
    except Exception:  # pylint: disable=broad-except
      logger.exception("Health check database failure")
      return JSONResponse(
          status_code=503,
          content={
              "status": "degraded",
              "database_backend": backend,
              "database_connected": False,
          },
      )

  @app.patch("/api/auth/profile")
  def update_profile(
      payload: ProfileUpdatePayload, user: User = Depends(get_current_user)
  ) -> Dict[str, Any]:
    updated = container.auth_service.update_own_profile(
        user,
        full_name=payload.full_name,
        email=payload.email,
        username=payload.username,
    )
    return {"user": _serialize(updated)}

  @app.get("/api/auth/sessions")
  def list_sessions(
      request: Request, user: User = Depends(get_current_user)
  ) -> Dict[str, Any]:
    return {
        "sessions": container.auth_service.list_active_sessions(user, _extract_token(request))
    }

  @app.delete("/api/auth/sessions/{session_id}")
  def revoke_session(
      session_id: int,
      request: Request,
      response: Response,
      user: User = Depends(get_current_user),
  ) -> Dict[str, Any]:
    res = container.auth_service.revoke_session_by_id(
        user, session_id, _extract_token(request)
    )
    if res.get("revoked_current"):
      _clear_auth_cookies(response)
    return res

  @app.post("/api/auth/logout-all")
  def logout_all_devices(
      request: Request,
      response: Response,
      payload: Optional[LogoutAllPayload] = None,
      user: User = Depends(get_current_user),
  ) -> Dict[str, Any]:
    keep = bool(payload.keep_current) if payload else False
    res = container.auth_service.logout_all_devices(
        user, _extract_token(request), keep_current=keep
    )
    if res.get("revoked_current"):
      _clear_auth_cookies(response)
    return res


  # --- Teacher: Periods ---

  @app.get("/api/teacher/periods")
  def list_periods(
      include_archived: bool = True,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    periods = container.classroom_service.list_periods(
        teacher, include_archived=include_archived
    )
    return {"periods": _serialize(periods)}

  @app.post("/api/teacher/periods", status_code=201)
  def create_period(
      payload: PeriodCreatePayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    period = container.classroom_service.create_period(
        teacher,
        name=payload.name,
        academic_year=payload.academic_year,
        semester=payload.semester,
        is_active=payload.is_active,
    )
    return {"period": _serialize(period)}

  @app.patch("/api/teacher/periods/{period_id}")
  def update_period_state(
      period_id: int,
      payload: PeriodStatePayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    period = container.classroom_service.update_period_state(
        teacher, period_id, is_active=payload.is_active, is_archived=payload.is_archived
    )
    return {"period": _serialize(period)}

  # --- Teacher: Classes ---

  @app.get("/api/teacher/classes")
  def list_classes(
      period_id: Optional[int] = None,
      include_archived: bool = False,
      limit: Optional[int] = None,
      offset: int = 0,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    classes = container.classroom_service.list_classrooms(
        teacher, period_id=period_id, include_archived=include_archived
    )
    page, meta = _paginate(classes, limit, offset)
    return {"classes": _serialize(page), "pagination": meta}

  @app.post("/api/teacher/classes", status_code=201)
  def create_class(
      payload: ClassroomCreatePayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    classroom = container.classroom_service.create_classroom(
        teacher=teacher,
        period_id=payload.period_id,
        name=payload.name,
        education_level=payload.education_level,
        academic_year=payload.academic_year,
        description=payload.description,
        calculation_mode=payload.calculation_mode,
        mastery_threshold=payload.mastery_threshold,
        allow_student_report_download=payload.allow_student_report_download,
    )
    return {"classroom": _serialize(classroom)}

  @app.get("/api/teacher/classes/{class_id}")
  def get_class(
      class_id: int, teacher: User = Depends(get_current_teacher)
  ) -> Dict[str, Any]:
    cls = container.classroom_service.get_owned_classroom(teacher, class_id)
    return {"classroom": _serialize(cls)}

  @app.patch("/api/teacher/classes/{class_id}")
  def update_class(
      class_id: int,
      payload: ClassroomUpdatePayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    cls = container.classroom_service.update_classroom(
        teacher=teacher,
        class_id=class_id,
        name=payload.name,
        education_level=payload.education_level,
        academic_year=payload.academic_year,
        description=payload.description,
        calculation_mode=payload.calculation_mode,
        mastery_threshold=payload.mastery_threshold,
        allow_student_report_download=payload.allow_student_report_download,
        is_archived=payload.is_archived,
    )
    return {"classroom": _serialize(cls)}

  @app.get("/api/teacher/classes/{class_id}/dependencies")
  def get_class_dependencies(
      class_id: int, teacher: User = Depends(get_current_teacher)
  ) -> Dict[str, Any]:
    return container.classroom_service.get_classroom_dependencies(teacher, class_id)

  @app.delete("/api/teacher/classes/{class_id}")
  def delete_class(
      class_id: int,
      confirm_permanent: bool = False,
      force: bool = False,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, str]:
    container.classroom_service.delete_classroom(
        teacher, class_id, confirm_permanent=confirm_permanent, force=force
    )
    return {"status": "deleted"}

  @app.post("/api/teacher/classes/{class_id}/reset")
  def reset_class_data(
      class_id: int,
      payload: ClassroomResetPayload = ClassroomResetPayload(),
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    result = container.classroom_service.reset_classroom_data(
        teacher,
        class_id,
        reset_grades=payload.reset_grades,
        reset_attendance=payload.reset_attendance,
    )
    return {"status": "reset", **result}

  # --- Teacher: Students ---

  @app.get("/api/teacher/students")
  def list_students(
      class_id: Optional[int] = None,
      status: Optional[AccountStatus] = None,
      search: Optional[str] = None,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    students = container.student_service.list_students(
        teacher, class_id=class_id, status=status, search=search
    )
    return {"students": _serialize(students)}

  @app.post("/api/teacher/students", status_code=201)
  def create_student(
      payload: StudentCreatePayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    res = container.student_service.create_student_with_account(
        teacher=teacher,
        class_id=payload.class_id,
        full_name=payload.full_name,
        student_code=payload.student_code,
        username=payload.username,
        initial_password=payload.initial_password,
        notes=payload.notes,
        account_status=payload.account_status,
    )
    return {
        "student": _serialize(res["student"]),
        "username": res["username"],
        "initial_password": res["initial_password"],
    }

  @app.patch("/api/teacher/students/{student_id}")
  def update_student(
      student_id: int,
      payload: StudentUpdatePayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    stu = container.student_service.update_student(
        teacher=teacher,
        student_id=student_id,
        full_name=payload.full_name,
        student_code=payload.student_code,
        notes=payload.notes,
        account_status=payload.account_status,
        username=payload.username,
    )
    return {"student": _serialize(stu)}

  @app.post("/api/teacher/students/{student_id}/move")
  def move_student(
      student_id: int,
      payload: StudentMovePayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    stu = container.student_service.move_student(
        teacher, student_id, payload.target_class_id
    )
    return {"student": _serialize(stu)}

  @app.post("/api/teacher/students/{student_id}/reset-credentials")
  def reset_student_credentials(
      student_id: int, teacher: User = Depends(get_current_teacher)
  ) -> Dict[str, Any]:
    return container.student_service.reset_student_credentials(teacher, student_id)

  @app.patch("/api/student/username")
  def update_student_username(
      payload: StudentUsernamePayload, student: User = Depends(get_current_student)
  ) -> Dict[str, Any]:
    updated = container.student_service.update_student_username(student, payload.username)
    return {"user": _serialize(updated)}

  @app.post("/api/teacher/students/{student_id}/reset-password")
  def reset_student_password(
      student_id: int,
      payload: ResetStudentPasswordPayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, str]:
    return container.student_service.reset_student_password(
        teacher, student_id, new_temporary_password=payload.new_temporary_password
    )

  @app.delete("/api/teacher/students/{student_id}")
  def delete_student(
      student_id: int,
      confirm_permanent: bool = False,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, str]:
    container.student_service.delete_student(
        teacher, student_id, confirm_permanent=confirm_permanent
    )
    return {"status": "deleted"}

  @app.get("/api/teacher/classes/{class_id}/students/bulk-delete-preview")
  def preview_bulk_delete_students(
      class_id: int,
      student_ids: Optional[str] = None,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    parsed_ids = None
    if student_ids:
      try:
        parsed_ids = [int(x.strip()) for x in student_ids.split(",") if x.strip()]
      except ValueError as exc:
        raise ValidationError("Parameter student_ids harus berupa daftar angka ID yang dipisahkan koma.") from exc
    return container.student_service.preview_bulk_delete_students(teacher, class_id, student_ids=parsed_ids)

  @app.post("/api/teacher/classes/{class_id}/students/bulk-delete")
  def bulk_delete_students(
      class_id: int,
      payload: BulkDeleteStudentsPayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    return container.student_service.bulk_delete_students(
        teacher=teacher,
        class_id=class_id,
        delete_all=payload.delete_all,
        student_ids=payload.student_ids,
        mode=payload.mode,
        confirm=payload.confirm,
    )

  @app.get("/api/teacher/students/import-template")
  def download_student_import_template(
      teacher: User = Depends(get_current_teacher),
  ) -> StreamingResponse:
    del teacher
    data = container.student_service.generate_student_import_template()
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="template_impor_peserta_didik.xlsx"'},
    )

  @app.post("/api/teacher/classes/{class_id}/students/import/preview")
  async def preview_import_students(
      class_id: int,
      file: UploadFile = File(...),
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    max_bytes = 4 * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
      raise ValidationError("Ukuran berkas impor melebihi batas maksimum 4 MB.")
    return container.student_service.preview_student_import(
        teacher, class_id, file.filename or "template.xlsx", content
    )

  @app.post("/api/teacher/classes/{class_id}/students/import/confirm")
  async def confirm_import_students(
      class_id: int,
      file: UploadFile = File(...),
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    max_bytes = 4 * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
      raise ValidationError("Ukuran berkas impor melebihi batas maksimum 4 MB.")
    return container.student_service.confirm_student_import(
        teacher, class_id, file.filename or "template.xlsx", content
    )

  @app.post("/api/teacher/classes/{class_id}/students/import")
  async def import_students(
      class_id: int,
      file: UploadFile = File(...),
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    max_bytes = 4 * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
      raise ValidationError("Ukuran berkas impor melebihi batas maksimum 4 MB.")
    return container.student_service.import_students(
        teacher, class_id, file.filename or "import.csv", content
    )

  # --- Teacher: Learning Materials ---

  @app.get("/api/teacher/classes/{class_id}/materials")
  def list_materials(
      class_id: int,
      include_archived: bool = False,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    items = container.grade_service.list_materials(teacher, class_id, include_archived=include_archived)
    return {"materials": _serialize(items)}

  @app.post("/api/teacher/classes/{class_id}/materials", status_code=201)
  def create_material(
      class_id: int,
      payload: MaterialCreatePayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    mat = container.grade_service.create_material(
        teacher, class_id, title=payload.title, description=payload.description, sort_order=payload.sort_order
    )
    return {"material": _serialize(mat)}

  @app.patch("/api/teacher/materials/{material_id}")
  def update_material(
      material_id: int,
      payload: MaterialUpdatePayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    mat = container.grade_service.update_material(
        teacher,
        material_id,
        title=payload.title,
        description=payload.description,
        sort_order=payload.sort_order,
        is_archived=payload.is_archived,
    )
    return {"material": _serialize(mat)}

  @app.delete("/api/teacher/materials/{material_id}")
  def delete_material(
      material_id: int, teacher: User = Depends(get_current_teacher)
  ) -> Dict[str, str]:
    container.grade_service.delete_material(teacher, material_id)
    return {"status": "deleted"}

  # --- Teacher: Assessments & Grades ---

  @app.get("/api/teacher/classes/{class_id}/assessments")
  def list_assessments(
      class_id: int,
      limit: Optional[int] = None,
      offset: int = 0,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    items = container.grade_service.list_assessments(teacher, class_id)
    page, meta = _paginate(items, limit, offset)
    return {"assessments": _serialize(page), "pagination": meta}

  @app.post("/api/teacher/classes/{class_id}/assessments", status_code=201)
  def create_assessment(
      class_id: int,
      payload: AssessmentCreatePayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    asmt = container.grade_service.create_assessment(
        teacher=teacher,
        class_id=class_id,
        title=payload.title,
        category=payload.category,
        assessment_date=payload.assessment_date,
        description=payload.description,
        max_score=payload.max_score,
        weight=payload.weight,
        status=payload.status,
        material_id=payload.material_id,
        is_graded=payload.is_graded,
    )
    return {"assessment": _serialize(asmt)}

  @app.patch("/api/teacher/assessments/{assessment_id}")
  def update_assessment(
      assessment_id: int,
      payload: AssessmentUpdatePayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    fields_set = getattr(payload, "model_fields_set", getattr(payload, "__fields_set__", set()))
    asmt = container.grade_service.update_assessment(
        teacher=teacher,
        assessment_id=assessment_id,
        title=payload.title,
        category=payload.category,
        assessment_date=payload.assessment_date,
        description=payload.description,
        max_score=payload.max_score,
        weight=payload.weight,
        status=payload.status,
        material_id=payload.material_id,
        update_material_id=("material_id" in fields_set),
        is_graded=payload.is_graded,
    )
    return {"assessment": _serialize(asmt)}

  @app.delete("/api/teacher/assessments/{assessment_id}")
  def delete_assessment(
      assessment_id: int, teacher: User = Depends(get_current_teacher)
  ) -> Dict[str, str]:
    container.grade_service.delete_assessment(teacher, assessment_id)
    return {"status": "deleted"}

  @app.get("/api/teacher/assessments/{assessment_id}/import-template")
  def download_grade_import_template(
      assessment_id: int,
      teacher: User = Depends(get_current_teacher),
  ) -> StreamingResponse:
    filename, data = container.grade_service.generate_grade_import_template(teacher, assessment_id)
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

  @app.post("/api/teacher/assessments/{assessment_id}/grades/import/preview")
  async def preview_import_grades(
      assessment_id: int,
      file: UploadFile = File(...),
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    max_bytes = 4 * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
      raise ValidationError("Ukuran berkas nilai melebihi batas maksimum 4 MB.")
    return container.grade_service.preview_grade_import(
        teacher, assessment_id, file.filename or "nilai.xlsx", content
    )

  @app.post("/api/teacher/assessments/{assessment_id}/grades/import/confirm")
  async def confirm_import_grades(
      assessment_id: int,
      conflict_mode: str = "skip",
      file: UploadFile = File(...),
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    max_bytes = 4 * 1024 * 1024
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
      raise ValidationError("Ukuran berkas nilai melebihi batas maksimum 4 MB.")
    return container.grade_service.confirm_grade_import(
        teacher, assessment_id, file.filename or "nilai.xlsx", content, conflict_mode=conflict_mode
    )

  @app.post("/api/teacher/assessments/{assessment_id}/grades")
  def save_grades(
      assessment_id: int,
      payload: BulkGradesPayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    entries = [(e.model_dump() if hasattr(e, "model_dump") else e.dict()) for e in payload.entries]
    saved = container.grade_service.save_grades_bulk(
        teacher, assessment_id, entries, reason=payload.reason
    )
    return {"saved": saved}

  @app.delete("/api/teacher/assessments/{assessment_id}/grades")
  def reset_assessment_grades(
      assessment_id: int,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    deleted = container.grade_service.reset_assessment_grades(teacher, assessment_id)
    return {"status": "deleted", "deleted": deleted}

  @app.get("/api/teacher/classes/{class_id}/gradebook")
  def get_gradebook(
      class_id: int,
      material_id: Optional[int] = None,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    return _serialize(container.grade_service.get_class_gradebook(teacher, class_id, material_id=material_id))

  @app.get("/api/teacher/classes/{class_id}/grade-history")
  def get_grade_history(
      class_id: int,
      assessment_id: Optional[int] = None,
      student_id: Optional[int] = None,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    items = container.grade_service.list_grade_history(
        teacher, class_id, assessment_id=assessment_id, student_id=student_id
    )
    return {"history": items}

  # --- Teacher: Attendance ---

  @app.get("/api/teacher/classes/{class_id}/attendance/sessions")
  def list_att_sessions(
      class_id: int,
      date_from: Optional[str] = None,
      date_to: Optional[str] = None,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    sessions = container.attendance_service.list_sessions(
        teacher, class_id, date_from=date_from, date_to=date_to
    )
    return {"sessions": _serialize(sessions)}

  @app.post("/api/teacher/classes/{class_id}/attendance/sessions", status_code=201)
  def create_att_session(
      class_id: int,
      payload: AttendanceSessionCreatePayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    res = container.attendance_service.create_session(
        teacher=teacher,
        class_id=class_id,
        session_date=payload.session_date,
        meeting_number=payload.meeting_number,
        topic=payload.topic,
        mark_all_present=payload.mark_all_present,
    )
    return _serialize(res)

  @app.get("/api/teacher/attendance/sessions/{session_id}")
  def get_att_session(
      session_id: int, teacher: User = Depends(get_current_teacher)
  ) -> Dict[str, Any]:
    return _serialize(container.attendance_service.get_session_detail(teacher, session_id))

  @app.post("/api/teacher/attendance/sessions/{session_id}/records")
  def save_att_records(
      session_id: int,
      payload: AttendanceSavePayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    saved = container.attendance_service.save_session_attendance(
        teacher, session_id, [(e.model_dump() if hasattr(e, "model_dump") else e.dict()) for e in payload.entries], reason=payload.reason
    )
    return {"saved": saved}

  @app.post("/api/teacher/attendance/sessions/{session_id}/mark-all-present")
  def mark_all_present(
      session_id: int, teacher: User = Depends(get_current_teacher)
  ) -> Dict[str, Any]:
    saved = container.attendance_service.mark_all_present(teacher, session_id)
    return {"saved": saved}

  @app.patch("/api/teacher/attendance/sessions/{session_id}")
  def update_att_session(
      session_id: int,
      payload: AttendanceSessionUpdatePayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    session = container.attendance_service.update_session(
        teacher,
        session_id,
        session_date=payload.session_date,
        meeting_number=payload.meeting_number,
        topic=payload.topic,
    )
    return {"session": _serialize(session)}

  @app.delete("/api/teacher/attendance/sessions/{session_id}")
  def delete_att_session(
      session_id: int, teacher: User = Depends(get_current_teacher)
  ) -> Dict[str, str]:
    container.attendance_service.delete_session(teacher, session_id)
    return {"status": "deleted"}

  @app.delete("/api/teacher/classes/{class_id}/attendance/sessions")
  def delete_all_att_sessions(
      class_id: int, teacher: User = Depends(get_current_teacher)
  ) -> Dict[str, Any]:
    deleted = container.attendance_service.delete_all_sessions_for_class(teacher, class_id)
    return {"status": "deleted", "deleted_sessions": deleted}

  @app.post("/api/teacher/attendance/sessions/{session_id}/reset")
  def reset_att_session(
      session_id: int, teacher: User = Depends(get_current_teacher)
  ) -> Dict[str, Any]:
    cleared = container.attendance_service.reset_session(teacher, session_id)
    return {"status": "reset", "cleared": cleared}

  @app.get("/api/teacher/classes/{class_id}/attendance/recap")
  def get_att_recap(
      class_id: int,
      granularity: str = "monthly",
      date_from: Optional[str] = None,
      date_to: Optional[str] = None,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    return container.analytics_service.get_attendance_recap(
        teacher, class_id, granularity=granularity, date_from=date_from, date_to=date_to
    )

  @app.get("/api/teacher/classes/{class_id}/attendance/history")
  def get_att_history(
      class_id: int, teacher: User = Depends(get_current_teacher)
  ) -> Dict[str, Any]:
    return {"history": container.attendance_service.list_attendance_history(teacher, class_id)}

  # --- Teacher: Dashboard, Analytics, Corrections, Audit & Backup ---

  @app.get("/api/teacher/dashboard")
  def teacher_dashboard(
      period_id: Optional[int] = None,
      class_id: Optional[int] = None,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    return container.analytics_service.get_teacher_dashboard(
        teacher, period_id=period_id, class_id=class_id
    )

  @app.get("/api/teacher/early-warning")
  def teacher_early_warning(
      period_id: Optional[int] = None,
      class_id: Optional[int] = None,
      alpa_threshold: Optional[int] = None,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    return container.analytics_service.get_early_warning_report(
        teacher, class_id=class_id, period_id=period_id, alpa_threshold=alpa_threshold
    )

  # --- Teacher & Student: Class Announcements ---

  @app.get("/api/teacher/classes/{class_id}/announcements")
  def list_class_announcements(
      class_id: int, teacher: User = Depends(get_current_teacher)
  ) -> Dict[str, Any]:
    items = container.classroom_service.list_announcements(teacher, class_id)
    return {"announcements": _serialize(items)}

  @app.post("/api/teacher/classes/{class_id}/announcements", status_code=201)
  def create_class_announcement(
      class_id: int,
      payload: AnnouncementCreatePayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    ann = container.classroom_service.create_announcement(
        teacher=teacher,
        class_id=class_id,
        title=payload.title,
        content=payload.content,
        category=payload.category,
        is_pinned=payload.is_pinned,
    )
    return {"announcement": _serialize(ann)}

  @app.patch("/api/teacher/announcements/{announcement_id}")
  def update_class_announcement(
      announcement_id: int,
      payload: AnnouncementUpdatePayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    ann = container.classroom_service.update_announcement(
        teacher=teacher,
        announcement_id=announcement_id,
        title=payload.title,
        category=payload.category,
        content=payload.content,
        is_pinned=payload.is_pinned,
    )
    return {"announcement": _serialize(ann)}

  @app.delete("/api/teacher/announcements/{announcement_id}")
  def delete_class_announcement(
      announcement_id: int, teacher: User = Depends(get_current_teacher)
  ) -> Dict[str, str]:
    container.classroom_service.delete_announcement(teacher, announcement_id)
    return {"status": "deleted"}

  @app.get("/api/student/announcements")
  def student_announcements(
      student: User = Depends(get_current_student),
  ) -> Dict[str, Any]:
    items = container.classroom_service.list_announcements_for_student(student)
    return {"announcements": _serialize(items)}

  @app.get("/api/teacher/students/{student_id}/progress")
  def teacher_student_progress(
      student_id: int, teacher: User = Depends(get_current_teacher)
  ) -> Dict[str, Any]:
    return container.analytics_service.get_student_progress_for_teacher(
        teacher, student_id
    )

  @app.get("/api/teacher/classes/{class_id}/compare")
  def teacher_compare_students(
      class_id: int,
      student_ids: str = Query(..., description="Daftar ID dipisah koma, mis. 1,2,3"),
      material_id: Optional[int] = None,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    try:
      ids = [int(x.strip()) for x in student_ids.split(",") if x.strip()]
    except ValueError as exc:
      raise ValidationError("Parameter student_ids harus berupa angka dipisah koma.") from exc
    if not ids:
      raise ValidationError("Pilih minimal satu peserta didik untuk dibandingkan.")
    return container.analytics_service.compare_students_for_teacher(
        teacher, class_id, ids, material_id=material_id
    )

  @app.get("/api/teacher/corrections")
  def teacher_corrections(
      status: Optional[CorrectionStatus] = None,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    return {
        "corrections": container.attendance_service.list_teacher_corrections(
            teacher, status=status
        )
    }

  @app.patch("/api/teacher/corrections/{request_id}")
  def respond_correction(
      request_id: int,
      payload: CorrectionRespondPayload,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    updated = container.attendance_service.respond_correction_request(
        teacher, request_id, payload.status, payload.teacher_response
    )
    return {"correction": updated}

  @app.delete("/api/teacher/corrections/{request_id}")
  def delete_teacher_correction(
      request_id: int,
      teacher: User = Depends(get_current_teacher),
  ) -> Dict[str, Any]:
    return container.attendance_service.delete_teacher_correction(teacher, request_id)

  @app.get("/api/teacher/audit-logs")
  def teacher_audit_logs(
      limit: int = 80, teacher: User = Depends(get_current_teacher)
  ) -> Dict[str, Any]:
    return {"logs": container.user_repo.list_audit_logs(actor_user_id=teacher.id, limit=limit)}

  @app.get("/api/teacher/backups")
  def list_backups(_admin: User = Depends(get_current_admin)) -> Dict[str, Any]:
    return {"backups": container.db.list_backups()}

  @app.post("/api/teacher/backups", status_code=201)
  def create_backup(
      payload: BackupCreatePayload, teacher: User = Depends(get_current_admin)
  ) -> Dict[str, Any]:
    filename = container.db.create_backup(label=payload.label)
    container.user_repo.log_audit(
        teacher.id, "create_backup", "database", filename, "Cadangan basis data dibuat."
    )
    return {"filename": filename}

  @app.post("/api/teacher/backups/restore")
  def restore_backup(
      payload: BackupRestorePayload, teacher: User = Depends(get_current_admin)
  ) -> Dict[str, str]:
    container.db.restore_backup(payload.filename)
    container.user_repo.log_audit(
        teacher.id, "restore_backup", "database", payload.filename, "Basis data dipulihkan."
    )
    return {"status": "restored", "filename": payload.filename}

  # --- Reports & Export ---

  @app.get("/api/reports/class/{class_id}/grades")
  def report_class_grades(
      class_id: int,
      fmt: str = "xlsx",
      teacher: User = Depends(get_current_teacher),
  ) -> StreamingResponse:
    data, media_type, fname = container.report_service.export_class_grades(
        teacher, class_id, fmt
    )
    return StreamingResponse(
        iter([data]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )

  @app.get("/api/reports/class/{class_id}/attendance")
  def report_class_attendance(
      class_id: int,
      fmt: str = "xlsx",
      date_from: Optional[str] = None,
      date_to: Optional[str] = None,
      teacher: User = Depends(get_current_teacher),
  ) -> StreamingResponse:
    data, media_type, fname = container.report_service.export_attendance_recap(
        teacher, class_id, fmt, date_from=date_from, date_to=date_to
    )
    return StreamingResponse(
        iter([data]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )

  @app.get("/api/reports/individual")
  def report_individual(
      student_id: Optional[int] = None,
      fmt: str = "pdf",
      user: User = Depends(get_current_user),
  ) -> StreamingResponse:
    data, media_type, fname = container.report_service.export_individual_progress(
        user, student_id, fmt
    )
    return StreamingResponse(
        iter([data]),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )

  # --- Student Endpoints (Strictly Scoped to Own Account) ---

  @app.get("/api/student/dashboard")
  def student_dashboard(
      period_id: Optional[int] = None,
      month: Optional[str] = None,
      material_id: Optional[int] = None,
      student: User = Depends(get_current_student),
  ) -> Dict[str, Any]:
    return container.analytics_service.get_student_dashboard(
        student, period_id=period_id, month=month, material_id=material_id
    )

  @app.get("/api/student/grades")
  def student_grades(
      period_id: Optional[int] = None,
      student: User = Depends(get_current_student),
  ) -> Dict[str, Any]:
    return _serialize(
        container.grade_service.get_student_published_grades(student, period_id=period_id)
    )

  @app.post("/api/student/grades/{assessment_id}/reveal")
  def student_reveal_grade(
      assessment_id: int,
      student: User = Depends(get_current_student),
  ) -> Dict[str, Any]:
    return container.grade_service.reveal_student_grade(student, assessment_id)

  @app.get("/api/student/attendance")
  def student_attendance(
      month: Optional[str] = None,
      period_id: Optional[int] = None,
      date_from: Optional[str] = None,
      date_to: Optional[str] = None,
      student: User = Depends(get_current_student),
  ) -> Dict[str, Any]:
    return _serialize(
        container.attendance_service.get_student_attendance(
            student, month=month, period_id=period_id, date_from=date_from, date_to=date_to
        )
    )

  @app.delete("/api/student/corrections/{request_id}")
  def delete_student_correction(
      request_id: int, student: User = Depends(get_current_student)
  ) -> Dict[str, Any]:
    return container.attendance_service.delete_student_correction(student, request_id)

  @app.get("/api/student/corrections")
  def student_list_corrections(
      student: User = Depends(get_current_student),
  ) -> Dict[str, Any]:
    return {
        "corrections": container.attendance_service.list_student_corrections(student)
    }

  @app.post("/api/student/corrections", status_code=201)
  def student_submit_correction(
      payload: CorrectionCreatePayload,
      student: User = Depends(get_current_student),
  ) -> Dict[str, Any]:
    req = container.attendance_service.submit_correction_request(
        student, payload.target_type, payload.target_id, payload.message
    )
    return {"correction": req}

  return app
