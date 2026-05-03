"use client";

import { CategoryChart } from "@/components/dashboard/category-chart";
import { CategorySentimentMiniHeatmap } from "@/components/dashboard/category-sentiment-mini-heatmap";
import { HeadlineMetricsCards } from "@/components/dashboard/headline-metrics-cards";
import { NpsMonthlyTrend } from "@/components/dashboard/nps-monthly-trend";
import { RecentTicketsTable } from "@/components/dashboard/recent-tickets";
import { SentimentDonut } from "@/components/dashboard/sentiment-donut";
import { SentimentTrend } from "@/components/dashboard/sentiment-trend";
import { useAuthStore } from "@/lib/auth-store";

/**
 * Tenant dashboard. Sprint 8.3.5.6 expanded the headline row:
 *
 *   1. Header        — greeting + active tenant name
 *   2. Headline row  — NPS hero card + 6 support metrics (single
 *                      /headline-metrics round-trip)
 *   3. NPS trend     — 12-month line, gap-on-null
 *   4. Analytics row — sentiment donut + category bar
 *   5. Sentiment trend — 30-day line chart (full width)
 *   6. Heatmap row   — category × sentiment mini matrix (full width)
 *   7. Recent tickets — full-width table
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

      <HeadlineMetricsCards />

      <NpsMonthlyTrend />

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
