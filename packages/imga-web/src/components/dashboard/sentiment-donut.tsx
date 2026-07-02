"use client";

// Sprint 8.3.4 dashboard widget — sentiment label distribution donut.
// Mirrors /insights' SentimentTab pie chart but compact (200px) and
// without filters; hits /tenants/me/analytics/sentiment-distribution
// with no filters → tenant-wide totals.

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { Skeleton } from "@/components/ui/skeleton";
import { useSentimentDistribution } from "@/hooks/use-analytics";
import { useTranslation } from "@/lib/i18n/use-translation";

const COLOURS: Record<string, string> = {
  NEGATIF: "#dc2626",
  NÖTR: "#737373",
  POZITIF: "#16a34a",
};

export function SentimentDonut() {
  const { t } = useTranslation();
  const dist = useSentimentDistribution({});

  return (
    <section className="bg-card rounded-lg border p-5">
      <header className="mb-4 flex items-baseline justify-between">
        <h2 className="text-base font-semibold tracking-tight">
          {t("dashboard.sentimentDonut.title")}
        </h2>
        <p className="text-muted-foreground text-xs">
          {t("dashboard.sentimentDonut.allTime")}
        </p>
      </header>
      {dist.isLoading ? (
        <Skeleton className="h-[220px]" />
      ) : dist.isError ? (
        <p className="text-destructive py-12 text-center text-sm">
          {t("dashboard.common.loadFailed")}
        </p>
      ) : !dist.data || dist.data.total === 0 ? (
        <p className="text-muted-foreground py-12 text-center text-sm">
          {t("dashboard.common.noData")}
        </p>
      ) : (
        <div className="h-[220px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={dist.data.data}
                dataKey="count"
                nameKey="label"
                innerRadius={50}
                outerRadius={88}
                label
              >
                {dist.data.data.map((row) => (
                  <Cell key={row.label} fill={COLOURS[row.label] ?? "#888"} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  background: "var(--popover)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
