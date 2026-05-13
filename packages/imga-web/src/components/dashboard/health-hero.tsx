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

type HealthBand = "excellent" | "good" | "watch" | "risk" | "critical" | "no-data";

interface HealthVisual {
  band: HealthBand;
  badge: string;
  container: string;
  scoreColor: string;
}

function healthFromNps(score: number | null): HealthVisual {
  if (score === null) {
    return {
      band: "no-data",
      badge: "Yeterli veri yok",
      container: "border-border bg-card",
      scoreColor: "text-muted-foreground",
    };
  }
  if (score >= 50) {
    return {
      band: "excellent",
      badge: "Mükemmel",
      container: "border-emerald-500/40 bg-gradient-to-br from-emerald-50 to-white dark:from-emerald-950/30 dark:to-zinc-900",
      scoreColor: "text-emerald-700 dark:text-emerald-300",
    };
  }
  if (score >= 30) {
    return {
      band: "good",
      badge: "İyi",
      container: "border-emerald-400/40 bg-gradient-to-br from-emerald-50/60 to-white dark:from-emerald-950/20 dark:to-zinc-900",
      scoreColor: "text-emerald-600 dark:text-emerald-300",
    };
  }
  if (score >= 0) {
    return {
      band: "watch",
      badge: "Dikkat",
      container: "border-amber-400/50 bg-gradient-to-br from-amber-50 to-white dark:from-amber-950/30 dark:to-zinc-900",
      scoreColor: "text-amber-700 dark:text-amber-300",
    };
  }
  if (score >= -50) {
    return {
      band: "risk",
      badge: "Riskli",
      container: "border-orange-400/50 bg-gradient-to-br from-orange-50 to-white dark:from-orange-950/30 dark:to-zinc-900",
      scoreColor: "text-orange-700 dark:text-orange-300",
    };
  }
  return {
    band: "critical",
    badge: "Kritik",
    container: "border-red-500/60 bg-gradient-to-br from-red-50 to-white dark:from-red-950/30 dark:to-zinc-900",
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
): string {
  if (nps === null && total === 0) {
    return "Henüz analiz edilmiş yorum yok. Toplu yükleme ile başlayın.";
  }
  if (total > 0 && crisis / total > 0.1) {
    return "Kriz hacmi yüksek — son dönemde negatif sinyaller yoğunlaşıyor, dikkat gerekli.";
  }
  if (nps !== null && nps < -30) {
    return "Genel his belirgin biçimde negatif — yönetim aksiyonu değerlendirin.";
  }
  if (nps !== null && nps < 0) {
    return "Genel his hafif negatif — eğilim tersine dönmeden ele alın.";
  }
  if (avgSentiment !== null && avgSentiment < -0.3) {
    return "Ortalama duygu negatif tarafa eğilimli.";
  }
  if (nps !== null && nps >= 30) {
    return "Genel seyir iyi — kritik bir sinyal yok.";
  }
  return "Genel seyir dengeli — periyodik takip yeterli.";
}

interface DeltaInfo {
  delta: number | null;
  label: string;
}

function computeNpsDelta(
  monthlyTrend: ReadonlyArray<{ score: number | null }> | undefined,
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
  return { delta, label: `önceki aya göre ${delta > 0 ? "+" : ""}${delta.toFixed(0)}` };
}

export function HealthHero() {
  const headline = useHeadlineMetrics({});
  const trend = useNpsMonthlyTrend(12);

  if (headline.isLoading) return <Skeleton className="h-44 w-full" />;
  if (headline.isError) {
    return (
      <div className="border-destructive/30 bg-destructive/5 flex items-center gap-3 rounded-xl border p-6">
        <AlertTriangle className="text-destructive size-5" aria-hidden />
        <div className="text-sm">
          <p className="font-medium">CX Sağlık verisi alınamadı.</p>
          <p className="text-muted-foreground">
            API erişimi yeniden kurulduğunda otomatik yenilenir.
          </p>
        </div>
      </div>
    );
  }

  const data = headline.data;
  const score = data?.nps_score ?? null;
  const visual = healthFromNps(score);
  const text = narrative(
    score,
    data?.crisis_count ?? 0,
    data?.total_reviews ?? 0,
    data?.avg_sentiment_score ?? null,
  );
  const delta = computeNpsDelta(trend.data);

  return (
    <section
      className={`rounded-xl border p-6 md:p-8 transition-colors ${visual.container}`}
      aria-label="CX Sağlık"
    >
      <div className="flex flex-wrap items-start gap-x-8 gap-y-4">
        <div className="flex-1 min-w-[12rem]">
          <p className="text-muted-foreground text-xs font-medium uppercase tracking-wider">
            CX Sağlık · Son 30 gün
          </p>
          <div className="mt-2 flex items-baseline gap-3">
            <span className={`text-5xl md:text-6xl font-semibold tabular-nums ${visual.scoreColor}`}>
              {formatScore(score)}
            </span>
            <span className={`text-sm font-medium ${visual.scoreColor}`}>
              {visual.badge}
            </span>
            {delta.delta !== null && (
              <DeltaPill delta={delta.delta} label={delta.label} />
            )}
          </div>
          <p className="text-foreground/80 mt-3 text-sm md:text-base max-w-2xl">
            {text}
          </p>
        </div>

        <div className="flex flex-col gap-2 text-xs text-muted-foreground min-w-[10rem]">
          <CoverageRow
            label="Toplam yorum"
            value={(data?.total_reviews ?? 0).toLocaleString("tr-TR")}
          />
          <CoverageRow
            label="NPS kapsama"
            value={`%${(data?.nps_coverage_percent ?? 0).toFixed(0)}`}
          />
          <CoverageRow
            label="Kriz adedi"
            value={(data?.crisis_count ?? 0).toLocaleString("tr-TR")}
          />
          <CoverageRow
            label="Açık ticket"
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
    <div className="flex items-center justify-between gap-3">
      <span>{label}</span>
      <span className="text-foreground font-medium tabular-nums">{value}</span>
    </div>
  );
}
