"use client";

// Sprint 9.6 redesign — single "CX health" hero.
//
// Replaces the Sprint 8.3.5.6 7-card grid (NPS hero + 6 small support
// metrics). C-level operators don't want 6 numbers; they want one
// big signal: "are we OK or not?". The hero answers it in three
// layers, stacked top-to-bottom:
//
//   1. Big NPS score (band-coloured by Apple-Health-style status).
//   2. Plain-Turkish narrative interpretation in 1 sentence —
//      computed client-side from the same headline metrics so the
//      operator doesn't have to read 6 numbers + the donut + the
//      bar chart to figure out what's happening.
//   3. Data-coverage chip so the executive knows the sample size
//      backing the number ("3.214 yorum · NPS kapsama %41").
//
// Delta vs previous period reads from the existing 12-month NPS
// trend endpoint — the headline-metrics endpoint doesn't carry
// per-period comparison and a backend round-trip per visit isn't
// worth a single arrow on the hero.

import { Activity, AlertTriangle, ArrowDown, ArrowUp, Minus } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { useHeadlineMetrics, useNpsMonthlyTrend } from "@/hooks/use-analytics";
import { useTranslation } from "@/lib/i18n/use-translation";

type Translate = (key: string, vars?: Record<string, string | number>) => string;

type HealthBand = "excellent" | "good" | "watch" | "risk" | "critical" | "no-data";

interface HealthVisual {
  band: HealthBand;
  badge: string;
  container: string;
  scoreColor: string;
}

function healthFromNps(score: number | null, t: Translate): HealthVisual {
  // Sprint 9.6.1 — band visuals refined for the new design system.
  // The container layers a tinted band wash (very subtle) over the
  // card surface so the hero reads as ONE surface with a colour
  // accent, not a coloured rectangle. The score itself uses the
  // brand gradient (gradient-text utility) on the positive bands;
  // negative bands keep a saturated tone so the colour signal
  // matches the meaning.
  if (score === null) {
    return {
      band: "no-data",
      badge: t("dashboard.healthHero.band.noData"),
      container: "border-border/60 bg-card shadow-soft",
      scoreColor: "text-muted-foreground",
    };
  }
  if (score >= 50) {
    return {
      band: "excellent",
      badge: t("dashboard.healthHero.band.excellent"),
      container:
        "border-emerald-200/60 bg-gradient-to-br from-emerald-50/80 via-card to-card dark:border-emerald-900/50 dark:from-emerald-950/30 dark:via-card dark:to-card shadow-elevated",
      scoreColor: "gradient-text",
    };
  }
  if (score >= 30) {
    return {
      band: "good",
      badge: t("dashboard.healthHero.band.good"),
      container:
        "border-emerald-200/40 bg-gradient-to-br from-emerald-50/40 via-card to-card dark:border-emerald-900/30 dark:from-emerald-950/20 dark:via-card dark:to-card shadow-elevated",
      scoreColor: "gradient-text",
    };
  }
  if (score >= 0) {
    return {
      band: "watch",
      badge: t("dashboard.healthHero.band.watch"),
      container:
        "border-amber-200/60 bg-gradient-to-br from-amber-50/80 via-card to-card dark:border-amber-900/40 dark:from-amber-950/25 dark:via-card dark:to-card shadow-elevated",
      scoreColor: "text-amber-700 dark:text-amber-300",
    };
  }
  if (score >= -50) {
    return {
      band: "risk",
      badge: t("dashboard.healthHero.band.risk"),
      container:
        "border-orange-200/70 bg-gradient-to-br from-orange-50/80 via-card to-card dark:border-orange-900/40 dark:from-orange-950/25 dark:via-card dark:to-card shadow-elevated",
      scoreColor: "text-orange-700 dark:text-orange-300",
    };
  }
  return {
    band: "critical",
    badge: t("dashboard.healthHero.band.critical"),
    container:
      "border-red-300/70 bg-gradient-to-br from-red-50/90 via-card to-card dark:border-red-900/50 dark:from-red-950/30 dark:via-card dark:to-card shadow-elevated",
    scoreColor: "text-red-700 dark:text-red-300",
  };
}

function formatScore(score: number | null): string {
  if (score === null) return "—";
  if (score > 0) return `+${Math.round(score)}`;
  return `${Math.round(score)}`;
}

/** Plain-Turkish single-sentence narrative. Reads the same headline
 *  metrics that fed the old 6-card grid; the hero collapses the
 *  signal into one sentence so the operator doesn't have to read
 *  numbers and infer. */
function narrative(
  nps: number | null,
  crisis: number,
  total: number,
  avgSentiment: number | null,
  t: Translate,
): string {
  if (nps === null && total === 0) {
    return t("dashboard.healthHero.narrative.empty");
  }
  if (total > 0 && crisis / total > 0.1) {
    return t("dashboard.healthHero.narrative.crisis");
  }
  if (nps !== null && nps < -30) {
    return t("dashboard.healthHero.narrative.veryNegative");
  }
  if (nps !== null && nps < 0) {
    return t("dashboard.healthHero.narrative.negative");
  }
  if (avgSentiment !== null && avgSentiment < -0.3) {
    return t("dashboard.healthHero.narrative.avgNegative");
  }
  if (nps !== null && nps >= 30) {
    return t("dashboard.healthHero.narrative.good");
  }
  return t("dashboard.healthHero.narrative.balanced");
}

interface DeltaInfo {
  delta: number | null;
  label: string;
}

function computeNpsDelta(
  monthlyTrend: ReadonlyArray<{ score: number | null }> | undefined,
  t: Translate,
): DeltaInfo {
  if (!monthlyTrend || monthlyTrend.length < 2) {
    return { delta: null, label: "" };
  }
  // Walk backward to find the latest two non-null months. NPS can be
  // null on months with no scored reviews; we don't want a -100 delta
  // just because last month had zero NPS coverage.
  let latest: number | null = null;
  let previous: number | null = null;
  for (let i = monthlyTrend.length - 1; i >= 0; i--) {
    const v = monthlyTrend[i]?.score;
    if (v == null) continue;
    if (latest === null) {
      latest = v;
      continue;
    }
    previous = v;
    break;
  }
  if (latest === null || previous === null) {
    return { delta: null, label: "" };
  }
  const delta = latest - previous;
  return {
    delta,
    label: t("dashboard.healthHero.deltaLabel", {
      delta: `${delta > 0 ? "+" : ""}${delta.toFixed(0)}`,
    }),
  };
}

export function HealthHero() {
  const { t } = useTranslation();
  const headline = useHeadlineMetrics({});
  const trend = useNpsMonthlyTrend(12);

  if (headline.isLoading) return <Skeleton className="h-44 w-full" />;
  if (headline.isError) {
    return (
      <div className="border-destructive/30 bg-destructive/5 flex items-center gap-3 rounded-xl border p-6">
        <AlertTriangle className="text-destructive size-5" aria-hidden />
        <div className="text-sm">
          <p className="font-medium">{t("dashboard.healthHero.error.title")}</p>
          <p className="text-muted-foreground">
            {t("dashboard.healthHero.error.desc")}
          </p>
        </div>
      </div>
    );
  }

  const data = headline.data;
  const score = data?.nps_score ?? null;
  const visual = healthFromNps(score, t);
  const text = narrative(
    score,
    data?.crisis_count ?? 0,
    data?.total_reviews ?? 0,
    data?.avg_sentiment_score ?? null,
    t,
  );
  const delta = computeNpsDelta(trend.data, t);

  return (
    <section
      className={`rise-in rounded-2xl border p-6 md:p-10 transition-shadow ${visual.container}`}
      aria-label={t("dashboard.healthHero.aria")}
    >
      <div className="flex flex-wrap items-start gap-x-10 gap-y-6">
        <div className="flex-1 min-w-[14rem]">
          <p className="text-muted-foreground text-[11px] font-semibold uppercase tracking-[0.14em]">
            {t("dashboard.healthHero.headerLabel")}
          </p>
          <div className="mt-3 flex items-baseline gap-4 flex-wrap">
            <span
              className={`text-6xl md:text-7xl font-semibold tabular-nums tracking-tight ${visual.scoreColor}`}
              style={{ letterSpacing: "-0.03em" }}
            >
              {formatScore(score)}
            </span>
            <span
              className={`text-sm font-semibold uppercase tracking-wider ${
                visual.band === "no-data" ? "text-muted-foreground" : "text-foreground/70"
              }`}
            >
              {visual.badge}
            </span>
            {delta.delta !== null && (
              <DeltaPill delta={delta.delta} label={delta.label} />
            )}
          </div>
          <p className="text-foreground/80 mt-4 text-sm md:text-base max-w-2xl leading-relaxed">
            {text}
          </p>
        </div>

        <div className="bg-card/60 ring-foreground/5 flex flex-col gap-2.5 rounded-xl px-4 py-3 text-xs ring-1 min-w-[11rem] backdrop-blur-sm">
          <CoverageRow
            label={t("dashboard.healthHero.coverage.totalReviews")}
            value={(data?.total_reviews ?? 0).toLocaleString("tr-TR")}
          />
          <CoverageRow
            label={t("dashboard.healthHero.coverage.npsCoverage")}
            value={`%${(data?.nps_coverage_percent ?? 0).toFixed(0)}`}
          />
          <CoverageRow
            label={t("dashboard.healthHero.coverage.crisisCount")}
            value={(data?.crisis_count ?? 0).toLocaleString("tr-TR")}
          />
          <CoverageRow
            label={t("dashboard.healthHero.coverage.openTickets")}
            value={(data?.open_tickets ?? 0).toLocaleString("tr-TR")}
          />
        </div>
      </div>
    </section>
  );
}

function DeltaPill({ delta, label }: { delta: number; label: string }) {
  const Icon =
    delta > 0 ? ArrowUp : delta < 0 ? ArrowDown : Minus;
  const tone =
    delta > 0
      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200"
      : delta < 0
        ? "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-200"
        : "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300";
  return (
    <span
      className={`inline-flex items-center gap-0.5 rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}
      title={label}
      aria-label={label}
    >
      <Icon className="size-3" aria-hidden />
      {Math.abs(delta).toFixed(0)}
    </span>
  );
}

function CoverageRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-6">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-foreground font-semibold tabular-nums">{value}</span>
    </div>
  );
}
