"use client";

// Sprint 8.3.9 — cohort tab for /insights.
//
// Recharts MultiLineChart: each cohort gets its own line; legend is
// interactive (Recharts default). URL state arrives from the parent
// /insights page so the F5 / back-button behaviour stays consistent
// with the other tabs.

import { useMemo } from "react";

// Sprint 9.8 — Madde 9 (UML): Tarih formatı Amerikan değil Türk
// (dd.mm.yyyy). XAxis tick'leri için ISO "YYYY-MM-DD" → "dd.mm.yyyy"
// dönüşümü. Locale-aware Intl Türk başlangıçta "06 May 2026" gibi
// uzun string üretiyor; chart eksenleri için kısa "01.05" yeterli.
function formatPeriodStartTr(value: string): string {
  if (typeof value !== "string" || value.length < 10) return value;
  const [yyyy, mm, dd] = value.slice(0, 10).split("-");
  if (!yyyy || !mm || !dd) return value;
  return `${dd}.${mm}`;
}
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { useTranslation } from "@/lib/i18n/use-translation";
import { useInsightsCohort } from "@/hooks/use-insights-cohort";
import type {
  CohortDimension,
  CohortPeriod,
  CohortResponse,
} from "@/lib/types";

const PERIOD_LABEL_KEYS: Record<CohortPeriod, string> = {
  week: "insights.cohort.periodWeek",
  month: "insights.cohort.periodMonth",
  quarter: "insights.cohort.periodQuarter",
};

const DIMENSION_LABEL_KEYS: Record<CohortDimension, string> = {
  taxonomy: "insights.cohort.dimTaxonomy",
  company_perspective: "insights.cohort.dimPerspective",
  nps_bucket: "insights.cohort.dimNpsBucket",
};

// Distinct line colours — picked for contrast on a white background;
// 10 entries match the default top-10 limit, after which we wrap.
// Sprint 10.2 — palet marka çiftiyle açılır (turuncu + lacivert),
// kalanı ayırt edilebilirlik için geniş hue yelpazesi.
const LINE_COLOURS = [
  "#e26622",
  "#44557d",
  "#16a34a",
  "#dc2626",
  "#9333ea",
  "#0891b2",
  "#db2777",
  "#65a30d",
  "#7c3aed",
  "#0d9488",
];

interface Props {
  period: CohortPeriod;
  dimension: CohortDimension;
  dateFrom: string;
  dateTo: string;
  limitCohorts: number;
  onPeriodChange: (next: CohortPeriod) => void;
  onDimensionChange: (next: CohortDimension) => void;
  onLimitChange: (next: number) => void;
}

export function CohortTab({
  period,
  dimension,
  dateFrom,
  dateTo,
  limitCohorts,
  onPeriodChange,
  onDimensionChange,
  onLimitChange,
}: Props) {
  const { t } = useTranslation();
  const query = useInsightsCohort({
    period,
    dimension,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    limit_cohorts: limitCohorts,
  });

  const chartData = useMemo(
    () => buildChartData(query.data ?? null),
    [query.data],
  );

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="grid grid-cols-1 gap-3 p-4 md:grid-cols-3">
          <div>
            <Label className="text-xs">{t("insights.cohort.period")}</Label>
            <select
              value={period}
              onChange={(e) => onPeriodChange(e.target.value as CohortPeriod)}
              className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
            >
              {(Object.keys(PERIOD_LABEL_KEYS) as CohortPeriod[]).map((p) => (
                <option key={p} value={p}>
                  {t(PERIOD_LABEL_KEYS[p])}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label className="text-xs">{t("insights.cohort.dimension")}</Label>
            <select
              value={dimension}
              onChange={(e) =>
                onDimensionChange(e.target.value as CohortDimension)
              }
              className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
            >
              {(Object.keys(DIMENSION_LABEL_KEYS) as CohortDimension[]).map(
                (d) => (
                  <option key={d} value={d}>
                    {t(DIMENSION_LABEL_KEYS[d])}
                  </option>
                ),
              )}
            </select>
          </div>
          <div>
            <Label className="text-xs">{t("insights.cohort.topCohorts")}</Label>
            <input
              type="number"
              min={1}
              max={20}
              value={limitCohorts}
              onChange={(e) => {
                const n = Number(e.target.value);
                if (Number.isFinite(n) && n >= 1 && n <= 20)
                  onLimitChange(n);
              }}
              className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
            />
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t("insights.cohort.trendTitle")}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {query.isLoading || query.isPending ? (
            <p className="text-muted-foreground py-12 text-center text-sm">
              {t("common.loading")}
            </p>
          ) : query.isError ? (
            <p className="text-destructive py-12 text-center text-sm">
              {t("insights.state.loadErrorShort")}
            </p>
          ) : !query.data || query.data.cohorts.length === 0 ? (
            <p className="text-muted-foreground py-12 text-center text-sm">
              {t("insights.state.noData")}
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={360}>
              <LineChart data={chartData.points}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="period_start"
                  fontSize={10}
                  tickFormatter={formatPeriodStartTr}
                />
                <YAxis fontSize={10} />
                <Tooltip />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {query.data.cohorts.map((cohort, idx) => (
                  <Line
                    key={cohort.key}
                    type="monotone"
                    dataKey={cohort.key}
                    name={cohort.label}
                    stroke={LINE_COLOURS[idx % LINE_COLOURS.length]}
                    strokeWidth={2}
                    dot={{ r: 3 }}
                    connectNulls={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

interface ChartShape {
  points: Array<Record<string, number | string | null>>;
}

function buildChartData(data: CohortResponse | null): ChartShape {
  if (!data) return { points: [] };
  // Pivot from "list of cohorts each with data points" to
  // "list of (period_start, cohort_key → count)" for Recharts.
  const periodSet = new Set<string>();
  for (const c of data.cohorts) {
    for (const dp of c.data_points) {
      periodSet.add(dp.period_start);
    }
  }
  const periods = Array.from(periodSet).sort();
  const lookup: Record<string, Record<string, number>> = {};
  for (const c of data.cohorts) {
    for (const dp of c.data_points) {
      lookup[dp.period_start] ??= {};
      lookup[dp.period_start]![c.key] = dp.count;
    }
  }
  const points = periods.map((p) => {
    const row: Record<string, number | string | null> = { period_start: p };
    for (const c of data.cohorts) {
      row[c.key] = lookup[p]?.[c.key] ?? null;
    }
    return row;
  });
  return { points };
}
