"use client";

// Sprint 8.3.8 — column-mapping preview for /analyze/upload Step 2.
//
// Two-column layout:
//   * left: per-column row with detected field, confidence badge,
//     manual-override dropdown, sample values list
//   * right: mini preview table (first 5 rows) with header strip
//     coloured by mapping (yeşil = matched, gri = ignored)
//
// The component is controlled: parent owns the override map
// (column_name → effective field). The detector's verdict drives the
// initial state, but every dropdown change updates the parent so the
// final upload knows which column is the text source.

import { useMemo } from "react";

import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useTranslation } from "@/lib/i18n/use-translation";
import {
  SMART_FIELD_LABELS,
  type DetectedColumn,
  type SmartFieldName,
  type SmartPreviewResponse,
} from "@/lib/types";
import { cn } from "@/lib/utils";

import { ConfidenceBadge, bandFor } from "./confidence-badge";

interface Props {
  preview: SmartPreviewResponse;
  /** Map column header → user-selected field. Undefined = use the
   *  detector's verdict; ``"ignore"`` = drop the column. */
  overrides: Record<string, SmartFieldName | undefined>;
  onOverrideChange: (column: string, field: SmartFieldName | undefined) => void;
}

const FIELD_OPTIONS: SmartFieldName[] = [
  "review_text",
  "nps_score",
  "date",
  "customer_id",
  "order_id",
  "product_name",
  "customer_name",
  "price",
  "ignore",
];

/** Convenience accessor: detector verdict OR user override, with
 *  ``"ignore"`` as the final fallback when neither was set. */
export function effectiveField(
  detected: DetectedColumn,
  overrides: Record<string, SmartFieldName | undefined>,
): SmartFieldName {
  const override = overrides[detected.column_name];
  if (override !== undefined) return override;
  return detected.field_name ?? "ignore";
}

export function ColumnMappingPreview({
  preview,
  overrides,
  onOverrideChange,
}: Props) {
  const { t } = useTranslation();
  const sampleTable = useMemo(() => buildSampleTable(preview), [preview]);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ColumnList
          preview={preview}
          overrides={overrides}
          onOverrideChange={onOverrideChange}
        />
        <SampleTable
          rows={sampleTable.rows}
          headers={preview.headers}
          overrides={overrides}
          detectedByColumn={sampleTable.detectedByColumn}
        />
      </div>
      <p className="text-muted-foreground text-xs">
        {t("analyze.mapping.hint")}
      </p>
    </div>
  );
}

// --- left column: detector verdicts + override dropdowns -----------------

function ColumnList({
  preview,
  overrides,
  onOverrideChange,
}: Props) {
  return (
    <ul className="space-y-2">
      {preview.detected.map((col) => (
        <ColumnRow
          key={col.column_name}
          col={col}
          override={overrides[col.column_name]}
          onChange={(next) => onOverrideChange(col.column_name, next)}
        />
      ))}
    </ul>
  );
}

function ColumnRow({
  col,
  override,
  onChange,
}: {
  col: DetectedColumn;
  override: SmartFieldName | undefined;
  onChange: (next: SmartFieldName | undefined) => void;
}) {
  const { t } = useTranslation();
  const effective = override ?? col.field_name ?? "ignore";
  return (
    <li className="bg-card space-y-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <code className="text-sm font-medium">{col.column_name}</code>
        {col.field_name !== null && override === undefined && (
          <ConfidenceBadge confidence={col.confidence} />
        )}
        {override !== undefined && override !== col.field_name && (
          <Badge variant="outline" className="text-xs">
            {t("analyze.mapping.manuallyChanged")}
          </Badge>
        )}
      </div>

      <Select
        value={effective}
        onValueChange={(v) => {
          const next = (v ?? "ignore") as SmartFieldName;
          // If the user re-selects the detector's verdict, treat it
          // as "no override" so the row doesn't show the badge.
          if (next === col.field_name) onChange(undefined);
          else onChange(next);
        }}
      >
        <SelectTrigger className="h-8 text-xs">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {FIELD_OPTIONS.map((opt) => (
            <SelectItem key={opt} value={opt}>
              {SMART_FIELD_LABELS[opt]}
              {col.field_name === opt && (
                <span className="text-muted-foreground ml-2">
                  {t("analyze.mapping.autoDetectedInline")}
                </span>
              )}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {col.sample_values.length > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("analyze.mapping.sampleLabel")}
          {col.sample_values.map((s) => `"${s}"`).join(", ")}
        </p>
      )}

      {col.alternatives.length > 0 && override === undefined && (
        <p className="text-muted-foreground text-xs">
          {t("analyze.mapping.alternativeLabel")}
          {col.alternatives
            .slice(0, 2)
            .map(
              (a) =>
                `${SMART_FIELD_LABELS[a.field_name]} (%${Math.round(a.confidence * 100)})`,
            )
            .join(" · ")}
        </p>
      )}
    </li>
  );
}

// --- right column: sample table mini preview -----------------------------

interface SampleTableData {
  rows: string[][];
  detectedByColumn: Record<string, DetectedColumn>;
}

function buildSampleTable(preview: SmartPreviewResponse): SampleTableData {
  const rowCount = Math.min(
    5,
    Math.max(...preview.detected.map((d) => d.sample_values.length), 0),
  );
  const rows: string[][] = [];
  for (let i = 0; i < rowCount; i++) {
    const row: string[] = [];
    for (const header of preview.headers) {
      const detected = preview.detected.find((d) => d.column_name === header);
      row.push(detected?.sample_values[i] ?? "");
    }
    rows.push(row);
  }
  const detectedByColumn: Record<string, DetectedColumn> = {};
  for (const d of preview.detected) detectedByColumn[d.column_name] = d;
  return { rows, detectedByColumn };
}

function SampleTable({
  rows,
  headers,
  overrides,
  detectedByColumn,
}: {
  rows: string[][];
  headers: string[];
  overrides: Record<string, SmartFieldName | undefined>;
  detectedByColumn: Record<string, DetectedColumn>;
}) {
  const { t } = useTranslation();
  if (rows.length === 0) {
    return (
      <div className="bg-card flex items-center rounded-lg border p-6 text-sm text-muted-foreground">
        {t("analyze.mapping.noRows")}
      </div>
    );
  }
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-xs">
        <thead className="bg-muted/40 sticky top-0">
          <tr>
            {headers.map((h) => {
              const detected = detectedByColumn[h];
              const override = overrides[h];
              const field = override ?? detected?.field_name ?? "ignore";
              const headerTone = headerToneFor(detected, field);
              return (
                <th
                  key={h}
                  scope="col"
                  className={cn(
                    "border-b px-2 py-1.5 text-left font-medium",
                    headerTone,
                  )}
                >
                  <div className="font-mono text-[11px]">{h}</div>
                  <div className="text-muted-foreground text-[10px] font-normal">
                    {SMART_FIELD_LABELS[field]}
                  </div>
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => (
            <tr key={idx}>
              {row.map((cell, cidx) => {
                const header = headers[cidx] ?? "";
                const override = overrides[header];
                const field =
                  override ?? detectedByColumn[header]?.field_name ?? "ignore";
                const tone = cellToneFor(field);
                return (
                  <td
                    key={cidx}
                    className={cn("max-w-[160px] truncate border-b px-2 py-1", tone)}
                    title={cell}
                  >
                    {cell || "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function headerToneFor(
  detected: DetectedColumn | undefined,
  field: SmartFieldName,
): string {
  if (field === "ignore") return "bg-zinc-100 text-zinc-500";
  if (!detected || detected.field_name === null)
    return "bg-zinc-50";
  const band = bandFor(detected.confidence);
  if (band === "high") return "bg-emerald-50";
  if (band === "medium") return "bg-amber-50";
  return "bg-red-50";
}

function cellToneFor(field: SmartFieldName): string {
  if (field === "ignore") return "bg-zinc-50 text-zinc-400";
  return "";
}
