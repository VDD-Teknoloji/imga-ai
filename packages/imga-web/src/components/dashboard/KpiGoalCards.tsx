// Sprint 9.2 B — Dashboard "Hedefler" section.
//
// Renders one card per active KPI goal with the achievement bar +
// "yolda / risk altında / hedefin altında" label. Empty state
// surfaces a CTA to /settings/kpi-goals so the operator can set
// their first goal in two clicks.

"use client";

import { Target } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import {
  type KpiGoalProgress,
  useKpiGoalProgressBulk,
} from "@/hooks/use-kpi-goals";
import {
  formatMetricValue,
  type MetricDefinition,
  useMetricDefinitions,
} from "@/hooks/use-metric-definitions";
import { useTranslation } from "@/lib/i18n/use-translation";
import { cn } from "@/lib/utils";

export function KpiGoalCards() {
  const { t } = useTranslation();
  const goals = useKpiGoalProgressBulk();
  const metrics = useMetricDefinitions();

  if (goals.isLoading) {
    return null; // dashboard already has its own skeleton
  }
  if (goals.isError) {
    return null;
  }
  const items = goals.data ?? [];
  if (items.length === 0) {
    return (
      <Card className="border-dashed">
        <CardContent className="flex flex-wrap items-center gap-3 p-4">
          <Target className="text-muted-foreground size-5" aria-hidden />
          <p className="text-muted-foreground flex-1 text-sm">
            {t("dashboard.kpiGoals.empty")}
          </p>
          <Link
            href="/settings/kpi-goals"
            className="text-primary text-sm font-medium hover:underline"
          >
            {t("dashboard.kpiGoals.addGoal")} →
          </Link>
        </CardContent>
      </Card>
    );
  }

  return (
    <section className="space-y-3">
      <header className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold tracking-tight">
          {t("dashboard.kpiGoals.title")}
        </h2>
        <Link
          href="/settings/kpi-goals"
          className="text-muted-foreground hover:text-foreground text-xs"
        >
          {t("dashboard.kpiGoals.edit")} →
        </Link>
      </header>
      <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {items.map((g) => (
          <GoalCard
            key={`${g.metric_key}-${g.period_start}`}
            progress={g}
            metric={metrics.data?.find((m) => m.metric_key === g.metric_key)}
          />
        ))}
      </div>
    </section>
  );
}

function GoalCard({
  progress: g,
  metric,
}: {
  progress: KpiGoalProgress;
  metric?: MetricDefinition;
}) {
  const { t } = useTranslation();
  const tone =
    g.achievement_pct === null
      ? "border-zinc-300"
      : g.on_track
      ? "border-emerald-400"
      : g.achievement_pct >= 70
      ? "border-amber-400"
      : "border-red-400";
  const stateLabel =
    g.achievement_pct === null
      ? t("dashboard.kpiGoals.state.noData")
      : g.on_track
      ? t("dashboard.kpiGoals.state.onTrack")
      : g.achievement_pct >= 70
      ? t("dashboard.kpiGoals.state.atRisk")
      : t("dashboard.kpiGoals.state.belowTarget");
  const stateClass =
    g.achievement_pct === null
      ? "bg-zinc-100 text-zinc-700"
      : g.on_track
      ? "bg-emerald-100 text-emerald-800"
      : g.achievement_pct >= 70
      ? "bg-amber-100 text-amber-900"
      : "bg-red-100 text-red-800";

  return (
    <Card className={cn("border-2", tone)}>
      <CardContent className="space-y-2 p-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-semibold">
              {metric?.display_name ?? g.metric_key}
            </p>
            <p className="text-muted-foreground text-xs">
              {g.target_period} · {g.period_start} → {g.period_end}
            </p>
          </div>
          <Badge className={cn("text-[10px] uppercase", stateClass)}>
            {stateLabel}
          </Badge>
        </div>
        <div className="flex items-baseline justify-between gap-2 text-sm">
          <span>
            <strong className="text-lg">
              {g.current_value !== null
                ? formatMetricValue(g.current_value, metric)
                : "—"}
            </strong>
            <span className="text-muted-foreground"> / </span>
            <span className="text-muted-foreground">
              {formatMetricValue(g.target_value, metric)}
            </span>
          </span>
          {g.achievement_pct !== null && (
            <span className="text-muted-foreground text-xs tabular-nums">
              %{g.achievement_pct.toFixed(0)}
            </span>
          )}
        </div>
        {g.achievement_pct !== null && (
          <div className="bg-muted h-1.5 overflow-hidden rounded-full">
            <div
              className={cn(
                "h-full transition-all",
                g.on_track
                  ? "bg-emerald-500"
                  : g.achievement_pct >= 70
                  ? "bg-amber-500"
                  : "bg-red-500",
              )}
              style={{
                width: `${Math.min(g.achievement_pct, 100)}%`,
              }}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}
