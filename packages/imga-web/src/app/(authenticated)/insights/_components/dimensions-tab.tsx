"use client";

// 2026-08-20 — "Boyutlar" tab for /insights.
//
// Mirrors CategoryTab's horizontal bar chart exactly (same BarChart
// layout="vertical" + XAxis/YAxis/Bar shape, same #1e40af fill) — no
// new chart design. Dimension + metric pickers follow the cohort tab's
// <select> pattern. Buckets arrive sorted by count desc from the
// backend; we only slice the first 15 client-side, we don't re-sort.

import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { useTranslation } from "@/lib/i18n/use-translation";
import {
  bucketMetricValue,
  useBusinessDimensions,
  useDimensionBreakdown,
  type BreakdownDimensionKey,
  type DimensionMetricKey,
} from "@/hooks/use-business-dimensions";

const DIMENSION_ORDER: readonly BreakdownDimensionKey[] = [
  "channel",
  "business_segment",
  "product_line",
  "customer_tier",
  "entered_by",
  "source",
];

const DIMENSION_LABEL_KEYS: Record<BreakdownDimensionKey, string> = {
  channel: "dimensions.channel",
  business_segment: "dimensions.businessSegment",
  product_line: "dimensions.productLine",
  customer_tier: "dimensions.customerTier",
  entered_by: "dimensions.enteredBy",
  source: "dimensions.source",
};

// Task-specified UI order: Yorum Sayısı, Olumsuz Payı %, Ortalama Skor,
// Pozitif %, NPS. "Pozitif %" has no dedicated backend metric_key — the
// backend's "sentiment_distribution" branch computes positive_pct per
// bucket (see imga-api services/dimension_service.py), so that's the
// one that maps to "Pozitif %" here (5 UI labels <-> 5 metric_keys,
// the other 4 pairs are unambiguous by name).
const METRIC_ORDER: readonly DimensionMetricKey[] = [
  "review_volume",
  "negative_share",
  "avg_sentiment",
  "sentiment_distribution",
  "nps",
];

const METRIC_LABEL_KEYS: Record<DimensionMetricKey, string> = {
  review_volume: "insights.dimTab.metricVolume",
  negative_share: "insights.dimTab.metricNegativeShare",
  avg_sentiment: "insights.dimTab.metricAvgScore",
  sentiment_distribution: "insights.dimTab.metricPositiveShare",
  nps: "insights.dimTab.metricNps",
};

const MAX_BUCKETS = 15;
// Same blue as CategoryTab / PerspectiveTab's volume bars — reused on
// purpose, not a new palette choice.
const BAR_COLOR = "#1e40af";

function formatTick(
  metricKey: DimensionMetricKey,
  value: number,
  t: (key: string, vars?: Record<string, string | number>) => string,
): string {
  switch (metricKey) {
    case "negative_share":
    case "sentiment_distribution":
      return t("insights.dimTab.percentValue", { value: value.toFixed(0) });
    case "nps":
      return (value > 0 ? "+" : "") + Math.round(value);
    case "avg_sentiment":
      return value.toFixed(1);
    case "review_volume":
    default:
      return String(Math.round(value));
  }
}

interface Props {
  dimension: BreakdownDimensionKey;
  metricKey: DimensionMetricKey;
  dateFrom: string;
  dateTo: string;
  /** 2026-08-18 (Dalga 3, WS2) desenini takip eder — sayfanın üst
   *  filtre çubuğundaki toggle bu tab'a da akar. */
  includeFlagged: boolean;
  onDimensionChange: (next: BreakdownDimensionKey) => void;
  onMetricChange: (next: DimensionMetricKey) => void;
}

export function DimensionsTab({
  dimension,
  metricKey,
  dateFrom,
  dateTo,
  includeFlagged,
  onDimensionChange,
  onMetricChange,
}: Props) {
  const { t } = useTranslation();
  const configs = useBusinessDimensions();
  const query = useDimensionBreakdown({
    dimension,
    metric_key: metricKey,
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
    include_flagged: includeFlagged || undefined,
  });

  // Kurum ayarlarında (settings/business-dimensions) özel bir
  // display_label varsa Boyutlar tab'ı onu tercih eder. entered_by /
  // source için config satırı hiç bulunamaz (DimensionKey'in dışında),
  // find() doğal olarak undefined döner ve sabit i18n etiketine düşer.
  const configRow = configs.data?.find((c) => c.dimension === dimension);
  const dimensionLabel = configRow?.display_label || t(DIMENSION_LABEL_KEYS[dimension]);
  const metricLabel = t(METRIC_LABEL_KEYS[metricKey]);

  const buckets = useMemo(() => {
    if (!query.data) return [];
    return query.data.buckets.slice(0, MAX_BUCKETS).map((b) => ({
      value: b.value,
      display: metricKey === "review_volume" ? b.count : (bucketMetricValue(b) ?? 0),
    }));
  }, [query.data, metricKey]);

  const coveragePct =
    query.data && query.data.total_count > 0
      ? ((query.data.coverage_count / query.data.total_count) * 100).toFixed(1)
      : "0.0";

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="grid grid-cols-1 gap-3 p-4 md:grid-cols-2">
          <div>
            <Label className="text-xs">{t("insights.dimTab.dimension")}</Label>
            <select
              value={dimension}
              onChange={(e) => onDimensionChange(e.target.value as BreakdownDimensionKey)}
              className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
            >
              {DIMENSION_ORDER.map((d) => (
                <option key={d} value={d}>
                  {configs.data?.find((c) => c.dimension === d)?.display_label ||
                    t(DIMENSION_LABEL_KEYS[d])}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label className="text-xs">{t("insights.dimTab.metric")}</Label>
            <select
              value={metricKey}
              onChange={(e) => onMetricChange(e.target.value as DimensionMetricKey)}
              className="border-input bg-background mt-1 w-full rounded-md border px-3 py-2 text-sm"
            >
              {METRIC_ORDER.map((m) => (
                <option key={m} value={m}>
                  {t(METRIC_LABEL_KEYS[m])}
                </option>
              ))}
            </select>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {t("insights.dimTab.chartTitle", {
              dimension: dimensionLabel,
              metric: metricLabel,
            })}
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
          ) : !query.data || buckets.length === 0 ? (
            <p className="text-muted-foreground py-12 text-center text-sm">
              {t("insights.state.noData")}
            </p>
          ) : (
            <>
              <ResponsiveContainer width="100%" height={Math.max(220, buckets.length * 32)}>
                <BarChart layout="vertical" data={buckets}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis
                    type="number"
                    fontSize={10}
                    tickFormatter={(v) => formatTick(metricKey, Number(v), t)}
                  />
                  <YAxis type="category" dataKey="value" fontSize={11} width={140} />
                  <Tooltip />
                  <Bar dataKey="display" name={metricLabel} fill={BAR_COLOR} />
                </BarChart>
              </ResponsiveContainer>
              <p className="text-muted-foreground mt-3 text-xs">
                {t("insights.dimTab.totalCoverage", {
                  total: query.data.total_count,
                  coverage: query.data.coverage_count,
                  pct: coveragePct,
                })}
              </p>
              {query.data.buckets.length > MAX_BUCKETS && (
                <p className="text-muted-foreground mt-1 text-[11px]">
                  {t("insights.dimTab.top15Note")}
                </p>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
