"use client";

// Sprint 8.3.5 dashboard widget — last 12 months NPS line.
//
// connectNulls={false} is the load-bearing config: months without any
// NPS-bearing review come back as score=null. Connecting through them
// would draw a fake line; leaving the gap is the truthful read.

import { useMemo } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { Skeleton } from "@/components/ui/skeleton";
import { useNpsMonthlyTrend } from "@/hooks/use-analytics";

const TR_MONTHS = [
  "Oca",
  "Şub",
  "Mar",
  "Nis",
  "May",
  "Haz",
  "Tem",
  "Ağu",
  "Eyl",
  "Eki",
  "Kas",
  "Ara",
];

function formatMonth(iso: string): string {
  // ISO date — "2025-06-01". Avoid Date() to dodge timezone drift.
  const m = iso.match(/^(\d{4})-(\d{2})/);
  if (!m) return iso;
  const monthIdx = Math.max(0, Math.min(11, Number(m[2]) - 1));
  return `${TR_MONTHS[monthIdx] ?? ""} ${(m[1] ?? "").slice(2)}`;
}

export function NpsMonthlyTrend() {
  const { data, isLoading, isError } = useNpsMonthlyTrend(12);

  const chartData = useMemo(
    () =>
      (data ?? []).map((p) => ({
        ...p,
        label: formatMonth(p.month),
      })),
    [data],
  );

  return (
    <section className="bg-card rounded-lg border p-5">
      <header className="mb-4 flex items-baseline justify-between">
        <h2 className="text-base font-semibold tracking-tight">Son 12 ay NPS trendi</h2>
        <p className="text-muted-foreground text-xs">
          Aylık · veri olmayan aylar boşluk olarak görünür
        </p>
      </header>
      {isLoading ? (
        <Skeleton className="h-[260px]" />
      ) : isError ? (
        <p className="text-destructive py-12 text-center text-sm">Veri yüklenemedi.</p>
      ) : chartData.length === 0 ? (
        <p className="text-muted-foreground py-12 text-center text-sm">Veri yok.</p>
      ) : (
        <div className="h-[260px] w-full">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis
                dataKey="label"
                tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
                stroke="var(--border)"
              />
              <YAxis
                domain={[-100, 100]}
                ticks={[-100, -50, 0, 50, 100]}
                tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
                stroke="var(--border)"
              />
              <ReferenceLine y={0} stroke="var(--muted-foreground)" strokeDasharray="2 4" />
              <Tooltip
                contentStyle={{
                  background: "var(--popover)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                formatter={(value) =>
                  value === null || value === undefined ? "veri yok" : String(value)
                }
              />
              <Line
                type="monotone"
                dataKey="score"
                stroke="#2563eb"
                strokeWidth={2.5}
                dot={{ r: 3 }}
                connectNulls={false}
                name="NPS"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
