"use client";

// Sprint 8.3.5 / 8.3.5.6 dashboard top row.
//
// Single backend round-trip via /tenants/me/analytics/headline-metrics
// fans out into a 7-card grid:
//   * One large "NPS" card up top (full width on small screens, 2-col
//     wide on lg) — colour-coded by score band.
//   * Six small support cards below: Toplam yorum, Açık ticket,
//     Bugün açılan, Kriz adedi, Ort. duygu, Hassas konular.
//
// The NPS colour band logic intentionally lives here (not a shared
// helper): it's the only consumer for now and the mapping is
// dashboard-product owned, not a generic palette.

import {
  Activity,
  AlertOctagon,
  CalendarPlus,
  CircleAlert,
  Inbox,
  MessageSquareText,
  ShieldAlert,
} from "lucide-react";

import { MetricCard } from "@/components/dashboard/metric-card";
import { Skeleton } from "@/components/ui/skeleton";
import { useHeadlineMetrics } from "@/hooks/use-analytics";
import { useTranslation } from "@/lib/i18n/use-translation";

type Translate = (key: string, vars?: Record<string, string | number>) => string;

function npsBandClasses(
  score: number | null,
  t: Translate,
): {
  containerClass: string;
  labelClass: string;
  badge: string;
} {
  if (score === null) {
    return {
      containerClass: "border-border bg-card",
      labelClass: "text-muted-foreground",
      badge: t("dashboard.headlineMetrics.band.noData"),
    };
  }
  if (score >= 50) {
    return {
      containerClass: "border-emerald-500/50 bg-emerald-50 dark:bg-emerald-950/20",
      labelClass: "text-emerald-700 dark:text-emerald-400",
      badge: t("dashboard.headlineMetrics.band.excellent"),
    };
  }
  if (score >= 30) {
    return {
      containerClass: "border-emerald-300/60 bg-emerald-50/50 dark:bg-emerald-950/10",
      labelClass: "text-emerald-600 dark:text-emerald-300",
      badge: t("dashboard.headlineMetrics.band.good"),
    };
  }
  if (score >= 0) {
    return {
      containerClass: "border-amber-400/60 bg-amber-50 dark:bg-amber-950/20",
      labelClass: "text-amber-700 dark:text-amber-400",
      badge: t("dashboard.headlineMetrics.band.improvable"),
    };
  }
  if (score >= -50) {
    return {
      containerClass: "border-orange-400/60 bg-orange-50 dark:bg-orange-950/20",
      labelClass: "text-orange-700 dark:text-orange-400",
      badge: t("dashboard.headlineMetrics.band.risky"),
    };
  }
  return {
    containerClass: "border-red-500/60 bg-red-50 dark:bg-red-950/20",
    labelClass: "text-red-700 dark:text-red-400",
    badge: t("dashboard.headlineMetrics.band.critical"),
  };
}

function formatScore(value: number | null): string {
  if (value === null) return "—";
  // NPS is -100..100, rendered without decimals to keep the headline
  // tile uncluttered. Backend already rounds to 2dp.
  return value > 0 ? `+${Math.round(value)}` : `${Math.round(value)}`;
}

function formatAvgSentiment(value: number | null): string {
  if (value === null) return "—";
  return value.toFixed(2);
}

interface HeadlineMetricsCardsProps {
  /** Sprint 9.5 B4 — when present, scopes review-side metrics + NPS
   * to a single batch job. Tickets-side counts stay tenant-wide (the
   * service contract). The dashboard leaves this unset; the strategy
   * page can pass a batch_job_id when rendering a batch-scoped SWOT
   * so the headline numbers match the report's input universe. */
  batchJobId?: string;
}

export function HeadlineMetricsCards({ batchJobId }: HeadlineMetricsCardsProps = {}) {
  const { t } = useTranslation();
  // No date filter at the dashboard level — last-30-days style
  // narrowing happens on the /insights page. The dashboard reflects
  // tenant-wide state.
  const { data, isLoading, isError } = useHeadlineMetrics({ batch_job_id: batchJobId });
  const npsScore = data?.nps_score ?? null;
  const band = npsBandClasses(npsScore, t);

  return (
    <div className="space-y-4">
      {/* Large NPS hero card */}
      <section
        className={`rounded-lg border p-6 transition-colors ${band.containerClass}`}
        aria-label={t("dashboard.headlineMetrics.npsAria")}
      >
        <header className="flex items-start justify-between">
          <div>
            <p className="text-muted-foreground text-sm font-medium">Net Promoter Score</p>
            <p className={`mt-1 text-xs font-medium ${band.labelClass}`}>{band.badge}</p>
          </div>
          <Activity className={`size-5 ${band.labelClass}`} aria-hidden />
        </header>
        <div className="mt-3 flex items-baseline gap-3">
          {isLoading ? (
            <Skeleton className="h-12 w-24" />
          ) : isError ? (
            <span className="text-muted-foreground text-4xl font-semibold tracking-tight">—</span>
          ) : (
            <span className={`text-5xl font-semibold tracking-tight ${band.labelClass}`}>
              {formatScore(npsScore)}
            </span>
          )}
          <span className="text-muted-foreground text-sm">
            {t("dashboard.headlineMetrics.coverage", {
              pct: (data?.nps_coverage_percent ?? 0).toFixed(1),
            })}
          </span>
        </div>
        {isError ? (
          <p className="text-destructive mt-2 text-xs">
            {t("dashboard.common.loadFailed")}
          </p>
        ) : null}
      </section>

      {/* Six support cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <MetricCard
          title={t("dashboard.headlineMetrics.totalReviews")}
          hint={t("dashboard.headlineMetrics.totalReviewsHint")}
          value={data?.total_reviews}
          isLoading={isLoading}
          isError={isError}
          icon={MessageSquareText}
        />
        <MetricCard
          title={t("dashboard.headlineMetrics.openTickets")}
          hint={t("dashboard.headlineMetrics.openTicketsHint")}
          value={data?.open_tickets}
          isLoading={isLoading}
          isError={isError}
          icon={Inbox}
          iconClassName="text-primary size-4"
        />
        <MetricCard
          title={t("dashboard.headlineMetrics.openedToday")}
          hint={t("dashboard.headlineMetrics.openedTodayHint")}
          value={data?.today_new_tickets}
          isLoading={isLoading}
          isError={isError}
          icon={CalendarPlus}
        />
        <MetricCard
          title={t("dashboard.headlineMetrics.crisisCount")}
          hint={t("dashboard.headlineMetrics.crisisCountHint")}
          value={data?.crisis_count}
          isLoading={isLoading}
          isError={isError}
          icon={CircleAlert}
          iconClassName="text-destructive size-4"
        />
        <AvgSentimentCard
          value={data?.avg_sentiment_score ?? null}
          isLoading={isLoading}
          isError={isError}
        />
        <MetricCard
          title={t("dashboard.headlineMetrics.sensitiveTopics")}
          hint={t("dashboard.headlineMetrics.sensitiveTopicsHint")}
          value={data?.sensitive_topics_count}
          isLoading={isLoading}
          isError={isError}
          icon={ShieldAlert}
          iconClassName="text-amber-600 size-4"
        />
      </div>
    </div>
  );
}

/** Separate card because avg_sentiment_score is a float, not the
 *  integer the shared MetricCard renders. */
function AvgSentimentCard({
  value,
  isLoading,
  isError,
}: {
  value: number | null;
  isLoading: boolean;
  isError: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="bg-card flex flex-col gap-2 rounded-lg border p-5">
      <div className="flex items-center justify-between">
        <span className="text-muted-foreground text-sm font-medium">
          {t("dashboard.headlineMetrics.avgSentiment")}
        </span>
        <AlertOctagon className="text-muted-foreground size-4" aria-hidden />
      </div>
      <div>
        {isLoading ? (
          <Skeleton className="h-9 w-16" />
        ) : isError ? (
          <span className="text-muted-foreground text-3xl font-semibold tracking-tight">—</span>
        ) : (
          <span className="text-3xl font-semibold tracking-tight">{formatAvgSentiment(value)}</span>
        )}
      </div>
      <p className="text-muted-foreground text-xs">
        {t("dashboard.headlineMetrics.avgSentimentRange")}
      </p>
    </div>
  );
}
