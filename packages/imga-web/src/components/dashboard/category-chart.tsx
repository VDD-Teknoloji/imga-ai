"use client";

import { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Skeleton } from "@/components/ui/skeleton";
import { useCategoryDistribution } from "@/hooks/use-tickets";
import { useTranslation } from "@/lib/i18n/use-translation";

/**
 * Top categories by ticket count.
 *
 * Colours come from the shadcn theme variables (--chart-1 .. --chart-5)
 * resolved through Tailwind 4 CSS vars — the chart palette stays
 * consistent with the rest of the app (warm neutral + teal primary).
 *
 * Empty / loading / error states are explicit:
 *   - Loading: skeleton bars (no chart at all to avoid Recharts
 *     animating from undefined data).
 *   - Error: muted "Veri yüklenemedi" line.
 *   - Empty (zero tickets): "Veri yok" placeholder.
 */
const CHART_COLOR_VARS = ["--chart-1", "--chart-2", "--chart-3", "--chart-4", "--chart-5"] as const;

interface ChartDatum {
  name: string;
  count: number;
}

export function CategoryChart() {
  const { t } = useTranslation();
  const distribution = useCategoryDistribution();

  // /tickets/stats?group_by=category already LEFT-JOINs the categories
  // label, so the bucket comes back with a ready-to-render label —
  // no useCategoryLabelMap merge needed (Sprint 7.7.1).
  const data = useMemo<ChartDatum[]>(() => {
    if (!distribution.data) return [];
    return distribution.data.slice(0, 5).map((entry) => ({
      name: entry.label,
      count: entry.count,
    }));
  }, [distribution.data]);

  const isLoading = distribution.isLoading;
  const isError = distribution.isError;

  return (
    <section className="bg-card rounded-lg border p-5">
      <header className="mb-4 flex items-baseline justify-between">
        <h2 className="text-base font-semibold tracking-tight">
          {t("dashboard.categoryChart.title")}
        </h2>
        <p className="text-muted-foreground text-xs">
          {t("dashboard.common.top5Categories")}
        </p>
      </header>

      {isLoading ? (
        <SkeletonChart />
      ) : isError ? (
        <p className="text-destructive py-12 text-center text-sm">
          {t("dashboard.common.loadFailed")}
        </p>
      ) : data.length === 0 ? (
        <p className="text-muted-foreground py-12 text-center text-sm">
          {t("dashboard.common.noData")}
        </p>
      ) : (
        <div className="h-[260px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis
                dataKey="name"
                tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
                stroke="var(--border)"
              />
              <YAxis
                allowDecimals={false}
                tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
                stroke="var(--border)"
              />
              <Tooltip
                contentStyle={{
                  background: "var(--popover)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  color: "var(--popover-foreground)",
                  fontSize: 12,
                }}
                cursor={{ fill: "var(--muted)", opacity: 0.5 }}
              />
              <Bar dataKey="count" radius={[6, 6, 0, 0]}>
                {data.map((_, index) => (
                  <Cell
                    key={index}
                    fill={`var(${CHART_COLOR_VARS[index % CHART_COLOR_VARS.length]})`}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}

function SkeletonChart() {
  return (
    <div className="flex h-[260px] items-end gap-3 px-2">
      {[60, 100, 80, 50, 40].map((h, i) => (
        <Skeleton key={i} className="flex-1" style={{ height: `${h}%` }} />
      ))}
    </div>
  );
}
