"use client";

// 2026-08-21 — "Operasyon" tab for /insights.
//
// Backend (imga-api) is being written by a parallel agent against a
// fixed contract (5 endpoints: summary, breakdown, sentiment-
// correlation, fact-mappings GET/PUT). This component + its hooks
// (@/hooks/use-operations) code strictly to that contract.
//
// Section 2 (dimension breakdown) mirrors dimensions-tab.tsx's
// horizontal bar chart pattern; several i18n keys are deliberately
// REUSED from insights.dimTab.* (dimension/metric select labels,
// chart title, coverage caption, "top 15" note) since the copy is
// identical between the two tabs — see the task's dimension-label
// reuse instruction.

import Link from "next/link";
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
import {
  useBusinessDimensions,
  type BreakdownDimensionKey,
} from "@/hooks/use-business-dimensions";
import {
  useOperationsBreakdown,
  useOperationsSummary,
  useSentimentCorrelation,
  type OperationsMetricKey,
  type OperationsQueryFilters,
} from "@/hooks/use-operations";
import { formatDurationMinutes } from "@/lib/number-format";
import { useTranslation } from "@/lib/i18n/use-translation";

// Sentiment renkleri: insights/page.tsx'teki SENTIMENT_COLOURS ile aynı
// hex değerleri — kasıtlı yerel kopya (page.tsx bir Next.js Page dosyası,
// oradan named export App Router'ın izin verdiği export alanları
// listesini bozar; compare/page.tsx ve sentiment-donut.tsx da aynı
// nedenle kendi kopyalarını tutuyor). Anahtarlar operasyon uçlarının
// sözleşmesine göre ASCII "NOTR" (Ö'süz) — insights'in kendi iç
// state'indeki "NÖTR" ile KARIŞTIRMAYIN, bu iki ayrı sözlük.
const OPS_SENTIMENT_COLOURS: Record<"NEGATIF" | "NOTR" | "POZITIF", string> = {
  NEGATIF: "#dc2626",
  NOTR: "#737373",
  POZITIF: "#16a34a",
};

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

const METRIC_ORDER: readonly OperationsMetricKey[] = [
  "violation_rate",
  "first_response_violation_rate",
  "avg_resolution_minutes",
  "avg_first_response_minutes",
  "avg_agent_interactions",
  "avg_customer_interactions",
  "csat_avg",
];

const METRIC_LABEL_KEYS: Record<OperationsMetricKey, string> = {
  violation_rate: "insights.opsTab.metricViolationRate",
  first_response_violation_rate: "insights.opsTab.metricFirstResponseViolationRate",
  avg_resolution_minutes: "insights.opsTab.metricAvgResolution",
  avg_first_response_minutes: "insights.opsTab.metricAvgFirstResponse",
  avg_agent_interactions: "insights.opsTab.metricAvgAgentInteractions",
  avg_customer_interactions: "insights.opsTab.metricAvgCustomerInteractions",
  csat_avg: "insights.opsTab.metricCsatAvg",
};

const MAX_BUCKETS = 15;
const BAR_COLOR = "#1e40af";
const LOW_SAMPLE_THRESHOLD = 1000;

function isPercentMetric(m: OperationsMetricKey): boolean {
  return m === "violation_rate" || m === "first_response_violation_rate";
}
function isDurationMetric(m: OperationsMetricKey): boolean {
  return m === "avg_resolution_minutes" || m === "avg_first_response_minutes";
}

function formatBreakdownTick(metric: OperationsMetricKey, value: number): string {
  if (isPercentMetric(metric)) return `%${value.toFixed(1)}`;
  if (isDurationMetric(metric)) return formatDurationMinutes(value);
  if (metric === "csat_avg") return value.toFixed(2);
  return value.toFixed(1);
}

interface Props {
  dateFrom: string;
  dateTo: string;
  includeFlagged: boolean;
  odim: BreakdownDimensionKey;
  ometric: OperationsMetricKey;
  onOdimChange: (next: BreakdownDimensionKey) => void;
  onOmetricChange: (next: OperationsMetricKey) => void;
}

export function OperationsTab({
  dateFrom,
  dateTo,
  includeFlagged,
  odim,
  ometric,
  onOdimChange,
  onOmetricChange,
}: Props) {
  const { t } = useTranslation();

  const filters = useMemo<OperationsQueryFilters>(
    () => ({
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
      include_flagged: includeFlagged || undefined,
    }),
    [dateFrom, dateTo, includeFlagged],
  );

  const summary = useOperationsSummary(filters);
  const configs = useBusinessDimensions();
  const breakdown = useOperationsBreakdown({
    ...filters,
    dimension: odim,
    metric_key: ometric,
  });
  const correlation = useSentimentCorrelation(filters);

  const noOperationalData =
    summary.data != null &&
    Object.values(summary.data.facts_coverage).every((v) => v === 0);

  if (summary.isLoading || summary.isPending) {
    return (
      <p className="text-muted-foreground py-12 text-center text-sm">
        {t("common.loading")}
      </p>
    );
  }
  if (summary.isError || !summary.data) {
    return (
      <p className="text-destructive py-12 text-center text-sm">
        {t("insights.state.loadErrorShort")}
      </p>
    );
  }
  if (noOperationalData) {
    return (
      <Card>
        <CardContent className="space-y-3 p-6">
          <p className="text-muted-foreground text-sm">
            {t("insights.opsTab.noDataHint")}
          </p>
          <Link
            href="/settings/business-dimensions"
            className="text-primary inline-block text-sm underline"
          >
            {t("insights.opsTab.noDataCta")}
          </Link>
        </CardContent>
      </Card>
    );
  }

  const s = summary.data;
  const dimensionLabel =
    configs.data?.find((c) => c.dimension === odim)?.display_label ||
    t(DIMENSION_LABEL_KEYS[odim]);
  const metricLabel = t(METRIC_LABEL_KEYS[ometric]);

  return (
    <div className="space-y-4">
      {/* 1) SLA özet kartları */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-4">
        <SlaStat
          label={t("insights.opsTab.metricSlaResolutionViolation")}
          value={
            s.facts_coverage.sla_resolution === 0
              ? "—"
              : t("insights.dimTab.percentValue", {
                  value: s.sla.resolution.violation_rate_pct.toFixed(1),
                })
          }
          coverage={t("insights.opsTab.coverageOf", {
            count: s.facts_coverage.sla_resolution,
          })}
        />
        <SlaStat
          label={t("insights.opsTab.metricSlaFirstResponseViolation")}
          value={
            s.facts_coverage.sla_first_response === 0
              ? "—"
              : t("insights.dimTab.percentValue", {
                  value: s.sla.first_response.violation_rate_pct.toFixed(1),
                })
          }
          coverage={t("insights.opsTab.coverageOf", {
            count: s.facts_coverage.sla_first_response,
          })}
        />
        <SlaStat
          label={t("insights.opsTab.metricAvgResolutionTime")}
          value={formatDurationMinutes(s.sla.avg_resolution_minutes)}
          coverage={t("insights.opsTab.coverageOf", {
            count: s.facts_coverage.sla_resolution,
          })}
        />
        <SlaStat
          label={t("insights.opsTab.metricAvgFirstResponseTime")}
          value={formatDurationMinutes(s.sla.avg_first_response_minutes)}
          coverage={t("insights.opsTab.coverageOf", {
            count: s.facts_coverage.sla_first_response,
          })}
        />
      </div>

      {/* 2) Boyuta göre kırılım */}
      <Card>
        <CardContent className="grid grid-cols-1 gap-3 p-4 md:grid-cols-2">
          <div>
            <Label className="text-xs">{t("insights.dimTab.dimension")}</Label>
            <select
              value={odim}
              onChange={(e) => onOdimChange(e.target.value as BreakdownDimensionKey)}
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
              value={ometric}
              onChange={(e) => onOmetricChange(e.target.value as OperationsMetricKey)}
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
          <BreakdownChart breakdown={breakdown} metricKey={ometric} />
        </CardContent>
      </Card>

      {/* 3) SLA × Duygu */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("insights.opsTab.slaSentimentTitle")}</CardTitle>
        </CardHeader>
        <CardContent>
          <SlaSentimentChart correlation={correlation} />
        </CardContent>
      </Card>

      {/* 4) CSAT */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{t("insights.opsTab.csatTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <CsatSection summary={s} correlation={correlation} t={t} />
        </CardContent>
      </Card>

      {/* 5) Tazmin & Teslimat */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("insights.opsTab.compensationTitle")}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <StatusList statuses={s.compensation.statuses} emptyLabel={t("insights.state.noData")} />
            <dl className="grid grid-cols-1 gap-2 text-xs">
              <div className="flex items-center justify-between">
                <dt className="text-muted-foreground">{t("insights.opsTab.freightSum")}</dt>
                <dd className="font-semibold">
                  {s.compensation.freight_cost_sum.toLocaleString("tr-TR")}
                </dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-muted-foreground">{t("insights.opsTab.goodsSum")}</dt>
                <dd className="font-semibold">
                  {s.compensation.goods_cost_sum.toLocaleString("tr-TR")}
                </dd>
              </div>
            </dl>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">{t("insights.opsTab.deliveryTitle")}</CardTitle>
          </CardHeader>
          <CardContent>
            <StatusList statuses={s.delivery.statuses} emptyLabel={t("insights.state.noData")} />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function SlaStat({
  label,
  value,
  coverage,
}: {
  label: string;
  value: string;
  coverage: string;
}) {
  return (
    <div className="bg-muted/30 rounded-md border p-3">
      <p className="text-muted-foreground text-xs">{label}</p>
      <p className="text-lg font-semibold">{value}</p>
      <p className="text-muted-foreground mt-1 text-[11px]">{coverage}</p>
    </div>
  );
}

function StatusList({
  statuses,
  emptyLabel,
}: {
  statuses: Record<string, number>;
  emptyLabel: string;
}) {
  const entries = Object.entries(statuses).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) {
    return <p className="text-muted-foreground text-sm">{emptyLabel}</p>;
  }
  return (
    <ul className="space-y-1.5">
      {entries.map(([status, count]) => (
        <li key={status} className="flex items-center justify-between text-sm">
          <span>{status}</span>
          <span className="text-muted-foreground font-mono text-xs">{count}</span>
        </li>
      ))}
    </ul>
  );
}

function BreakdownChart({
  breakdown,
  metricKey,
}: {
  breakdown: ReturnType<typeof useOperationsBreakdown>;
  metricKey: OperationsMetricKey;
}) {
  const { t } = useTranslation();
  const buckets = useMemo(() => {
    if (!breakdown.data) return [];
    return breakdown.data.buckets.slice(0, MAX_BUCKETS).map((b) => ({
      value: b.value,
      display: b.metric_value ?? 0,
    }));
  }, [breakdown.data]);

  if (breakdown.isLoading || breakdown.isPending) {
    return (
      <p className="text-muted-foreground py-12 text-center text-sm">{t("common.loading")}</p>
    );
  }
  if (breakdown.isError) {
    return (
      <p className="text-destructive py-12 text-center text-sm">
        {t("insights.state.loadErrorShort")}
      </p>
    );
  }
  if (!breakdown.data || buckets.length === 0) {
    return (
      <p className="text-muted-foreground py-12 text-center text-sm">{t("insights.state.noData")}</p>
    );
  }

  const coveragePct =
    breakdown.data.total_count > 0
      ? ((breakdown.data.coverage_count / breakdown.data.total_count) * 100).toFixed(1)
      : "0.0";

  return (
    <>
      <ResponsiveContainer width="100%" height={Math.max(220, buckets.length * 32)}>
        <BarChart layout="vertical" data={buckets}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis
            type="number"
            fontSize={10}
            tickFormatter={(v) => formatBreakdownTick(metricKey, Number(v))}
          />
          <YAxis type="category" dataKey="value" fontSize={11} width={140} />
          <Tooltip />
          <Bar dataKey="display" fill={BAR_COLOR} />
        </BarChart>
      </ResponsiveContainer>
      <p className="text-muted-foreground mt-3 text-xs">
        {t("insights.dimTab.totalCoverage", {
          total: breakdown.data.total_count,
          coverage: breakdown.data.coverage_count,
          pct: coveragePct,
        })}
      </p>
      {breakdown.data.buckets.length > MAX_BUCKETS && (
        <p className="text-muted-foreground mt-1 text-[11px]">{t("insights.dimTab.top15Note")}</p>
      )}
    </>
  );
}

function SlaSentimentChart({
  correlation,
}: {
  correlation: ReturnType<typeof useSentimentCorrelation>;
}) {
  const { t } = useTranslation();

  const rows = useMemo(() => {
    if (!correlation.data) return [];
    const source: Array<{
      key: "violated" | "within";
      label: string;
      bucket: { NEGATIF: number; NOTR: number; POZITIF: number };
    }> = [
      {
        key: "violated",
        label: t("insights.opsTab.slaViolated"),
        bucket: correlation.data.sla.violated,
      },
      {
        key: "within",
        label: t("insights.opsTab.slaWithin"),
        bucket: correlation.data.sla.within,
      },
    ];
    return source.map((row) => {
      const total = row.bucket.NEGATIF + row.bucket.NOTR + row.bucket.POZITIF;
      if (total === 0) {
        return { name: row.label, NEGATIF: 0, NOTR: 0, POZITIF: 0, n: 0 };
      }
      return {
        name: row.label,
        NEGATIF: (row.bucket.NEGATIF / total) * 100,
        NOTR: (row.bucket.NOTR / total) * 100,
        POZITIF: (row.bucket.POZITIF / total) * 100,
        n: total,
      };
    });
  }, [correlation.data, t]);

  if (correlation.isLoading || correlation.isPending) {
    return (
      <p className="text-muted-foreground py-12 text-center text-sm">{t("common.loading")}</p>
    );
  }
  if (correlation.isError || !correlation.data) {
    return (
      <p className="text-destructive py-12 text-center text-sm">
        {t("insights.state.loadErrorShort")}
      </p>
    );
  }
  if (rows.every((r) => r.n === 0)) {
    return <p className="text-muted-foreground py-12 text-center text-sm">{t("insights.state.noData")}</p>;
  }

  return (
    <ResponsiveContainer width="100%" height={140}>
      {/* Değerler zaten satır bazında %100'e normalize edilmiş
          (bkz. rows useMemo) — recharts'ın kendi stackOffset="expand"
          yeniden-normalizasyonu burada YOK, aksi halde 0-1 aralığına
          düşer ve domain={[0,100]} ile çakışır. */}
      <BarChart layout="vertical" data={rows}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis type="number" domain={[0, 100]} tickFormatter={(v) => `%${v}`} fontSize={10} />
        <YAxis type="category" dataKey="name" fontSize={11} width={70} />
        <Tooltip formatter={(value) => `%${Number(value).toFixed(1)}`} />
        <Bar dataKey="NEGATIF" stackId="sla" fill={OPS_SENTIMENT_COLOURS.NEGATIF} />
        <Bar dataKey="NOTR" stackId="sla" fill={OPS_SENTIMENT_COLOURS.NOTR} />
        <Bar dataKey="POZITIF" stackId="sla" fill={OPS_SENTIMENT_COLOURS.POZITIF} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function CsatSection({
  summary,
  correlation,
  t,
}: {
  summary: import("@/hooks/use-operations").OperationsSummary;
  correlation: ReturnType<typeof useSentimentCorrelation>;
  t: ReturnType<typeof useTranslation>["t"];
}) {
  const distData = useMemo(
    () =>
      (["1", "2", "3", "4", "5"] as const).map((star) => ({
        star,
        count: summary.csat.distribution[star] ?? 0,
      })),
    [summary.csat.distribution],
  );

  if (summary.csat.count === 0) {
    return <p className="text-muted-foreground text-sm">{t("insights.state.noData")}</p>;
  }

  const agreement = correlation.data?.agreement ?? null;

  return (
    <>
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={distData}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="star" fontSize={11} />
          <YAxis fontSize={10} />
          <Tooltip />
          <Bar dataKey="count" fill={BAR_COLOR} />
        </BarChart>
      </ResponsiveContainer>
      <dl className="grid grid-cols-1 gap-1 text-sm sm:grid-cols-2">
        <div className="flex items-center justify-between">
          <dt className="text-muted-foreground">{t("insights.opsTab.csatAvgLabel")}</dt>
          <dd className="font-semibold">
            {summary.csat.avg_score === null ? "—" : summary.csat.avg_score.toFixed(2)}
          </dd>
        </div>
      </dl>
      {agreement && (
        <div className="text-muted-foreground space-y-1 text-xs">
          {agreement.csat_high_model_positive_pct !== null && (
            <p>
              {t("insights.opsTab.csatAgreementHigh", {
                pct: agreement.csat_high_model_positive_pct.toFixed(1),
              })}
            </p>
          )}
          {agreement.csat_low_model_negative_pct !== null && (
            <p>
              {t("insights.opsTab.csatAgreementLow", {
                pct: agreement.csat_low_model_negative_pct.toFixed(1),
              })}
            </p>
          )}
          {agreement.n_csat < LOW_SAMPLE_THRESHOLD && (
            <p>{t("insights.opsTab.lowSampleNote", { n: agreement.n_csat })}</p>
          )}
        </div>
      )}
    </>
  );
}
