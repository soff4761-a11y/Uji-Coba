"""Layanan pembuatan laporan akademik dan ekspor dalam format Excel (.xlsx), CSV, dan PDF bergrafik."""

from __future__ import annotations

import csv
import io
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape as xml_escape

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from edutrack.domain.errors import AuthorizationError, NotFoundError, ValidationError
from edutrack.domain.models import AssessmentStatus, Role, User
from edutrack.repositories.academic_repo import AcademicRepository
from edutrack.services.analytics_service import AnalyticsService
from edutrack.services.grade_service import GradeService

_PDF_NAVY = colors.HexColor("#0F172A")
_PDF_INDIGO = colors.HexColor("#1E3A8A")
_PDF_SKY = colors.HexColor("#0284C7")
_PDF_SLATE_BG = colors.HexColor("#F8FAFC")
_PDF_BORDER = colors.HexColor("#E2E8F0")
_PDF_TEXT = colors.HexColor("#0F172A")
_PDF_MUTED = colors.HexColor("#64748B")

_CHART_PALETTE = [
    colors.HexColor("#2563EB"),
    colors.HexColor("#0EA5E9"),
    colors.HexColor("#10B981"),
    colors.HexColor("#F59E0B"),
    colors.HexColor("#8B5CF6"),
    colors.HexColor("#EC4899"),
    colors.HexColor("#14B8A6"),
    colors.HexColor("#F97316"),
]


def _render_csv(headers: List[str], rows: List[List[Any]]) -> bytes:
  buf = io.StringIO()
  writer = csv.writer(buf)
  writer.writerow(headers)
  for r in rows:
    writer.writerow(["" if v is None else v for v in r])
  return buf.getvalue().encode("utf-8-sig")


def _render_xlsx(
    title: str, subtitle: str, headers: List[str], rows: List[List[Any]]
) -> bytes:
  wb = openpyxl.Workbook()
  ws = wb.active
  ws.title = "Laporan"

  ws.append([title])
  ws.append([subtitle])
  ws.append([])
  ws.append(headers)

  ws["A1"].font = Font(bold=True, size=14, color="1E293B")
  ws["A2"].font = Font(italic=True, size=10, color="475569")

  header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
  header_font = Font(bold=True, color="FFFFFF", size=10)

  for col_idx in range(1, len(headers) + 1):
    cell = ws.cell(row=4, column=col_idx)
    cell.fill = header_fill
    cell.font = header_font
    cell.alignment = Alignment(horizontal="center", vertical="center")

  for row in rows:
    ws.append(["-" if v is None else v for v in row])

  for col in ws.columns:
    max_len = 12
    col_letter = col[0].column_letter
    for cell in col:
      val = str(cell.value or "")
      if len(val) > max_len:
        max_len = min(len(val) + 2, 42)
    ws.column_dimensions[col_letter].width = max_len

  out = io.BytesIO()
  wb.save(out)
  return out.getvalue()


def _fmt_kkm_num(val: float) -> str:
  return str(int(val)) if float(val).is_integer() else f"{val:g}"


def _build_kkm_distribution(scores: Sequence[float], kkm: float) -> Dict[str, int]:
  """Menyusun distribusi skor dinamis berdasarkan ambang KKM kelas."""
  if not math.isfinite(kkm):
    kkm = 75.0

  if kkm <= 0.0:
    buckets = {"0-59": 0, "60-79": 0, "80-89": 0, "90-100": 0}
    for fs in scores:
      if fs < 60.0:
        buckets["0-59"] += 1
      elif fs < 80.0:
        buckets["60-79"] += 1
      elif fs < 90.0:
        buckets["80-89"] += 1
      else:
        buckets["90-100"] += 1
    return buckets

  if kkm >= 100.0:
    buckets = {"<60": 0, "60-79": 0, "80-99": 0, "100": 0}
    for fs in scores:
      if fs < 60.0:
        buckets["<60"] += 1
      elif fs < 80.0:
        buckets["60-79"] += 1
      elif fs < 100.0:
        buckets["80-99"] += 1
      else:
        buckets["100"] += 1
    return buckets

  low_cut = round(kkm * 0.8, 1)
  high_cut = round(kkm + (100.0 - kkm) * 0.6, 1)
  if low_cut <= 0.0 or low_cut >= kkm or high_cut <= kkm or high_cut >= 100.0:
    b_low = f"<{_fmt_kkm_num(kkm)}"
    b_high = f"{_fmt_kkm_num(kkm)}-100"
    buckets = {b_low: 0, b_high: 0}
    for fs in scores:
      if fs < kkm:
        buckets[b_low] += 1
      else:
        buckets[b_high] += 1
    return buckets

  if (
      float(low_cut).is_integer()
      and float(kkm).is_integer()
      and float(high_cut).is_integer()
      and int(low_cut) < int(kkm)
      and int(kkm) < int(high_cut)
  ):
    b1 = f"<{int(low_cut)}"
    b2 = f"{int(low_cut)}-{int(kkm) - 1}"
    b3 = f"{int(kkm)}-{int(high_cut) - 1}"
    b4 = f"{int(high_cut)}-100"
  else:
    b1 = f"<{_fmt_kkm_num(low_cut)}"
    b2 = f"{_fmt_kkm_num(low_cut)}..<{_fmt_kkm_num(kkm)}"
    b3 = f"{_fmt_kkm_num(kkm)}..<{_fmt_kkm_num(high_cut)}"
    b4 = f"{_fmt_kkm_num(high_cut)}-100"

  buckets = {b1: 0, b2: 0, b3: 0, b4: 0}
  for fs in scores:
    if fs < low_cut:
      buckets[b1] += 1
    elif fs < kkm:
      buckets[b2] += 1
    elif fs < high_cut:
      buckets[b3] += 1
    else:
      buckets[b4] += 1
  return buckets


def _truncate(text: str, max_len: int) -> str:
  clean = str(text or "").strip()
  return clean if len(clean) <= max_len else clean[: max_len - 1] + "…"


def _make_doughnut_card(
    title: str,
    center_value: str,
    center_label: str,
    segments: Sequence[Tuple[str, float, str, colors.Color]],
    width: float = 170.0,
    height: float = 205.0,
) -> Drawing:
  """Membangun kartu diagram donat vektor ReportLab lengkap dengan legenda."""
  d = Drawing(width, height)
  # Bingkai kartu
  d.add(
      Rect(
          0,
          0,
          width,
          height,
          rx=8,
          ry=8,
          fillColor=colors.white,
          strokeColor=_PDF_BORDER,
          strokeWidth=0.9,
      )
  )
  # Judul kartu
  d.add(
      String(
          width / 2,
          height - 16,
          _truncate(title, 26),
          fontName="Helvetica-Bold",
          fontSize=8.5,
          fillColor=_PDF_TEXT,
          textAnchor="middle",
      )
  )

  valid = [(lbl, float(val), disp, col) for (lbl, val, disp, col) in segments if float(val) > 0]
  cx = width / 2
  cy = height - 76
  pie_size = 92

  if valid:
    pie = Pie()
    pie.x = cx - pie_size / 2
    pie.y = cy - pie_size / 2
    pie.width = pie_size
    pie.height = pie_size
    pie.data = [v for (_, v, _, _) in valid]
    pie.labels = [""] * len(valid)
    pie.startAngle = 90
    pie.direction = "clockwise"
    pie.slices.strokeWidth = 0.8
    pie.slices.strokeColor = colors.white
    for idx, (_, _, _, col) in enumerate(valid):
      pie.slices[idx].fillColor = col
    d.add(pie)
    # Lubang donat di tengah
    d.add(Circle(cx, cy, pie_size * 0.30, fillColor=colors.white, strokeColor=colors.white, strokeWidth=0))
    d.add(
        String(
            cx,
            cy + 2,
            _truncate(center_value, 10),
            fontName="Helvetica-Bold",
            fontSize=12,
            fillColor=_PDF_TEXT,
            textAnchor="middle",
        )
    )
    d.add(
        String(
            cx,
            cy - 10,
            _truncate(center_label, 16),
            fontName="Helvetica",
            fontSize=6.5,
            fillColor=_PDF_MUTED,
            textAnchor="middle",
        )
    )

    # Legenda ringkas di bawah (maks 5 baris)
    total = sum(v for (_, v, _, _) in valid) or 1.0
    shown = valid[:5]
    y_cursor = 64
    for lbl, val, disp, col in shown:
      pct = round((val / total) * 100.0, 1)
      d.add(Circle(12, y_cursor + 3, 3.2, fillColor=col, strokeWidth=0))
      d.add(
          String(
              20,
              y_cursor,
              _truncate(lbl, 16),
              fontName="Helvetica",
              fontSize=6.8,
              fillColor=_PDF_TEXT,
          )
      )
      d.add(
          String(
              width - 10,
              y_cursor,
              f"{disp} ({pct}%)",
              fontName="Helvetica-Bold",
              fontSize=6.8,
              fillColor=_PDF_MUTED,
              textAnchor="end",
          )
      )
      y_cursor -= 11.5
    if len(valid) > 5:
      d.add(
          String(
              width / 2,
              6,
              f"+{len(valid) - 5} kategori lainnya",
              fontName="Helvetica-Oblique",
              fontSize=6.2,
              fillColor=_PDF_MUTED,
              textAnchor="middle",
          )
      )
  else:
    d.add(
        Circle(
            cx,
            cy,
            pie_size * 0.42,
            fillColor=colors.white,
            strokeColor=_PDF_BORDER,
            strokeWidth=8,
        )
    )
    d.add(
        String(
            cx,
            cy - 3,
            "Belum ada data",
            fontName="Helvetica",
            fontSize=7.5,
            fillColor=_PDF_MUTED,
            textAnchor="middle",
        )
    )

  return d


def _make_bar_chart_card(
    title: str,
    labels: Sequence[str],
    values: Sequence[float],
    width: float = 528.0,
    height: float = 158.0,
    bar_color: colors.Color = _PDF_SKY,
    max_y: float = 100.0,
) -> Drawing:
  """Membangun kartu grafik batang vektor ReportLab."""
  d = Drawing(width, height)
  d.add(
      Rect(
          0,
          0,
          width,
          height,
          rx=8,
          ry=8,
          fillColor=colors.white,
          strokeColor=_PDF_BORDER,
          strokeWidth=0.9,
      )
  )
  d.add(
      String(
          14,
          height - 16,
          title,
          fontName="Helvetica-Bold",
          fontSize=9,
          fillColor=_PDF_TEXT,
      )
  )

  if not labels or not values:
    d.add(
        String(
            width / 2,
            height / 2 - 6,
            "Belum ada data grafik untuk ditampilkan.",
            fontName="Helvetica",
            fontSize=8.5,
            fillColor=_PDF_MUTED,
            textAnchor="middle",
        )
    )
    return d

  chart = VerticalBarChart()
  chart.x = 38
  chart.y = 30
  chart.width = width - 56
  chart.height = height - 58
  chart.data = [list(values)]
  chart.strokeColor = None
  chart.bars[0].fillColor = bar_color
  chart.bars[0].strokeColor = bar_color
  chart.barSpacing = 2
  chart.groupSpacing = 8

  top_val = max(max_y, max(values) * 1.1) if values else max_y
  chart.valueAxis.valueMin = 0
  chart.valueAxis.valueMax = top_val
  chart.valueAxis.valueStep = max(1, round(top_val / 4))
  chart.valueAxis.strokeColor = _PDF_BORDER
  chart.valueAxis.visibleGrid = True
  chart.valueAxis.gridStrokeColor = colors.HexColor("#F1F5F9")
  chart.valueAxis.labels.fontName = "Helvetica"
  chart.valueAxis.labels.fontSize = 7
  chart.valueAxis.labels.fillColor = _PDF_MUTED

  chart.categoryAxis.categoryNames = [_truncate(lbl, 11) for lbl in labels]
  chart.categoryAxis.strokeColor = _PDF_BORDER
  chart.categoryAxis.labels.fontName = "Helvetica"
  chart.categoryAxis.labels.fontSize = 7
  chart.categoryAxis.labels.fillColor = _PDF_TEXT
  chart.categoryAxis.labels.boxAnchor = "n"
  chart.categoryAxis.labels.dy = -3

  chart.barLabels.nudge = 5
  chart.barLabelFormat = "%.0f"
  chart.barLabels.fontName = "Helvetica-Bold"
  chart.barLabels.fontSize = 6.8
  chart.barLabels.fillColor = _PDF_TEXT

  d.add(chart)
  return d


def _draw_page_chrome(canvas: Any, doc: Any) -> None:
  """Menggambar garis aksen atas pada setiap halaman PDF (tanpa footer)."""
  canvas.saveState()
  page_w, page_h = doc.pagesize
  canvas.setFillColor(_PDF_INDIGO)
  canvas.rect(0, page_h - 6, page_w * 0.65, 6, fill=1, stroke=0)
  canvas.setFillColor(_PDF_SKY)
  canvas.rect(page_w * 0.65, page_h - 6, page_w * 0.35, 6, fill=1, stroke=0)
  canvas.restoreState()


def _build_pdf_banner(title: str, subtitle: str, badge_text: str, content_width: float) -> Table:
  title_style = ParagraphStyle(
      "EduBannerTitle",
      fontName="Helvetica-Bold",
      fontSize=14,
      leading=18,
      textColor=colors.white,
  )
  sub_style = ParagraphStyle(
      "EduBannerSub",
      fontName="Helvetica",
      fontSize=8.8,
      leading=12,
      textColor=colors.HexColor("#BAE6FD"),
  )
  badge_style = ParagraphStyle(
      "EduBannerBadge",
      fontName="Helvetica-Bold",
      fontSize=7.5,
      leading=10,
      alignment=2,
      textColor=colors.HexColor("#38BDF8"),
  )
  left_cell = [
      Paragraph(xml_escape(title), title_style),
      Spacer(1, 3),
      Paragraph(xml_escape(subtitle), sub_style),
  ]
  right_cell = Paragraph(xml_escape(badge_text), badge_style)
  banner = Table([[left_cell, right_cell]], colWidths=[content_width * 0.78, content_width * 0.22])
  banner.setStyle(
      TableStyle([
          ("BACKGROUND", (0, 0), (-1, -1), _PDF_NAVY),
          ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("LEFTPADDING", (0, 0), (-1, -1), 14),
          ("RIGHTPADDING", (0, 0), (-1, -1), 14),
          ("TOPPADDING", (0, 0), (-1, -1), 12),
          ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
          ("ROUNDEDCORNERS", [8, 8, 8, 8]),
      ])
  )
  return banner


def _build_kpi_strip(kpis: Sequence[Tuple[str, str, str]], content_width: float) -> Table:
  label_s = ParagraphStyle("KpiLbl", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=_PDF_MUTED)
  val_s = ParagraphStyle("KpiVal", fontName="Helvetica-Bold", fontSize=14, leading=17, textColor=_PDF_TEXT)
  sub_s = ParagraphStyle("KpiSub", fontName="Helvetica", fontSize=7.2, leading=9.5, textColor=_PDF_MUTED)
  accents = [_PDF_INDIGO, colors.HexColor("#10B981"), _PDF_SKY, colors.HexColor("#8B5CF6")]
  cells = []
  for lbl, val, sub in kpis:
    cells.append([
        Paragraph(xml_escape(lbl.upper()), label_s),
        Spacer(1, 2),
        Paragraph(xml_escape(val), val_s),
        Paragraph(xml_escape(sub), sub_s),
    ])
  col_w = content_width / max(len(kpis), 1)
  tbl = Table([cells], colWidths=[col_w] * len(kpis))
  style_cmds = [
      ("BACKGROUND", (0, 0), (-1, -1), _PDF_SLATE_BG),
      ("BOX", (0, 0), (-1, -1), 0.7, _PDF_BORDER),
      ("INNERGRID", (0, 0), (-1, -1), 0.7, _PDF_BORDER),
      ("LEFTPADDING", (0, 0), (-1, -1), 9),
      ("RIGHTPADDING", (0, 0), (-1, -1), 9),
      ("TOPPADDING", (0, 0), (-1, -1), 8),
      ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
      ("VALIGN", (0, 0), (-1, -1), "TOP"),
  ]
  for idx in range(len(kpis)):
    style_cmds.append(("LINEABOVE", (idx, 0), (idx, 0), 2.5, accents[idx % len(accents)]))
  tbl.setStyle(TableStyle(style_cmds))
  return tbl


def _build_styled_table(
    headers: List[str],
    rows: List[List[Any]],
    content_width: float,
    col_weights: Optional[List[float]] = None,
) -> Table:
  hdr_s = ParagraphStyle("TblHdr", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.white)
  cell_s = ParagraphStyle("TblCell", fontName="Helvetica", fontSize=7.8, leading=10, textColor=_PDF_TEXT)
  data = [[Paragraph(xml_escape(str(h)), hdr_s) for h in headers]]
  for r in rows:
    if not r:
      continue
    data.append([Paragraph(xml_escape("-" if v is None else str(v)), cell_s) for v in r])

  if col_weights and len(col_weights) == len(headers):
    total_w = sum(col_weights) or 1.0
    col_widths = [content_width * (w / total_w) for w in col_weights]
  else:
    col_widths = [content_width / max(len(headers), 1)] * len(headers)

  tbl = Table(data, colWidths=col_widths, repeatRows=1)
  tbl.setStyle(
      TableStyle([
          ("BACKGROUND", (0, 0), (-1, 0), _PDF_INDIGO),
          ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
          ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("GRID", (0, 0), (-1, -1), 0.45, _PDF_BORDER),
          ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _PDF_SLATE_BG]),
          ("LEFTPADDING", (0, 0), (-1, -1), 6),
          ("RIGHTPADDING", (0, 0), (-1, -1), 6),
          ("TOPPADDING", (0, 0), (-1, -1), 5),
          ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
      ])
  )
  return tbl


def _render_pdf(
    title: str,
    subtitle: str,
    headers: List[str],
    rows: List[List[Any]],
    badge_text: str = "BAHASA INDONESIA • LAPORAN",
    kpis: Optional[Sequence[Tuple[str, str, str]]] = None,
    chart_flowables: Optional[List[Any]] = None,
    section_title: str = "Rincian Data",
    col_weights: Optional[List[float]] = None,
    force_landscape: bool = False,
) -> bytes:
  buf = io.BytesIO()
  pagesize = landscape(A4) if (force_landscape or len(headers) > 7) else A4
  doc = SimpleDocTemplate(
      buf,
      pagesize=pagesize,
      leftMargin=30,
      rightMargin=30,
      topMargin=24,
      bottomMargin=24,
  )
  content_width = pagesize[0] - doc.leftMargin - doc.rightMargin
  styles = getSampleStyleSheet()
  sec_style = ParagraphStyle(
      "EduSecTitle",
      parent=styles["Heading3"],
      fontName="Helvetica-Bold",
      fontSize=10,
      leading=13,
      textColor=_PDF_NAVY,
      spaceBefore=4,
      spaceAfter=6,
  )

  elements: List[Any] = [
      _build_pdf_banner(title, subtitle, badge_text, content_width),
      Spacer(1, 10),
  ]

  if kpis:
    elements.append(_build_kpi_strip(kpis, content_width))
    elements.append(Spacer(1, 10))

  if chart_flowables:
    for item in chart_flowables:
      elements.append(item)
      elements.append(Spacer(1, 10))

  elements.append(Paragraph(xml_escape(section_title), sec_style))
  elements.append(_build_styled_table(headers, rows, content_width, col_weights=col_weights))

  doc.build(elements, onFirstPage=_draw_page_chrome, onLaterPages=_draw_page_chrome)
  return buf.getvalue()


class ReportService:
  """Menghasilkan laporan Excel, CSV, dan PDF bergrafik dengan penegakan RBAC ketat."""

  def __init__(
      self,
      grade_service: GradeService,
      analytics_service: AnalyticsService,
      academic_repo: AcademicRepository,
  ) -> None:
    self._grade_service = grade_service
    self._analytics_service = analytics_service
    self._academic_repo = academic_repo

  @staticmethod
  def _export(
      fmt: str,
      stem: str,
      title: str,
      subtitle: str,
      headers: List[str],
      rows: List[List[Any]],
      pdf_kwargs: Optional[Dict[str, Any]] = None,
  ) -> Tuple[bytes, str, str]:
    clean_fmt = fmt.lower().strip()
    if clean_fmt == "csv":
      return _render_csv(headers, rows), "text/csv; charset=utf-8", f"{stem}.csv"
    if clean_fmt in ("xlsx", "excel"):
      return (
          _render_xlsx(title, subtitle, headers, rows),
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          f"{stem}.xlsx",
      )
    if clean_fmt == "pdf":
      return (
          _render_pdf(title, subtitle, headers, rows, **(pdf_kwargs or {})),
          "application/pdf",
          f"{stem}.pdf",
      )
    raise ValidationError("Format laporan harus 'csv', 'xlsx', atau 'pdf'.")

  def export_class_grades(
      self, teacher: User, class_id: int, fmt: str
  ) -> Tuple[bytes, str, str]:
    """Ekspor laporan nilai seluruh kelas (hanya Guru pemilik kelas)."""
    gb = self._grade_service.get_class_gradebook(teacher, class_id)
    cls = gb["classroom"]
    assessments = [a for a in gb["assessments"] if a.is_graded]
    stats = gb["statistics"]

    headers = (
        ["NIS", "Nama Peserta Didik"]
        + [
            a.title if a.status == AssessmentStatus.PUBLISHED else f"{a.title} (Draft)"
            for a in assessments
        ]
        + [
            "Nilai Akhir",
            "Ketuntasan",
        ]
    )
    rows: List[List[Any]] = []
    mastered_cnt = 0
    unmastered_cnt = 0
    valid_final_scores: List[float] = []
    for row in gb["rows"]:
      vals = [row["student_code"], row["full_name"]]
      for a in assessments:
        sc = row["scores"][a.id]["score"]
        vals.append("Belum Dinilai" if sc is None else sc)
      fs = row["final_score"]
      vals.append("Belum Ada" if fs is None else fs)
      if row["is_mastered"] is None:
        vals.append("-")
      else:
        vals.append("Tuntas" if row["is_mastered"] else "Perlu Pendampingan")
        if row["is_mastered"]:
          mastered_cnt += 1
        else:
          unmastered_cnt += 1
      if fs is not None:
        valid_final_scores.append(float(fs))
      rows.append(vals)
    buckets = _build_kkm_distribution(valid_final_scores, cls.mastery_threshold)

    title = f"Laporan Nilai Kelas {cls.name}"
    subtitle = f"Tahun Pelajaran {cls.academic_year} | Tingkat {cls.education_level} | KKM {cls.mastery_threshold}"

    pdf_kwargs: Dict[str, Any] = {}
    if fmt.lower().strip() == "pdf":
      is_land = len(headers) > 7
      cw = (landscape(A4)[0] if is_land else A4[0]) - 60
      total_eval = mastered_cnt + unmastered_cnt
      mastery_pct = round((mastered_cnt / total_eval) * 100.0, 1) if total_eval else None
      kpis = [
          ("Rata-rata Kelas", str(stats.average if stats.average is not None else "-"), f"Dari {stats.graded_count} siswa dinilai"),
          ("Tertinggi / Terendah", f"{stats.highest if stats.highest is not None else '-'} / {stats.lowest if stats.lowest is not None else '-'}", "Rentang nilai akhir"),
          ("Ketuntasan", f"{mastery_pct}%" if mastery_pct is not None else "-", f"KKM: {cls.mastery_threshold}"),
          ("Total Peserta Didik", str(len(gb["rows"])), f"{len(assessments)} komponen penilaian"),
      ]
      bar_w = cw * 0.62 - 6
      don_w = cw * 0.38 - 6
      bar_chart = _make_bar_chart_card(
          "Distribusi Nilai Akhir Kelas",
          list(buckets.keys()),
          [float(v) for v in buckets.values()],
          width=bar_w,
          height=180,
          bar_color=_PDF_INDIGO,
          max_y=max(4.0, float(max(buckets.values()) + 1)),
      )
      mastery_donut = _make_doughnut_card(
          "Ketuntasan Belajar",
          f"{mastery_pct}%" if mastery_pct is not None else "-",
          "Tuntas",
          [
              ("Tuntas", float(mastered_cnt), f"{mastered_cnt} siswa", colors.HexColor("#10B981")),
              ("Perlu Pendampingan", float(unmastered_cnt), f"{unmastered_cnt} siswa", colors.HexColor("#F59E0B")),
          ],
          width=don_w,
          height=180,
      )
      chart_row = Table([[bar_chart, mastery_donut]], colWidths=[bar_w + 6, don_w + 6])
      chart_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
      pdf_kwargs = {
          "badge_text": "LAPORAN NILAI KELAS",
          "kpis": kpis,
          "chart_flowables": [chart_row],
          "section_title": "Matriks Buku Nilai Peserta Didik",
      }

    return self._export(
        fmt, f"nilai_kelas_{cls.id}", title, subtitle, headers, rows, pdf_kwargs=pdf_kwargs
    )

  def export_attendance_recap(
      self,
      teacher: User,
      class_id: int,
      fmt: str,
      date_from: Optional[str] = None,
      date_to: Optional[str] = None,
  ) -> Tuple[bytes, str, str]:
    """Ekspor rekapitulasi kehadiran kelas (hanya Guru pemilik kelas)."""
    recap = self._analytics_service.get_attendance_recap(
        teacher, class_id, granularity="monthly", date_from=date_from, date_to=date_to
    )
    headers = [
        "NIS",
        "Nama Peserta Didik",
        "Total Pertemuan",
        "Hadir",
        "Sakit",
        "Izin",
        "Alpa",
        "Kehadiran (%)",
    ]
    rows = [
        [
            s["student_code"],
            s["full_name"],
            s["total_recorded"],
            s["hadir"],
            s["sakit"],
            s["izin"],
            s["alpa"],
            "-" if s["attendance_percentage"] is None else f"{s['attendance_percentage']}%",
        ]
        for s in recap["students"]
    ]
    title = f"Rekapitulasi Kehadiran Kelas {recap['class_name']}"
    subtitle = f"Periode filter: {date_from or 'Awal'} s.d. {date_to or 'Sekarang'}"

    pdf_kwargs: Dict[str, Any] = {}
    if fmt.lower().strip() == "pdf":
      tot_h = sum(int(s["hadir"]) for s in recap["students"])
      tot_s = sum(int(s["sakit"]) for s in recap["students"])
      tot_i = sum(int(s["izin"]) for s in recap["students"])
      tot_a = sum(int(s["alpa"]) for s in recap["students"])
      tot_all = tot_h + tot_s + tot_i + tot_a
      avg_pct = round((tot_h / tot_all) * 100.0, 1) if tot_all else None
      cw = landscape(A4)[0] - 60
      kpis = [
          ("Total Peserta Didik", str(len(recap["students"])), "Tercatat pada rekap"),
          ("Kehadiran Rata-rata", f"{avg_pct}%" if avg_pct is not None else "-", f"{tot_h} dari {tot_all} catatan"),
          ("Sakit / Izin", f"{tot_s} / {tot_i}", "Ketidakhadiran berizin"),
          ("Tanpa Keterangan (Alpa)", str(tot_a), "Perlu tindak lanjut"),
      ]
      donut = _make_doughnut_card(
          "Komposisi Kehadiran Kelas",
          f"{avg_pct}%" if avg_pct is not None else "-",
          "Hadir",
          [
              ("Hadir", float(tot_h), f"{tot_h}x", colors.HexColor("#10B981")),
              ("Sakit", float(tot_s), f"{tot_s}x", colors.HexColor("#F59E0B")),
              ("Izin", float(tot_i), f"{tot_i}x", colors.HexColor("#0EA5E9")),
              ("Alpa", float(tot_a), f"{tot_a}x", colors.HexColor("#EF4444")),
          ],
          width=220,
          height=185,
      )
      bar = _make_bar_chart_card(
          "Distribusi Status Kehadiran",
          ["Hadir", "Sakit", "Izin", "Alpa"],
          [float(tot_h), float(tot_s), float(tot_i), float(tot_a)],
          width=cw - 232,
          height=185,
          bar_color=_PDF_SKY,
          max_y=max(4.0, float(max(tot_h, tot_s, tot_i, tot_a) + 1)),
      )
      chart_row = Table([[donut, bar]], colWidths=[230, cw - 230])
      chart_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
      pdf_kwargs = {
          "badge_text": "REKAP KEHADIRAN",
          "kpis": kpis,
          "chart_flowables": [chart_row],
          "section_title": "Rincian Kehadiran per Peserta Didik",
          "force_landscape": True,
      }

    return self._export(
        fmt, f"kehadiran_kelas_{class_id}", title, subtitle, headers, rows, pdf_kwargs=pdf_kwargs
    )

  def export_individual_progress(
      self,
      actor: User,
      student_id: Optional[int],
      fmt: str,
  ) -> Tuple[bytes, str, str]:
    """Ekspor laporan perkembangan nilai & kehadiran individual lengkap dengan diagram vektor."""
    if actor.role == Role.TEACHER:
      if student_id is None:
        raise ValidationError("student_id wajib disertakan untuk guru.")
      data = self._analytics_service.get_student_progress_for_teacher(actor, student_id)
    else:
      profile = self._academic_repo.get_student_by_user_id(actor.id)
      if not profile:
        raise NotFoundError("Profil peserta didik tidak ditemukan.")
      if student_id is not None and student_id != profile.id:
        raise AuthorizationError(
            "Akses ditolak: peserta didik tidak boleh mengunduh laporan teman sekelas."
        )
      data = self._analytics_service.get_student_dashboard(actor)
      if not data["classroom"]["allow_student_report_download"]:
        raise AuthorizationError(
            "Unduh laporan pribadi sedang dinonaktifkan oleh guru pada kelas ini."
        )

    stu = data["student"]
    cls = data["classroom"]
    att = data["attendance_summary"]
    gs = data["grade_summary"]
    timeline = data.get("grade_timeline", [])
    cat_comp = data.get("category_comparison", [])

    headers = [
        "Tanggal",
        "Materi",
        "Penilaian",
        "Kategori",
        "Nilai",
        "Skala 100",
        "Umpan Balik",
    ]
    rows = [
        [
            item["date"],
            item.get("material_title") or "Belum Dikelompokkan",
            item["title"],
            item["category"],
            "Belum Dinilai" if item["raw_score"] is None else f"{item['raw_score']} / {item['max_score']}",
            "-" if item["normalized_score"] is None else item["normalized_score"],
            item["feedback"] or "-",
        ]
        for item in timeline
    ]

    # Untuk CSV/XLSX sertakan baris ringkasan di bawah
    export_rows = list(rows)
    if fmt.lower().strip() in ("csv", "xlsx", "excel"):
      export_rows.append([])
      export_rows.append([
          "RINGKASAN",
          f"Nilai Akhir: {gs['final_score'] if gs['final_score'] is not None else '-'}",
          f"Tren: {gs['trend_indicator']}",
          f"Hadir: {att['hadir']}/{att['total_recorded']}",
          f"S:{att['sakit']} I:{att['izin']} A:{att['alpa']}",
          f"Kehadiran: {att['attendance_percentage']}%" if att["attendance_percentage"] is not None else "-",
          "",
      ])

    title = f"Laporan Perkembangan Belajar — {stu['full_name']}"
    subtitle = (
        f"NIS {stu['student_code']}  •  Kelas {cls['name']} ({cls['education_level']})  •  "
        f"Tahun Pelajaran {cls['academic_year']}  •  KKM {cls['mastery_threshold']}"
    )

    pdf_kwargs: Dict[str, Any] = {}
    if fmt.lower().strip() == "pdf":
      cw = A4[0] - 60  # 535.27 pt
      final_str = str(gs["final_score"]) if gs["final_score"] is not None else "-"
      att_str = f"{att['attendance_percentage']}%" if att["attendance_percentage"] is not None else "-"
      status_kkm = "-"
      if gs["final_score"] is not None:
        status_kkm = "Tuntas KKM" if float(gs["final_score"]) >= float(cls["mastery_threshold"]) else "Perlu Pendampingan"

      kpis = [
          ("Nilai Akhir", final_str, f"Status: {status_kkm}"),
          ("Kehadiran", att_str, f"{att['hadir']} dari {att['total_recorded']} pertemuan"),
          ("Penilaian Dinilai", f"{gs['graded_assessments']} / {gs['total_assessments']}", f"KKM Kelas: {cls['mastery_threshold']}"),
          ("Tren Belajar", str(gs["trend_indicator"]), f"S:{att['sakit']} • I:{att['izin']} • A:{att['alpa']}"),
      ]

      # 3 Diagram Donat sejajar (seragam dengan Dashboard Siswa)
      graded_items = [p for p in timeline if p["normalized_score"] is not None]
      card_w = (cw - 14) / 3.0
      trend_segs = [
          (
              p["title"],
              max(float(p["normalized_score"]), 0.01),
              f"{p['normalized_score']}",
              _CHART_PALETTE[idx % len(_CHART_PALETTE)],
          )
          for idx, p in enumerate(graded_items)
      ]
      donut_trend = _make_doughnut_card(
          "Perkembangan Nilai",
          final_str,
          "Nilai Akhir",
          trend_segs,
          width=card_w,
          height=205,
      )

      cat_avg = (
          round(sum(float(c["average"]) for c in cat_comp) / len(cat_comp), 1)
          if cat_comp
          else None
      )
      cat_segs = [
          (
              c["category"],
              max(float(c["average"]), 0.01),
              f"{c['average']}",
              _CHART_PALETTE[idx % len(_CHART_PALETTE)],
          )
          for idx, c in enumerate(cat_comp)
      ]
      donut_cat = _make_doughnut_card(
          "Capaian per Kategori",
          str(cat_avg) if cat_avg is not None else "-",
          "Rata-rata Kategori",
          cat_segs,
          width=card_w,
          height=205,
      )

      att_segs = [
          ("Hadir", float(att["hadir"]), f"{att['hadir']}x", colors.HexColor("#10B981")),
          ("Sakit", float(att["sakit"]), f"{att['sakit']}x", colors.HexColor("#F59E0B")),
          ("Izin", float(att["izin"]), f"{att['izin']}x", colors.HexColor("#0EA5E9")),
          ("Alpa", float(att["alpa"]), f"{att['alpa']}x", colors.HexColor("#EF4444")),
      ]
      donut_att = _make_doughnut_card(
          "Ringkasan Kehadiran",
          att_str,
          "Kehadiran",
          att_segs,
          width=card_w,
          height=205,
      )

      donut_row = Table(
          [[donut_trend, donut_cat, donut_att]],
          colWidths=[card_w + 4.6, card_w + 4.6, card_w + 4.6],
      )
      donut_row.setStyle(
          TableStyle([
              ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("LEFTPADDING", (0, 0), (-1, -1), 0),
              ("RIGHTPADDING", (0, 0), (-1, -1), 0),
              ("TOPPADDING", (0, 0), (-1, -1), 0),
              ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
          ])
      )

      chart_flowables: List[Any] = [donut_row]
      if graded_items:
        bar_chart = _make_bar_chart_card(
            "Grafik Nilai Skala 100 per Penilaian",
            [p["title"] for p in graded_items[:12]],
            [float(p["normalized_score"]) for p in graded_items[:12]],
            width=cw,
            height=155,
            bar_color=_PDF_INDIGO,
            max_y=100.0,
        )
        chart_flowables.append(bar_chart)

      pdf_kwargs = {
          "badge_text": "LAPORAN INDIVIDU",
          "kpis": kpis,
          "chart_flowables": chart_flowables,
          "section_title": "Rincian Penilaian yang Dipublikasikan",
          "col_weights": [1.1, 1.5, 1.7, 1.0, 1.0, 0.9, 1.8],
      }

    return self._export(
        fmt,
        f"laporan_individu_{stu['student_code']}",
        title,
        subtitle,
        headers,
        export_rows if fmt.lower().strip() != "pdf" else (rows or [["-", "-", "Belum ada penilaian dipublikasikan", "-", "-", "-", "-"]]),
        pdf_kwargs=pdf_kwargs,
    )


def iter_export_chunks(data: bytes, chunk_size: int = 65536):
  """Generator chunked untuk StreamingResponse ekspor laporan berukuran besar."""
  view = memoryview(data)
  for offset in range(0, len(view), chunk_size):
    yield bytes(view[offset : offset + chunk_size])
