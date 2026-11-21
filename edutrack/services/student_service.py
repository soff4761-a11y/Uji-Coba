"""Layanan pengelolaan peserta didik, akun tertaut, pindah kelas, dan impor CSV/Excel."""

from __future__ import annotations

import csv
import io
import re
from typing import Any, Dict, List, Optional

import openpyxl

from edutrack.configs.app_config import AppConfig
from edutrack.domain.errors import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from edutrack.domain.models import AccountStatus, Role, StudentProfile, User
from edutrack.domain.security import (
    generate_secure_token,
    hash_password,
    validate_password_strength,
)
from edutrack.repositories.academic_repo import AcademicRepository
from edutrack.repositories.user_repo import UserRepository
from edutrack.services.auth_service import AuthService


DEFAULT_STUDENT_PASSWORD = "12345678"


def _slugify_username(full_name: str, student_code: str) -> str:
  """Menghasilkan username default peserta didik menggunakan NIS alfanumerik bersih."""
  del full_name
  nis = re.sub(r"[^a-zA-Z0-9]+", "", (student_code or "").strip())
  if len(nis) >= 3:
    return nis[:32]
  return f"nis{nis or '000'}"


class StudentService:
  """Mengelola profil peserta didik, akun login tertaut, dan impor massal."""

  def __init__(
      self,
      academic_repo: AcademicRepository,
      user_repo: UserRepository,
      config: AppConfig,
  ) -> None:
    self._academic_repo = academic_repo
    self._user_repo = user_repo
    self._config = config

  def _verify_class_ownership(self, teacher: User, class_id: int) -> None:
    AuthService.require_role(teacher, Role.TEACHER)
    classroom = self._academic_repo.get_classroom(class_id)
    if not classroom:
      raise NotFoundError("Kelas tidak ditemukan.")
    if classroom.teacher_id != teacher.id:
      raise AuthorizationError("Anda tidak berwenang mengelola kelas guru lain.")

  def get_owned_student(self, teacher: User, student_id: int) -> StudentProfile:
    AuthService.require_role(teacher, Role.TEACHER)
    student = self._academic_repo.get_student(student_id)
    if not student:
      raise NotFoundError("Peserta didik tidak ditemukan.")
    if student.teacher_id != teacher.id:
      raise AuthorizationError(
          "Akses ditolak: peserta didik ini bukan dalam kewenangan Anda."
      )
    return student

  def create_student_with_account(
      self,
      teacher: User,
      class_id: int,
      full_name: str,
      student_code: str,
      username: Optional[str] = None,
      initial_password: Optional[str] = None,
      notes: str = "",
      account_status: AccountStatus = AccountStatus.PENDING_ACTIVATION,
  ) -> Dict[str, Any]:
    """Menambahkan peserta didik baru sekaligus membuat akun login yang terhubung.

    Returns:
      Dictionary berisi ``student`` (StudentProfile), ``username``, dan
      ``initial_password`` untuk diserahkan secara aman oleh guru.
    """
    self._verify_class_ownership(teacher, class_id)
    clean_name = full_name.strip()
    clean_code = student_code.strip()
    if not clean_name or not clean_code:
      raise ValidationError("Nama lengkap dan nomor induk/identitas wajib diisi.")

    clean_username = (
        username.strip() if username and username.strip() else _slugify_username(clean_name, clean_code)
    )
    if len(clean_username) < 3 or " " in clean_username:
      raise ValidationError("Username peserta didik minimal 3 karakter tanpa spasi.")

    raw_password = initial_password if initial_password else DEFAULT_STUDENT_PASSWORD
    validate_password_strength(raw_password)

    pw_hash = hash_password(raw_password, iterations=self._config.pbkdf2_iterations)
    user = self._user_repo.create_user(
        username=clean_username,
        password_hash=pw_hash,
        full_name=clean_name,
        role=Role.STUDENT,
        status=account_status,
        must_change_password=True,
    )
    try:
      student = self._academic_repo.create_student(
          user_id=user.id,
          teacher_id=teacher.id,
          class_id=class_id,
          student_code=clean_code,
          full_name=clean_name,
          notes=notes.strip(),
      )
    except Exception:
      # Rollback penuh akun user bila pembuatan profil peserta didik gagal (mis. duplikat NIS).
      self._user_repo.delete_user(user.id)
      raise

    self._user_repo.log_audit(
        teacher.id,
        "create_student",
        "student",
        student.id,
        f"Peserta didik '{clean_name}' ({clean_code}) ditambahkan ke kelas #{class_id}.",
    )
    return {
        "student": student,
        "username": clean_username,
        "initial_password": raw_password,
    }

  def list_students(
      self,
      teacher: User,
      class_id: Optional[int] = None,
      status: Optional[AccountStatus] = None,
      search: Optional[str] = None,
  ) -> List[StudentProfile]:
    AuthService.require_role(teacher, Role.TEACHER)
    if class_id is not None:
      self._verify_class_ownership(teacher, class_id)
    return self._academic_repo.list_students(
        teacher_id=teacher.id, class_id=class_id, status=status, search=search
    )

  def update_student(
      self,
      teacher: User,
      student_id: int,
      full_name: Optional[str] = None,
      student_code: Optional[str] = None,
      notes: Optional[str] = None,
      account_status: Optional[AccountStatus] = None,
      username: Optional[str] = None,
  ) -> StudentProfile:
    student = self.get_owned_student(teacher, student_id)
    if full_name is not None and not full_name.strip():
      raise ValidationError("Nama peserta didik tidak boleh kosong.")
    if student_code is not None and not student_code.strip():
      raise ValidationError("Nomor induk tidak boleh kosong.")
    clean_username = username.strip() if username is not None else None
    if clean_username is not None and (len(clean_username) < 3 or " " in clean_username):
      raise ValidationError("Username peserta didik minimal 3 karakter tanpa spasi.")

    if account_status is not None or clean_username is not None:
      self._user_repo.update_account_profile(
          student.user_id, status=account_status, username=clean_username
      )
      if account_status == AccountStatus.DEACTIVATED:
        self._user_repo.revoke_all_user_sessions(student.user_id)

    updated = self._academic_repo.update_student_profile(
        student_id=student_id,
        full_name=full_name.strip() if full_name is not None else None,
        student_code=student_code.strip() if student_code is not None else None,
        notes=notes.strip() if notes is not None else None,
    )
    if updated is None:
      raise NotFoundError("Peserta didik tidak ditemukan.")
    self._user_repo.log_audit(
        teacher.id,
        "update_student",
        "student",
        student_id,
        f"name={updated.full_name}, status={updated.account_status.value}",
    )
    return updated

  def move_student(
      self, teacher: User, student_id: int, target_class_id: int
  ) -> StudentProfile:
    """Memindahkan peserta didik ke kelas lain sambil mempertahankan riwayat lama."""
    student = self.get_owned_student(teacher, student_id)
    self._verify_class_ownership(teacher, target_class_id)
    if student.current_class_id == target_class_id:
      raise ValidationError("Peserta didik sudah berada di kelas tujuan tersebut.")
    moved = self._academic_repo.move_student_class(student_id, target_class_id)
    if moved is None:
      raise NotFoundError("Peserta didik tidak ditemukan.")
    self._user_repo.log_audit(
        teacher.id,
        "move_student",
        "student",
        student_id,
        f"Dipindahkan dari kelas #{student.current_class_id} ke #{target_class_id}.",
    )
    return moved

  def reset_student_password(
      self, teacher: User, student_id: int, new_temporary_password: Optional[str] = None
  ) -> Dict[str, str]:
    """Mereset kata sandi peserta didik oleh guru dengan kewajiban ubah saat login."""
    student = self.get_owned_student(teacher, student_id)
    raw_pw = (
        new_temporary_password
        if new_temporary_password
        else DEFAULT_STUDENT_PASSWORD
    )
    validate_password_strength(raw_pw)
    pw_hash = hash_password(raw_pw, iterations=self._config.pbkdf2_iterations)
    self._user_repo.update_password(
        student.user_id, pw_hash, must_change_password=True
    )
    self._user_repo.revoke_all_user_sessions(student.user_id)
    self._user_repo.log_audit(
        teacher.id,
        "reset_student_password",
        "student",
        student_id,
        "Guru mereset kata sandi peserta didik.",
    )
    return {"username": student.username, "temporary_password": raw_pw}

  def delete_student(
      self, teacher: User, student_id: int, confirm_permanent: bool = False
  ) -> None:
    student = self.get_owned_student(teacher, student_id)
    if student.account_status != AccountStatus.DEACTIVATED:
      raise ValidationError(
          "Nonaktifkan akun peserta didik terlebih dahulu sebelum menghapus permanen."
      )
    if not confirm_permanent:
      raise ValidationError(
          "Konfirmasi penghapusan permanen (confirm_permanent=true) wajib diberikan."
      )
    self._academic_repo.delete_student(student_id)
    self._user_repo.log_audit(
        teacher.id,
        "delete_student",
        "student",
        student_id,
        f"Peserta didik '{student.full_name}' dihapus permanen.",
    )

  def import_students(
      self,
      teacher: User,
      class_id: int,
      filename: str,
      content: bytes,
  ) -> Dict[str, Any]:
    """Mengimpor daftar peserta didik dari berkas CSV atau Excel (.xlsx).

    Kolom yang dikenali (case-insensitive):
      - nama / full_name / nama_lengkap (wajib)
      - nis / student_code / nomor_induk (wajib)
      - username (opsional)
      - password (opsional)
      - catatan / notes (opsional)
    """
    self._verify_class_ownership(teacher, class_id)
    if not content:
      raise ValidationError("Berkas impor kosong.")

    lower_name = filename.lower()
    rows: List[Dict[str, str]] = []
    if lower_name.endswith(".csv"):
      text = content.decode("utf-8-sig")
      reader = csv.DictReader(io.StringIO(text))
      if not reader.fieldnames:
        raise ValidationError("Header CSV tidak ditemukan.")
      for raw in reader:
        rows.append({
            (k or "").strip().lower(): (v or "").strip() for k, v in raw.items()
        })
    elif lower_name.endswith(".xlsx"):
      try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
      except Exception as exc:  # pylint: disable=broad-except
        raise ValidationError("Berkas Excel (.xlsx) tidak dapat dibaca atau rusak.") from exc
      try:
        ws = wb.active
        if ws is None:
          raise ValidationError("Berkas Excel tidak memiliki lembar kerja aktif.")
        all_rows = list(ws.iter_rows(values_only=True))
      except ValidationError:
        raise
      except Exception as exc:  # pylint: disable=broad-except
        raise ValidationError("Isi berkas Excel (.xlsx) rusak atau tidak dapat diproses.") from exc
      finally:
        wb.close()
      if len(all_rows) < 2:
        raise ValidationError("Berkas Excel tidak memiliki baris data.")
      headers = [str(h or "").strip().lower() for h in all_rows[0]]
      for raw_row in all_rows[1:]:
        if all(cell is None or str(cell).strip() == "" for cell in raw_row):
          continue
        row_dict: Dict[str, str] = {}
        for idx, header in enumerate(headers):
          val = raw_row[idx] if idx < len(raw_row) else ""
          row_dict[header] = "" if val is None else str(val).strip()
        rows.append(row_dict)
    else:
      raise ValidationError("Format berkas harus .csv atau .xlsx.")

    created: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for idx, row in enumerate(rows, start=2):
      full_name = (
          row.get("full_name")
          or row.get("nama_lengkap")
          or row.get("nama")
          or ""
      )
      student_code = (
          row.get("student_code")
          or row.get("nomor_induk")
          or row.get("nis")
          or row.get("nisn")
          or ""
      )
      username = row.get("username") or None
      password = row.get("password") or None
      notes = row.get("notes") or row.get("catatan") or ""

      try:
        res = self.create_student_with_account(
            teacher=teacher,
            class_id=class_id,
            full_name=full_name,
            student_code=student_code,
            username=username,
            initial_password=password,
            notes=notes,
        )
        created.append({
            "row": idx,
            "student_id": res["student"].id,
            "full_name": res["student"].full_name,
            "student_code": res["student"].student_code,
            "username": res["username"],
            "initial_password": res["initial_password"],
        })
      except (ValidationError, ConflictError) as exc:
        errors.append({"row": idx, "error": exc.message})

    return {
        "imported_count": len(created),
        "failed_count": len(errors),
        "created": created,
        "errors": errors,
    }

  @staticmethod
  def _normalize_excel_cell(val: Any) -> str:
    if val is None:
      return ""
    if isinstance(val, float) and val.is_integer():
      return str(int(val))
    return str(val).strip()

  def generate_student_import_template(self) -> bytes:
    """Menghasilkan template Excel (.xlsx) untuk impor massal peserta didik beserta akun."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data Peserta Didik"
    ws.append(["No.", "NIS / Identitas", "Nama Peserta Didik", "Username", "Password", "Catatan (Opsional)"])
    ws.append([1, "NIS-001", "Nama Peserta Didik 1", "siswa001", "PasswordAwal001", "Contoh baris 1 (ubah sebelum unggah)"])
    ws.append([2, "NIS-002", "Nama Peserta Didik 2", "siswa002", "PasswordAwal002", "Contoh baris 2 (ubah sebelum unggah)"])
    for col_letter, width in [("A", 8), ("B", 20), ("C", 28), ("D", 20), ("E", 22), ("F", 34)]:
      ws.column_dimensions[col_letter].width = width

    guide = wb.create_sheet(title="Petunjuk Pengisian")
    guide.append(["Petunjuk Pengisian Template Impor Data Peserta Didik"])
    guide.append(["1. Isi data mulai dari baris ke-2 pada sheet 'Data Peserta Didik'. Hapus atau timpa 2 baris contoh."])
    guide.append(["2. Kolom Wajib: Nama Peserta Didik, Username (min. 3 karakter, tanpa spasi, unik), dan Password (min. 8 karakter)."])
    guide.append(["3. Kolom NIS / Identitas dianjurkan diisi sebagai penanda unik agar mencegah duplikasi data peserta didik."])
    guide.append(["4. Password yang diunggah akan di-hash secara aman dan peserta didik wajib menggantinya saat login pertama."])
    guide.column_dimensions["A"].width = 96

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

  def _parse_student_import_rows(self, filename: str, content: bytes) -> List[tuple[int, Dict[str, str]]]:
    if not content:
      raise ValidationError("Berkas impor kosong.")
    lower_name = filename.lower()
    parsed: List[tuple[int, Dict[str, str]]] = []
    if lower_name.endswith(".csv"):
      text = content.decode("utf-8-sig")
      reader = csv.DictReader(io.StringIO(text))
      if not reader.fieldnames:
        raise ValidationError("Header CSV tidak ditemukan.")
      for idx, raw in enumerate(reader, start=2):
        row_dict = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        if any(row_dict.values()):
          parsed.append((idx, row_dict))
    elif lower_name.endswith(".xlsx"):
      try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
      except Exception as exc:  # pylint: disable=broad-except
        raise ValidationError("Berkas Excel (.xlsx) tidak dapat dibaca atau rusak.") from exc
      try:
        ws = wb.active
        if ws is None:
          raise ValidationError("Berkas Excel tidak memiliki lembar kerja aktif.")
        all_rows = list(ws.iter_rows(values_only=True))
      except ValidationError:
        raise
      except Exception as exc:  # pylint: disable=broad-except
        raise ValidationError("Isi berkas Excel (.xlsx) rusak atau tidak dapat diproses.") from exc
      finally:
        wb.close()
      if len(all_rows) < 2:
        raise ValidationError("Berkas Excel tidak memiliki baris data.")
      headers = [self._normalize_excel_cell(h).lower() for h in all_rows[0]]
      for row_num, raw_row in enumerate(all_rows[1:], start=2):
        if all(cell is None or str(cell).strip() == "" for cell in raw_row):
          continue
        row_dict = {}
        for idx, header in enumerate(headers):
          val = raw_row[idx] if idx < len(raw_row) else ""
          row_dict[header] = self._normalize_excel_cell(val)
        parsed.append((row_num, row_dict))
    else:
      raise ValidationError("Format berkas harus .xlsx atau .csv.")
    return parsed

  def _validate_student_import_file(
      self, teacher: User, class_id: int, filename: str, content: bytes
  ) -> Dict[str, Any]:
    self._verify_class_ownership(teacher, class_id)
    parsed_rows = self._parse_student_import_rows(filename, content)

    existing_students = self._academic_repo.list_students(teacher.id, class_id=class_id)
    existing_codes = {s.student_code.strip().lower() for s in existing_students}
    seen_usernames: set[str] = set()
    seen_codes: set[str] = set()

    valid_rows: List[Dict[str, Any]] = []
    invalid_rows: List[Dict[str, Any]] = []

    for row_num, row in parsed_rows:
      full_name = (
          row.get("nama peserta didik")
          or row.get("nama")
          or row.get("nama_lengkap")
          or row.get("full_name")
          or ""
      ).strip()
      student_code = (
          row.get("nis / identitas")
          or row.get("nis/identitas")
          or row.get("nis")
          or row.get("nisn")
          or row.get("identitas")
          or row.get("student_code")
          or row.get("nomor_induk")
          or ""
      ).strip()
      username = (row.get("username") or "").strip().lower()
      password = (row.get("password") or "").strip()
      notes = (row.get("catatan (opsional)") or row.get("catatan") or row.get("notes") or "").strip()

      row_errors: List[tuple[str, str]] = []
      if not full_name:
        row_errors.append(("Nama Peserta Didik", "Nama peserta didik wajib diisi."))
      if not username:
        row_errors.append(("Username", "Username wajib diisi."))
      elif len(username) < 3 or " " in username:
        row_errors.append(("Username", "Username minimal 3 karakter dan tanpa spasi."))
      elif username in seen_usernames:
        row_errors.append(("Username", f"Username '{username}' ganda di dalam berkas unggahan."))
      elif self._user_repo.get_auth_record_by_username(username) is not None:
        row_errors.append(("Username", f"Username '{username}' sudah digunakan akun lain."))

      if not password:
        row_errors.append(("Password", "Password awal wajib diisi."))
      else:
        try:
          validate_password_strength(password)
        except ValidationError as exc:
          row_errors.append(("Password", exc.message))

      effective_code = student_code or f"STD-{username.upper()}"
      code_key = effective_code.lower()
      if code_key in seen_codes:
        row_errors.append(("NIS / Identitas", f"Identitas '{effective_code}' ganda di dalam berkas."))
      elif code_key in existing_codes:
        row_errors.append(("NIS / Identitas", f"Peserta didik dengan identitas '{effective_code}' sudah terdaftar di kelas ini."))

      if row_errors:
        for col, reason in row_errors:
          invalid_rows.append({
              "row_number": row_num,
              "column": col,
              "reason": reason,
              "full_name": full_name,
              "student_code": effective_code,
              "username": username,
          })
      else:
        seen_usernames.add(username)
        seen_codes.add(code_key)
        valid_rows.append({
            "row_number": row_num,
            "full_name": full_name,
            "student_code": effective_code,
            "username": username,
            "password": password,
            "notes": notes,
        })

    return {
        "total_rows": len(parsed_rows),
        "valid_count": len(valid_rows),
        "invalid_count": len(invalid_rows),
        "valid_rows": valid_rows,
        "invalid_rows": invalid_rows,
    }

  def preview_student_import(
      self, teacher: User, class_id: int, filename: str, content: bytes
  ) -> Dict[str, Any]:
    """Memvalidasi berkas impor peserta didik dan mengembalikan pratinjau aman tanpa password plaintext."""
    res = self._validate_student_import_file(teacher, class_id, filename, content)
    safe_valid = [
        {
            "row_number": r["row_number"],
            "full_name": r["full_name"],
            "student_code": r["student_code"],
            "username": r["username"],
            "password_status": "Valid (akan di-hash aman)",
            "notes": r["notes"],
        }
        for r in res["valid_rows"]
    ]
    return {
        "total_rows": res["total_rows"],
        "valid_count": res["valid_count"],
        "invalid_count": res["invalid_count"],
        "valid_rows": safe_valid,
        "invalid_rows": res["invalid_rows"],
    }

  def confirm_student_import(
      self, teacher: User, class_id: int, filename: str, content: bytes
  ) -> Dict[str, Any]:
    """Menyimpan seluruh baris valid dari berkas impor dengan password ter-hash PBKDF2."""
    res = self._validate_student_import_file(teacher, class_id, filename, content)
    created: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = list(res["invalid_rows"])

    for r in res["valid_rows"]:
      try:
        out = self.create_student_with_account(
            teacher=teacher,
            class_id=class_id,
            full_name=r["full_name"],
            student_code=r["student_code"],
            username=r["username"],
            initial_password=r["password"],
            notes=r["notes"],
            account_status=AccountStatus.PENDING_ACTIVATION,
        )
        created.append({
            "row_number": r["row_number"],
            "student_id": out["student"].id,
            "full_name": out["student"].full_name,
            "student_code": out["student"].student_code,
            "username": out["student"].username,
        })
      except Exception as exc:  # pylint: disable=broad-except
        errors.append({
            "row_number": r["row_number"],
            "column": "Sistem",
            "reason": getattr(exc, "message", str(exc)),
            "full_name": r["full_name"],
            "student_code": r["student_code"],
            "username": r["username"],
        })

    return {
        "imported_count": len(created),
        "failed_count": len(errors),
        "created": created,
        "errors": errors,
    }

  def preview_bulk_delete_students(
      self,
      teacher: User,
      class_id: int,
      student_ids: Optional[List[int]] = None,
  ) -> Dict[str, Any]:
    """Memeriksa jumlah peserta didik & riwayat akademiknya sebelum penghapusan massal."""
    self._verify_class_ownership(teacher, class_id)
    classroom = self._academic_repo.get_classroom(class_id)
    if not classroom:
      raise NotFoundError('Kelas tidak ditemukan.')
    preview = self._academic_repo.get_bulk_student_delete_preview(
        teacher.id, class_id, student_ids=student_ids
    )
    return {"class_id": classroom.id, "class_name": classroom.name, **preview}

  def bulk_delete_students(
      self,
      teacher: User,
      class_id: int,
      delete_all: bool = False,
      student_ids: Optional[List[int]] = None,
      mode: str = "archive",
      confirm: bool = False,
  ) -> Dict[str, Any]:
    """Menghapus atau menonaktifkan peserta didik secara massal (dibatasi pada kelas milik guru)."""
    self._verify_class_ownership(teacher, class_id)
    classroom = self._academic_repo.get_classroom(class_id)
    if not classroom:
      raise NotFoundError('Kelas tidak ditemukan.')
    clean_mode = mode.strip().lower()
    if clean_mode not in ("archive", "permanent"):
      raise ValidationError("Mode penghapusan harus 'archive' atau 'permanent'.")
    if not confirm:
      raise ValidationError("Konfirmasi eksplisit (confirm=true) wajib diberikan.")
    if not delete_all and not student_ids:
      raise ValidationError("Pilih minimal satu peserta didik atau aktifkan delete_all=true.")

    try:
      result = self._academic_repo.bulk_archive_or_delete_students(
          teacher_id=teacher.id,
          class_id=class_id,
          student_ids=student_ids,
          delete_all=delete_all,
          mode=clean_mode,
      )
    except ValueError as exc:
      if str(exc) == "OUT_OF_SCOPE":
        raise AuthorizationError(
            "Sebagian peserta didik yang dipilih bukan berada di kelas ini atau di luar kewenangan Anda."
        ) from exc
      raise
    except RuntimeError as exc:
      if str(exc).startswith("MULTI_CLASS:"):
        names = str(exc).split("MULTI_CLASS:", 1)[1]
        raise ConflictError(
            f"Penghapusan permanen dibatalkan karena peserta didik ({names}) masih terhubung dengan riwayat kelas lain. "
            "Gunakan mode Arsipkan/Nonaktifkan agar riwayat akademik tetap aman."
        ) from exc
      raise

    self._user_repo.log_audit(
        teacher.id,
        "bulk_delete_students",
        "class",
        class_id,
        f"Kelas '{classroom.name}': {result['affected_count']} peserta didik diproses (mode={clean_mode}, delete_all={delete_all}).",
    )
    action_label = "dihapus permanen" if clean_mode == "permanent" else "diarsipkan / dinonaktifkan"
    return {
        **result,
        "class_name": classroom.name,
        "message": f"{result['affected_count']} peserta didik pada kelas '{classroom.name}' berhasil {action_label}.",
    }

  def reset_student_credentials(
      self, teacher: User, student_id: int
  ) -> Dict[str, Any]:
    """Mereset username peserta didik ke NIS dan kata sandi ke '12345678' serta mencabut sesi lama."""
    stu = self.get_owned_student(teacher, student_id)
    clean_nis = re.sub(r"[^a-zA-Z0-9]+", "", (stu.student_code or "").strip())
    if len(clean_nis) < 3:
      raise ValidationError(
          f"NIS '{stu.student_code}' terlalu pendek (minimal 3 karakter alfanumerik) untuk dijadikan username."
      )
    nis_username = clean_nis[:32]
    self._user_repo.update_account_profile(stu.user_id, username=nis_username)
    pw_hash = hash_password(DEFAULT_STUDENT_PASSWORD, iterations=self._config.pbkdf2_iterations)
    self._user_repo.update_password(
        stu.user_id, pw_hash, must_change_password=True, activate_if_pending=False
    )
    self._user_repo.revoke_all_user_sessions(stu.user_id)
    self._user_repo.log_audit(
        teacher.id,
        "reset_student_credentials",
        "student",
        student_id,
        f"Username peserta didik '{stu.full_name}' direset ke NIS ({nis_username}) dan sandi ke default.",
    )
    return {
        "student_id": stu.id,
        "full_name": stu.full_name,
        "student_code": stu.student_code,
        "username": nis_username,
        "temporary_password": DEFAULT_STUDENT_PASSWORD,
        "message": f"Akun '{stu.full_name}' direset: Username = {nis_username}, Sandi = {DEFAULT_STUDENT_PASSWORD}.",
    }

  def update_student_username(self, student_user: User, new_username: str) -> User:
    """Memungkinkan peserta didik mengubah username miliknya sendiri."""
    AuthService.require_role(student_user, Role.STUDENT)
    clean_u = (new_username or "").strip()
    if len(clean_u) < 3 or " " in clean_u:
      raise ValidationError("Username minimal 3 karakter dan tidak boleh mengandung spasi.")
    updated = self._user_repo.update_account_profile(student_user.id, username=clean_u)
    if not updated:
      raise NotFoundError("Akun peserta didik tidak ditemukan.")
    self._user_repo.log_audit(
        student_user.id,
        "student_change_username",
        "user",
        student_user.id,
        f"Siswa mengubah username menjadi '{clean_u}'.",
    )
    return updated
