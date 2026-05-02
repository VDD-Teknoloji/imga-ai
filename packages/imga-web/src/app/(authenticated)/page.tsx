"use client";

import { CategoryChart } from "@/components/dashboard/category-chart";
import { CategorySentimentMiniHeatmap } from "@/components/dashboard/category-sentiment-mini-heatmap";
import { MetricCards } from "@/components/dashboard/metric-cards";
import { RecentTicketsTable } from "@/components/dashboard/recent-tickets";
import { SentimentDonut } from "@/components/dashboard/sentiment-donut";
import { SentimentTrend } from "@/components/dashboard/sentiment-trend";
import { useAuthStore } from "@/lib/auth-store";

/**
 * Tenant dashboard. Sprint 8.3.4 expanded the analytics layer:
 *
 *   1. Header     — greeting + active tenant name
 *   2. Metric grid — four ticket-derived counts
 *   3. Analytics row — sentiment donut + category bar (existing)
 *   4. Trend row — last 30 days sentiment line chart (full width)
 *   5. Heatmap row — category × sentiment mini matrix (full width)
 *   6. Recent tickets — full-width table
 */
export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);
  const activeContext = useAuthStore((s) => s.activeContext);

  const tenantName = activeContext?.tenant_name ?? "Aktif tenant yok";

  return (
    <main className="mx-auto w-full max-w-7xl space-y-6 p-6 md:p-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
          Merhaba{user?.full_name ? `, ${user.full_name.split(" ")[0]}` : ""}
        </h1>
        <p className="text-muted-foreground text-sm">{tenantName}</p>
      </header>

      <MetricCards />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <SentimentDonut />
        <CategoryChart />
      </div>

      <SentimentTrend />

      <CategorySentimentMiniHeatmap />

      <RecentTicketsTable />
    </main>
  );
}
