"use client";

// Custom SVG heatmap. ~150 lines, no @nivo / victory; viewBox-responsive
// so it scales with its parent without a ResizeObserver.
//
// Sprint 8.3.3 use case: kategori × duygu matrix on the dashboard +
// /insights "Çapraz Analiz" tab. Cell click navigates to the filtered
// /reviews page (route ownership is the parent's; this component just
// fires the callback).
//
// Color scale: linear interpolation between two anchor colors. "blue"
// is the default (low = pale, high = navy). The "diverging" scale uses
// red ↔ blue around the matrix's median so mixed-sign data stays
// readable.

import { useMemo, useState } from "react";

interface HeatmapProps {
  rows: string[];
  cols: string[];
  matrix: number[][];
  rowTotals?: number[];
  colTotals?: number[];
  colorScale?: "blue" | "green" | "red" | "diverging";
  cellLabel?: (value: number, row: number, col: number) => string;
  onCellClick?: (row: number, col: number) => void;
  tooltip?: (value: number, rowLabel: string, colLabel: string) => string;
  height?: number;
}

const SCALES: Record<string, [string, string]> = {
  blue: ["#dbeafe", "#1e3a8a"],
  green: ["#dcfce7", "#14532d"],
  red: ["#fee2e2", "#7f1d1d"],
  diverging: ["#fee2e2", "#1e3a8a"],
};

const CELL_W = 64;
const CELL_H = 36;
const ROW_LABEL_W = 140;
const COL_LABEL_H = 40;

function lerp(start: string, end: string, t: number): string {
  const ratio = Math.max(0, Math.min(1, t));
  const a = parseHex(start);
  const b = parseHex(end);
  const r = Math.round(a[0] + (b[0] - a[0]) * ratio);
  const g = Math.round(a[1] + (b[1] - a[1]) * ratio);
  const bl = Math.round(a[2] + (b[2] - a[2]) * ratio);
  return `rgb(${r}, ${g}, ${bl})`;
}

function parseHex(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  return [
    parseInt(h.slice(0, 2), 16),
    parseInt(h.slice(2, 4), 16),
    parseInt(h.slice(4, 6), 16),
  ];
}

export function Heatmap({
  rows,
  cols,
  matrix,
  rowTotals,
  colTotals,
  colorScale = "blue",
  cellLabel,
  onCellClick,
  tooltip,
  height,
}: HeatmapProps) {
  const [hover, setHover] = useState<{ r: number; c: number } | null>(null);

  const max = useMemo(
    () => matrix.reduce((m, row) => Math.max(m, ...row), 0),
    [matrix],
  );
  const scale = SCALES[colorScale] ?? (SCALES.blue as [string, string]);
  const [low, high] = scale;

  const totalsW = rowTotals ? CELL_W : 0;
  const totalsH = colTotals ? CELL_H : 0;

  const width = ROW_LABEL_W + cols.length * CELL_W + totalsW;
  const totalH = COL_LABEL_H + rows.length * CELL_H + totalsH;

  // Mobile responsive: pin the SVG at its native pixel width so labels
  // never shrink to illegible 6px text. The parent's `overflow-x-auto`
  // lets the user pan horizontally on narrow viewports; the touch-pan-x
  // utility hints to mobile browsers that horizontal touch-drag is
  // intended (otherwise iOS Safari sometimes prefers the page scroll).
  return (
    <div className="overflow-x-auto -mx-2 px-2 touch-pan-x">
      <svg
        viewBox={`0 0 ${width} ${totalH}`}
        width={width}
        height={height ?? totalH}
        role="img"
        aria-label="Isı haritası"
        style={{ display: "block" }}
      >
        {/* Column labels */}
        {cols.map((c, j) => (
          <text
            key={`col-${j}`}
            x={ROW_LABEL_W + j * CELL_W + CELL_W / 2}
            y={COL_LABEL_H - 12}
            textAnchor="middle"
            fontSize="11"
            fontWeight="500"
            fill="#374151"
          >
            {c}
          </text>
        ))}

        {/* Body */}
        {rows.map((rLabel, i) => (
          <g key={`row-${i}`}>
            <text
              x={ROW_LABEL_W - 8}
              y={COL_LABEL_H + i * CELL_H + CELL_H / 2 + 4}
              textAnchor="end"
              fontSize="11"
              fill="#374151"
            >
              {rLabel.length > 18 ? `${rLabel.slice(0, 17)}…` : rLabel}
            </text>
            {cols.map((cLabel, j) => {
              const value = matrix[i]?.[j] ?? 0;
              const t = max === 0 ? 0 : value / max;
              const fill = lerp(low, high, t);
              const isHover = hover && hover.r === i && hover.c === j;
              const labelText = cellLabel ? cellLabel(value, i, j) : String(value);
              const tooltipText = tooltip
                ? tooltip(value, rLabel, cLabel)
                : `${rLabel} × ${cLabel}: ${value}`;
              return (
                <g key={`cell-${i}-${j}`}>
                  <rect
                    x={ROW_LABEL_W + j * CELL_W}
                    y={COL_LABEL_H + i * CELL_H}
                    width={CELL_W}
                    height={CELL_H}
                    fill={fill}
                    stroke={isHover ? "#0f172a" : "#ffffff"}
                    strokeWidth={isHover ? 2 : 1}
                    style={{ cursor: onCellClick ? "pointer" : "default" }}
                    onMouseEnter={() => setHover({ r: i, c: j })}
                    onMouseLeave={() => setHover(null)}
                    onClick={() => onCellClick?.(i, j)}
                    role={onCellClick ? "button" : undefined}
                    aria-label={tooltipText}
                  >
                    <title>{tooltipText}</title>
                  </rect>
                  <text
                    x={ROW_LABEL_W + j * CELL_W + CELL_W / 2}
                    y={COL_LABEL_H + i * CELL_H + CELL_H / 2 + 4}
                    textAnchor="middle"
                    fontSize="11"
                    fontWeight="500"
                    fill={t > 0.5 ? "#ffffff" : "#0f172a"}
                    pointerEvents="none"
                  >
                    {labelText}
                  </text>
                </g>
              );
            })}
          </g>
        ))}

        {/* Row totals (right-most column) */}
        {rowTotals?.map((total, i) => (
          <text
            key={`rtotal-${i}`}
            x={ROW_LABEL_W + cols.length * CELL_W + CELL_W / 2}
            y={COL_LABEL_H + i * CELL_H + CELL_H / 2 + 4}
            textAnchor="middle"
            fontSize="11"
            fontWeight="600"
            fill="#1f2937"
          >
            {total}
          </text>
        ))}

        {/* Column totals (bottom row) */}
        {colTotals?.map((total, j) => (
          <text
            key={`ctotal-${j}`}
            x={ROW_LABEL_W + j * CELL_W + CELL_W / 2}
            y={COL_LABEL_H + rows.length * CELL_H + 16}
            textAnchor="middle"
            fontSize="11"
            fontWeight="600"
            fill="#1f2937"
          >
            {total}
          </text>
        ))}
      </svg>
    </div>
  );
}
