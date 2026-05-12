"use client";

// Sprint 8.3.9 — heatmap tab for /insights.
//
// Plain CSS-grid renderer instead of Recharts custom shape or
// nivo-heatmap. Each cell is a div with a background colour
// interpolated along a viridis-like scale; tooltips on hover; max-
// value cell gets a corner indicator. No new library install.
//
// X / Y / metric selectors live in their own card so the URL state
// pattern (parent-controlled) stays consistent with the other tabs.

import { useMemo, useCallback } from "react";
import { useRouter } from "next/navigation";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { useInsightsHeatmap } from "@/hooks/use-insights-heatmap";
import type {
  HeatmapMetric,
  HeatmapResponse,
  HeatmapXAxis,
  HeatmapYAxis,
} from "@/lib/types";


/**
 * Sprint 9.5 B1 — map an axis type + its raw cell value to the
 * matching /tenants/me/reviews query param. The backend exposes
 * 4 EXTRACT-based filters (hour_of_day, day_of_week, week_of_year,
 * month) plus primary_categories. Returns null when the axis type
 * has no drilldown wired (no current case, but kept for the
 * type-narrowing future).
 */
function _drilldownParam(
  axis: HeatmapXAxis | HeatmapYAxis,
  key: number | string,
): { name: string; value: string } | null {
  switch (axis) {
    case "hour_of_day":
    case "day_of_week":
    case "week_of_year":
    case "month":
      return { name: axis, value: String(key) };
    case "taxonomy_code":
      // /reviews uses the CSV ``primary_categories`` filter for the
      // taxonomy axis (Sprint 8.3.10 wired). We pass a single code
      // here; the user can broaden afterward on the reviews page.
      return { name: "primary_categories", value: String(key) };
    default:
      return null;
  }
}

const X_AXIS_LABELS: Record<HeatmapXAxis, string> = {
  hour_of_day: "Günün Saati",
  day_of_week: "Haftanın Günü",
  week_of_year: "Yılın Haftası",
};

const Y_AXIS_LABELS: Record<HeatmapYAxis, string> = {
  day_of_week: "Haftanın Günü",
  month: "Ay",
  taxonomy_code: "Kategori",
};

const METRIC_LABELS: Record<HeatmapMetric, string> = {
  count: "Yorum Sayısı",
  avg_sentiment: "Ortalama Duygu",
  avg_nps: "Ortalama NPS",
};

interface Props {
  xAxis: HeatmapXAxis;
  yAxis: HeatmapYAxis;
  metric: HeatmapMetric;
  dateFrom: string;
  dateTo: string;
  onXAxisChange: (next: HeatmapXAxis) => void;
  onYAxisChange: (next: HeatmapYAxis) => void;
  onMetricChange: (next: HeatmapMetric) => void;
}

export function HeatmapTab({
  xAxis,
  yAxis,
  metric,
  dateFrom,
  dateTo,
  onXAxisChange,
  onYAxisChange,
  onMetricChange,
}: Props) {
  const router = useRouter();
  const sameAxisError =
    (xAxis as string) === (yAxis as string);

  const query = useInsightsHeatmap({
    x_axis: xAxis,
    y_axis: yAxis,
    metric,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  });

  const { colorFor, maxCell } = useMemo(
    () => buildScale(query.data ?? null),
    [query.data],
  );

  // Sprint 9.5 B1 — heatmap drilldown. Clicking a cell builds the
  // /reviews URL with the cell's axis values + the current heatmap's
  // date range, then navigates. The (xAxis, yAxis) pair selects
  // which backend filters get populated via _drilldownParam.
  const handleCellClick = useCallback(
    (rowIdx: number, colIdx: number) => {
      const data = query.data;
      if (!data) return;
      const xKey = data.x_keys[colIdx];
      const yKey = data.y_keys[rowIdx];
      if (xKey === undefined || yKey === undefined) return;

      const params = new URLSearchParams();
      const xParam = _drilldownParam(xAxis, xKey);
      const yParam = _drilldownParam(yAxis, yKey);
      if (xParam) params.set(xParam.name, xParam.value);
      if (yParam) params.set(yParam.name, yParam.value);
      if (dateFrom) params.set("date_from", dateFrom);
      if (dateTo) params.set("date_to", dateTo);
      router.push(`/reviews?${params.toString()}`);
    },
    [query.data, xAxis, yAxis, dateFrom, dateTo, router],
  );

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="grid grid-cols-1 gap-3 p-4 md:grid-cols-3">
          <div>
            <Label className="text-xs">X ekseni</Label>
            <select
              value={xAxis}
              onChange={(e) => onXAxisChange(e.target.value as HeatmapXAxis)}
              className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
            >
              {(Object.keys(X_AXIS_LABELS) as HeatmapXAxis[]).map((a) => (
                <option key={a} value={a}>
                  {X_AXIS_LABELS[a]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label className="text-xs">Y ekseni</Label>
            <select
              value={yAxis}
              onChange={(e) => onYAxisChange(e.target.value as HeatmapYAxis)}
              className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
            >
              {(Object.keys(Y_AXIS_LABELS) as HeatmapYAxis[]).map((a) => (
                <option key={a} value={a}>
                  {Y_AXIS_LABELS[a]}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label className="text-xs">Metrik</Label>
            <select
              value={metric}
              onChange={(e) => onMetricChange(e.target.value as HeatmapMetric)}
              className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
            >
              {(Object.keys(METRIC_LABELS) as HeatmapMetric[]).map((m) => (
                <option key={m} value={m}>
                  {METRIC_LABELS[m]}
                </option>
              ))}
            </select>
          </div>
        </CardContent>
      </Card>

      {sameAxisError && (
        <p className="text-destructive text-sm">
          X ve Y eksenleri farklı olmalı.
        </p>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {query.data?.metric_label ?? METRIC_LABELS[metric]}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {sameAxisError ? null : query.isLoading || query.isPending ? (
            <p className="text-muted-foreground py-12 text-center text-sm">
              Yükleniyor…
            </p>
          ) : query.isError ? (
            <p className="text-destructive py-12 text-center text-sm">
              Veri yüklenemedi.
            </p>
          ) : !query.data || query.data.values.length === 0 ? (
            <p className="text-muted-foreground py-12 text-center text-sm">
              Bu filtrelerle veri bulunamadı.
            </p>
          ) : (
            <HeatmapGrid
              data={query.data}
              colorFor={colorFor}
              maxCell={maxCell}
              onCellClick={handleCellClick}
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

interface GridProps {
  data: HeatmapResponse;
  colorFor: (v: number | null) => string;
  maxCell: { row: number; col: number; value: number } | null;
  /** Sprint 9.5 B1 — invoked when the operator clicks a cell.
   *  Parent (HeatmapTab) builds the /reviews drilldown URL from
   *  the cell coords + the heatmap's date range and navigates. */
  onCellClick: (rowIdx: number, colIdx: number) => void;
}

function HeatmapGrid({ data, colorFor, maxCell, onCellClick }: GridProps) {
  const cellSize = 36;
  return (
    <div className="overflow-x-auto">
      <div
        className="inline-grid gap-px bg-zinc-200 p-px"
        style={{
          gridTemplateColumns: `120px repeat(${data.x_labels.length}, ${cellSize}px)`,
        }}
      >
        {/* Top-left empty cell */}
        <div className="bg-white" />
        {/* X labels */}
        {data.x_labels.map((label, idx) => (
          <div
            key={`x-${idx}`}
            className="bg-white text-center text-[10px] font-medium text-muted-foreground"
            style={{ width: cellSize, padding: "4px 0" }}
          >
            {label}
          </div>
        ))}
        {/* Rows */}
        {data.y_labels.map((yLabel, rowIdx) => (
          <Row
            key={`row-${rowIdx}`}
            yLabel={yLabel}
            row={data.values[rowIdx] ?? []}
            xLabels={data.x_labels}
            metricLabel={data.metric_label}
            colorFor={colorFor}
            isMaxRow={maxCell?.row === rowIdx}
            maxCol={
              maxCell?.row === rowIdx ? maxCell.col : undefined
            }
            cellSize={cellSize}
            onCellClick={(colIdx) => onCellClick(rowIdx, colIdx)}
          />
        ))}
      </div>

      <div className="mt-3 flex items-center gap-3 text-xs text-muted-foreground">
        <span>Düşük</span>
        <div className="flex h-3 w-40 overflow-hidden rounded">
          {Array.from({ length: 20 }).map((_, i) => (
            <div
              key={i}
              className="flex-1"
              style={{ background: colorFor(i / 19) }}
            />
          ))}
        </div>
        <span>Yüksek</span>
        <span className="ml-auto tabular-nums">
          min {data.metric_min} · max {data.metric_max}
        </span>
      </div>
    </div>
  );
}

function Row({
  yLabel,
  row,
  xLabels,
  metricLabel,
  colorFor,
  isMaxRow,
  maxCol,
  cellSize,
  onCellClick,
}: {
  yLabel: string;
  row: Array<number | null>;
  xLabels: string[];
  metricLabel: string;
  colorFor: (v: number | null) => string;
  isMaxRow: boolean;
  maxCol: number | undefined;
  cellSize: number;
  onCellClick: (colIdx: number) => void;
}) {
  return (
    <>
      <div
        className="bg-white text-right text-xs font-medium pr-2 flex items-center justify-end"
        title={yLabel}
      >
        <span className="truncate">{yLabel}</span>
      </div>
      {xLabels.map((_, colIdx) => {
        const value = row[colIdx] ?? null;
        const isMax = isMaxRow && colIdx === maxCol;
        const isEmpty = value === null;
        return (
          <button
            key={`cell-${colIdx}`}
            type="button"
            // Sprint 9.5 B1 — cell is now a clickable button. Empty
            // cells (value === null) stay disabled because the
            // backend would return zero rows for that drilldown
            // window anyway; clicking would just confuse.
            disabled={isEmpty}
            onClick={isEmpty ? undefined : () => onCellClick(colIdx)}
            className={
              "relative " +
              (isEmpty
                ? "cursor-default"
                : "cursor-pointer hover:ring-2 hover:ring-primary/40")
            }
            style={{
              width: cellSize,
              height: cellSize,
              background: isEmpty ? "#f5f5f5" : colorFor(value),
              padding: 0,
              border: "none",
            }}
            title={
              isEmpty
                ? `${yLabel} × ${xLabels[colIdx]} — veri yok`
                : `${yLabel} × ${xLabels[colIdx]}: ${value} (${metricLabel}) — yorumları gör`
            }
            aria-label={
              isEmpty
                ? `${yLabel} × ${xLabels[colIdx]} boş hücre`
                : `${yLabel} × ${xLabels[colIdx]} hücresinin yorumlarını aç`
            }
          >
            {isMax && (
              <span
                className="absolute right-0.5 top-0.5 text-[8px] font-bold text-white"
                aria-hidden
              >
                ★
              </span>
            )}
          </button>
        );
      })}
    </>
  );
}

interface Scale {
  colorFor: (v: number | null) => string;
  maxCell: { row: number; col: number; value: number } | null;
}

function buildScale(data: HeatmapResponse | null): Scale {
  if (!data) {
    return {
      colorFor: () => "#f5f5f5",
      maxCell: null,
    };
  }
  const min = data.metric_min;
  const max = data.metric_max;
  const range = max - min;

  // Find the max-valued cell for the corner indicator.
  let maxCell: Scale["maxCell"] = null;
  for (let r = 0; r < data.values.length; r++) {
    const row = data.values[r];
    if (!row) continue;
    for (let c = 0; c < row.length; c++) {
      const v = row[c];
      if (v === null || v === undefined) continue;
      if (maxCell === null || v > maxCell.value) {
        maxCell = { row: r, col: c, value: v };
      }
    }
  }

  function colorFor(v: number | null): string {
    if (v === null) return "#f5f5f5";
    let t: number;
    // The scale legend passes a 0..1 ratio directly; data values
    // need normalisation. Detect the legend case by checking if v
    // is already in [0, 1] AND max isn't (avoids confusion when
    // max ≤ 1 naturally).
    if (range <= 0) {
      t = 0.5;
    } else {
      t = (v - min) / range;
    }
    t = Math.max(0, Math.min(1, t));
    return viridisLike(t);
  }
  return { colorFor, maxCell };
}

// Viridis-like 5-stop interpolation. Real viridis is a 256-stop
// LUT; this 5-stop approximation reads close enough for a
// dashboard tile and avoids shipping a 4kB LUT.
const VIRIDIS_STOPS: Array<[number, [number, number, number]]> = [
  [0, [68, 1, 84]],
  [0.25, [59, 82, 139]],
  [0.5, [33, 144, 141]],
  [0.75, [94, 201, 98]],
  [1, [253, 231, 37]],
];

function viridisLike(t: number): string {
  for (let i = 0; i < VIRIDIS_STOPS.length - 1; i++) {
    const [t0, c0] = VIRIDIS_STOPS[i]!;
    const [t1, c1] = VIRIDIS_STOPS[i + 1]!;
    if (t >= t0 && t <= t1) {
      const local = (t - t0) / (t1 - t0);
      const r = Math.round(c0[0] + (c1[0] - c0[0]) * local);
      const g = Math.round(c0[1] + (c1[1] - c0[1]) * local);
      const b = Math.round(c0[2] + (c1[2] - c0[2]) * local);
      return `rgb(${r}, ${g}, ${b})`;
    }
  }
  return "#525252";
}
