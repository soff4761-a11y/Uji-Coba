/**
 * Modul Grafik SVG Interaktif Terpadu EduTrack v7:
 * - Satu komponen diagram donat seragam (renderDoughnutChart)
 * - Grafik batang responsif/dapat digulir saat item banyak (renderBarChart)
 * - Grafik garis dengan skala sumbu Y dinamis (renderLineChart)
 */

import { escapeHtml } from "./state.js?v=20261120-v8.4.2";

export const DOUGHNUT_PALETTE = [
  "#38bdf8",
  "#818cf8",
  "#34d399",
  "#fbbf24",
  "#f472b6",
  "#a78bfa",
  "#2dd4bf",
  "#fb923c",
];

/**
 * Komponen Diagram Donat tunggal untuk Portal Guru maupun Portal Siswa.
 */
export function renderDoughnutChart(
  containerId,
  { centerValue, centerLabel, centerBadge = "", segments = [], emptyMessage = "Belum ada data" }
) {
  const el = document.getElementById(containerId);
  if (!el) return;
  const valid = (segments || []).filter((s) => Number(s.value) > 0);
  if (!valid.length) {
    el.innerHTML = `<div class="doughnut-empty">${escapeHtml(emptyMessage)}</div>`;
    return;
  }

  const total = valid.reduce((acc, s) => acc + Number(s.value), 0);
  const r = 68;
  const circ = 2 * Math.PI * r;
  let offset = 0;

  const circles = valid
    .map((s, idx) => {
      const val = Number(s.value);
      const frac = total > 0 ? val / total : 0;
      const dash = frac * circ;
      const color = s.color || DOUGHNUT_PALETTE[idx % DOUGHNUT_PALETTE.length];
      const svgSeg = `<circle cx="95" cy="95" r="${r}" fill="none" stroke="${color}" stroke-width="20"
        stroke-dasharray="${dash.toFixed(2)} ${(circ - dash).toFixed(2)}"
        stroke-dashoffset="${(-offset).toFixed(2)}" transform="rotate(-90 95 95)" stroke-linecap="butt" />`;
      offset += dash;
      return svgSeg;
    })
    .join("");

  const legendRows = valid
    .map((s, idx) => {
      const val = Number(s.value);
      const pct = total > 0 ? Math.round((val / total) * 1000) / 10 : 0;
      const color = s.color || DOUGHNUT_PALETTE[idx % DOUGHNUT_PALETTE.length];
      const displayVal = s.displayValue !== undefined ? s.displayValue : String(val);
      return `<div class="doughnut-legend-row">
        <div class="doughnut-legend-left">
          <span class="doughnut-dot" style="background:${color};"></span>
          <span class="doughnut-legend-label" title="${escapeHtml(s.label)}">${escapeHtml(s.label)}</span>
        </div>
        <strong>${escapeHtml(displayVal)} <span class="muted small">(${pct}%)</span></strong>
      </div>`;
    })
    .join("");

  el.innerHTML = `
    <div class="doughnut-wrap">
      <div class="doughnut-svg-box">
        <svg viewBox="0 0 190 190" role="img" aria-label="${escapeHtml(centerLabel || "Diagram Donat")}">
          <circle cx="95" cy="95" r="${r}" fill="none" stroke="rgba(148,163,184,0.16)" stroke-width="20" />
          ${circles}
          <text x="95" y="90" text-anchor="middle" fill="currentColor" font-size="24" font-weight="700">${escapeHtml(String(centerValue))}</text>
          <text x="95" y="110" text-anchor="middle" fill="currentColor" opacity="0.72" font-size="11" font-weight="600">${escapeHtml(centerLabel || "")}</text>
          ${centerBadge ? `<text x="95" y="126" text-anchor="middle" fill="#38bdf8" font-size="10.5" font-weight="600">${escapeHtml(centerBadge)}</text>` : ""}
        </svg>
      </div>
      <div class="doughnut-legend">${legendRows}</div>
    </div>`;
}

/**
 * Grafik Batang responsif (lebar dinamis & dapat digulir horizontal saat item banyak).
 */
export function renderBarChart(containerId, items, color = "#38bdf8", options = {}) {
  const box = document.getElementById(containerId);
  if (!box) return;
  if (!items || items.length === 0) {
    box.innerHTML = `<p class="muted small">Belum ada data untuk ditampilkan.</p>`;
    return;
  }

  const fullWidth = Boolean(options && options.fullWidth);
  const padL = 40;
  const padR = 20;
  const padT = 24;
  const padB = 46;
  const h = fullWidth ? 250 : 215;
  const baseW = fullWidth ? 860 : 440;
  const slotW = fullWidth ? 108 : 64;
  const maxLabelLen = fullWidth ? 20 : 10;
  const w = Math.max(baseW, items.length * slotW + padL + padR);
  const rawMax = Math.max(...items.map((i) => Number(i.value || 0)), 0);
  const maxVal = rawMax > 0 ? Math.ceil((rawMax * 1.15) / 5) * 5 : 100;
  const step = (w - padL - padR) / items.length;
  const bw = fullWidth ? Math.max(28, Math.min(58, step - 24)) : Math.max(20, Math.min(44, step - 14));
  const valFont = fullWidth ? "12" : "10";
  const lblFont = fullWidth ? "11" : "9.5";

  let bars = "";
  items.forEach((item, idx) => {
    const val = Number(item.value || 0);
    const barH = ((h - padT - padB) * val) / (maxVal || 1);
    const x = padL + idx * step + (step - bw) / 2;
    const y = h - padB - barH;
    const shortLabel = item.label.length > maxLabelLen ? item.label.slice(0, maxLabelLen - 1) + "…" : item.label;
    bars += `
      <rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${barH.toFixed(1)}" rx="6" fill="${item.color || color}">
        <title>${escapeHtml(item.label)}: ${val}</title>
      </rect>
      <text x="${(x + bw / 2).toFixed(1)}" y="${(y - 6).toFixed(1)}" text-anchor="middle" font-size="${valFont}" font-weight="600" fill="currentColor">${val}</text>
      <text x="${(x + bw / 2).toFixed(1)}" y="${h - padB + 18}" text-anchor="middle" font-size="${lblFont}" fill="var(--muted)">${escapeHtml(shortLabel)}</text>
    `;
  });

  const scrollable = w > baseW;
  const svgStyle = scrollable
    ? `min-width:${w}px;height:${h}px;`
    : fullWidth
    ? `width:100%;height:auto;max-height:290px;`
    : "width:100%;height:auto;";
  box.innerHTML = `
    <div class="chart-scroll">
      <svg viewBox="0 0 ${w} ${h}" style="${svgStyle}" aria-label="Grafik Batang">
        <line x1="${padL}" y1="${h - padB}" x2="${w - padR}" y2="${h - padB}" stroke="var(--glass-border)" />
        ${bars}
      </svg>
    </div>`;
}

/**
 * Grafik Garis dengan skala sumbu Y dinamis (mendukung single-series maupun multi-series).
 */
function _isValidLineValue(v) {
  if (v === null || v === undefined || typeof v === "boolean") return false;
  if (typeof v === "string" && v.trim() === "") return false;
  return Number.isFinite(Number(v));
}

export function renderLineChart(containerId, data) {
  const box = document.getElementById(containerId);
  if (!box) return;
  const rawList = Array.isArray(data) ? data : [];
  const isMulti = rawList.length > 0 && rawList.some((item) => item && Array.isArray(item.points));
  const seriesList = isMulti
    ? rawList.map((s) => ({
        name: String(s?.name || ""),
        points: Array.isArray(s?.points) ? s.points : [],
      }))
    : [{ name: "", points: rawList }];

  // Bangun daftar label sumbu X terurut (union lintas seri) dan kumpulkan seluruh nilai numerik valid
  const xLabels = [];
  const labelIndex = new Map();
  const allVals = [];

  for (const s of seriesList) {
    for (const p of s.points) {
      if (!p) continue;
      const lbl = String(p.label ?? "");
      if (!labelIndex.has(lbl)) {
        labelIndex.set(lbl, xLabels.length);
        xLabels.push(lbl);
      }
      if (_isValidLineValue(p.value)) {
        allVals.push(Number(p.value));
      }
    }
  }

  if (!allVals.length || !xLabels.length) {
    box.innerHTML = `<p class="muted small">Belum ada nilai yang dapat digambarkan.</p>`;
    return;
  }

  const padL = 40;
  const padR = 20;
  const padT = 20;
  const padB = 42;
  const h = 215;
  const w = Math.max(460, xLabels.length * 72 + padL + padR);

  const rawMin = Math.min(...allVals);
  const rawMax = Math.max(...allVals);
  const span = rawMax - rawMin;
  const pad = span > 0 ? Math.max(2, span * 0.15) : Math.max(5, Math.abs(rawMax) * 0.1 || 10);
  const minY = Math.max(0, Math.floor((rawMin - pad) / 5) * 5);
  const maxY = Math.ceil((rawMax + pad) / 5) * 5;
  const rangeY = Math.max(1, maxY - minY);

  const stepX = xLabels.length > 1 ? (w - padL - padR) / (xLabels.length - 1) : 0;
  const xForIdx = (i) => (xLabels.length > 1 ? padL + i * stepX : w / 2);
  const yForVal = (val) => h - padB - ((val - minY) / rangeY) * (h - padT - padB);

  const tickCount = 4;
  let grid = "";
  for (let i = 0; i <= tickCount; i++) {
    const tickVal = Math.round((minY + (rangeY * i) / tickCount) * 10) / 10;
    const gy = h - padB - (i / tickCount) * (h - padT - padB);
    grid += `
      <line x1="${padL}" y1="${gy.toFixed(1)}" x2="${w - padR}" y2="${gy.toFixed(1)}" stroke="var(--glass-border)" stroke-dasharray="3 3" />
      <text x="${padL - 6}" y="${(gy + 3).toFixed(1)}" text-anchor="end" font-size="9.5" fill="var(--muted)">${tickVal}</text>
    `;
  }

  const xAxisLabels = xLabels
    .map((lbl, i) => {
      const cx = xForIdx(i);
      return `<text x="${cx.toFixed(1)}" y="${h - padB + 16}" text-anchor="middle" font-size="9" fill="var(--muted)">${escapeHtml(lbl.slice(0, 10))}</text>`;
    })
    .join("");

  const showValueLabels = seriesList.length === 1;
  let pathsMarkup = "";
  let dotsMarkup = "";
  const legendItems = [];

  seriesList.forEach((s, sIdx) => {
    const color = DOUGHNUT_PALETTE[sIdx % DOUGHNUT_PALETTE.length];
    if (s.name) {
      legendItems.push({ name: s.name, color });
    }
    const byLabel = new Map();
    for (const p of s.points) {
      if (!p) continue;
      const lbl = String(p.label ?? "");
      if (_isValidLineValue(p.value)) {
        byLabel.set(lbl, Number(p.value));
      } else if (!byLabel.has(lbl)) {
        byLabel.set(lbl, null);
      }
    }

    const segments = [];
    let currentSeg = [];
    xLabels.forEach((lbl, i) => {
      const val = byLabel.has(lbl) ? byLabel.get(lbl) : null;
      if (val !== null) {
        const pt = { x: xForIdx(i), y: yForVal(val), label: lbl, value: val };
        currentSeg.push(pt);
        const titlePrefix = s.name ? `${escapeHtml(s.name)} — ` : "";
        dotsMarkup += `
          <circle cx="${pt.x.toFixed(1)}" cy="${pt.y.toFixed(1)}" r="4.5" fill="${color}" stroke="#0f172a" stroke-width="1.5">
            <title>${titlePrefix}${escapeHtml(pt.label)}: ${escapeHtml(String(pt.value))}</title>
          </circle>
          ${showValueLabels ? `<text x="${pt.x.toFixed(1)}" y="${(pt.y - 9).toFixed(1)}" text-anchor="middle" font-size="10" fill="currentColor">${escapeHtml(String(pt.value))}</text>` : ""}
        `;
      } else if (currentSeg.length) {
        segments.push(currentSeg);
        currentSeg = [];
      }
    });
    if (currentSeg.length) segments.push(currentSeg);

    const dParts = segments
      .filter((seg) => seg.length >= 2)
      .map((seg) => seg.map((c, idx) => `${idx === 0 ? "M" : "L"} ${c.x.toFixed(1)} ${c.y.toFixed(1)}`).join(" "));
    if (dParts.length) {
      pathsMarkup += `<path d="${dParts.join(" ")}" fill="none" stroke="${color}" stroke-width="2.5" />`;
    }
  });

  const showLegend = seriesList.length > 1 || legendItems.length > 0;
  const legendMarkup = showLegend && legendItems.length
    ? `<div style="display:flex;flex-wrap:wrap;gap:0.75rem;font-size:0.82rem;align-items:center;">${legendItems
        .map(
          (it) =>
            `<span style="display:inline-flex;align-items:center;gap:0.35rem;"><span style="width:10px;height:10px;border-radius:50%;background:${it.color};display:inline-block;"></span>${escapeHtml(it.name)}</span>`
        )
        .join("")}</div>`
    : "";

  const scrollable = w > 460;
  box.innerHTML = `
    <div style="width:100%;display:flex;flex-direction:column;gap:0.5rem;">
      ${legendMarkup}
      <div class="chart-scroll">
        <svg viewBox="0 0 ${w} ${h}" style="${scrollable ? `min-width:${w}px;height:215px;` : "width:100%;height:auto;"}" aria-label="Grafik Garis Dinamis">
          ${grid}
          ${xAxisLabels}
          ${pathsMarkup}
          ${dotsMarkup}
        </svg>
      </div>
    </div>`;
}
