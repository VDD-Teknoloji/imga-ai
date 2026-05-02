"use client";

// Sprint 8.3.4 dashboard widget — last 30 days sentiment timeline.
// Three series (NEGATIF / NÖTR / POZITIF) over day-grouped buckets.

import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Skeleton } from "@/components/ui/skeleton";
import { useSentimentTimeline } from "@/hooks/use-analytics";

function formatYmd(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function SentimentTrend() {
  // Last 30 days, anchored on local midnight so the API call lines
  // up with the user's timezone (use-analytics expands YYYY-MM-DD →
  // local midnight ISO before hitting the backend).
  const range = useMemo(() => {
    const today = new Date();
    const start = new Date(today);
    start.setDate(start.getDate() - 29);
    return { date_from: formatYmd(start), date_to: formatYmd(today) };
  }, []);
  const tl = useSentimentTimeline(range, "day");

  return (
    <section className="bg-card rounded-lg border p-5">
      <header className="mb-4 flex items-baseline justify-between">
        <h2 className="text-base font-semibold tracking-tight">
          Son 30 gün duygu trendi
        </h2>
        <p className="text-muted-foreground text-xs">Günlük bazda</p>
      </header>
      {tl.isLoading ? (
        <Skeleton className="h-[260px]" />
      ) : tl.isError ? (
        <p className="text-destructive py-12 text-center text-sm">Veri yüklenemedi.</p>
      ) : !tl.data || tl.data.data.length === 0 ? (
        <p className="text-muted-foreground py-12 text-center text-sm">Veri yok.</p>
      ) : (
        <div className="h-[260px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={tl.data.data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis
                dataKey="date"
                tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
                stroke="var(--border)"
              />
              <YAxis
                allowDecimals={false}
                tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
                stroke="var(--border)"
              />
              <Tooltip
                contentStyle={{
                  background: "var(--popover)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              <Line
                type="monotone"
                dataKey="negatif"
                stroke="#dc2626"
                strokeWidth={2}
                dot={false}
                name="Negatif"
              />
              <Line
                type="monotone"
                dataKey="nötr"
                stroke="#737373"
                strokeWidth={2}
                dot={false}
                name="Nötr"
              />
              <Line
                type="monotone"
                dataKey="pozitif"
                stroke="#16a34a"
                strokeWidth={2}
                dot={false}
                name="Pozitif"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
