"use client";

// Sprint 9.6 redesign — C-level landing page.
//
// Tear-down of the Sprint 8.3.5.6 7-card grid + donut + bar +
// 30-day trend + mini heatmap stack. C-level operators don't want
// a wall of charts; they want one big signal at the top + the 3-4
// actions they actually take.
//
// New shape, top to bottom:
//
//   1. Greeting + tenant name (minimal header).
//   2. HealthHero — one giant NPS-band card + plain Turkish
//      narrative + data-coverage chips.
//   3. QuickActions — 4 prominent tiles (Yeni yükleme, Brifing
//      üret, Aksiyonlar, Strateji raporu). Same 4 actions also
//      live in the universal FAB so they're reachable from every
//      route — multi-entry pattern, like the iPhone camera on
//      lock screen + control center + apps.
//   4. NpsMonthlyTrend + AttentionList side by side — trend gives
//      direction, AttentionList answers "what needs fixing right
//      now" (replaces SentimentDonut + CategoryChart raw-count
//      visuals).
//   5. KpiGoalCards — per-tenant goal progress (unchanged).
//   6. RecentTicketsTable — last few tickets (kept).
//
// Dropped: HeadlineMetricsCards 6-card grid (rolled into hero),
// SentimentDonut, CategoryChart, SentimentTrend (30-day),
// CategorySentimentMiniHeatmap. These live on /insights for the
// analyst persona; the dashboard doesn't need them.

import { AttentionList } from "@/components/dashboard/attention-list";
import { ClassificationQualityChip } from "@/components/dashboard/classification-quality-chip";
import { HealthHero } from "@/components/dashboard/health-hero";
import { KpiGoalCards } from "@/components/dashboard/KpiGoalCards";
import { NpsMonthlyTrend } from "@/components/dashboard/nps-monthly-trend";
import { QuickActions } from "@/components/dashboard/quick-actions";
import { RecentTicketsTable } from "@/components/dashboard/recent-tickets";
import { useAuthStore } from "@/lib/auth-store";

export default function DashboardPage() {
  const user = useAuthStore((s) => s.user);
  const activeContext = useAuthStore((s) => s.activeContext);

  const tenantName = activeContext?.tenant_name ?? "Aktif tenant yok";
  const firstName = user?.full_name?.split(" ")[0] ?? "";

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-6 md:p-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">
          {firstName ? `Merhaba, ${firstName}` : "Merhaba"}
        </h1>
        <p className="text-muted-foreground text-sm">{tenantName}</p>
      </header>

      <HealthHero />

      {/* Sprint 9.9 — Madde 1 (UML feedback): operatöre belirsiz oran
          uyarısı. Iyi durumdaysa veya hiç veri yoksa kendini
          gizliyor, dashboard'a yer kaplamıyor. */}
      <ClassificationQualityChip />

      <QuickActions />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <NpsMonthlyTrend />
        </div>
        <AttentionList />
      </div>

      <KpiGoalCards />

      <RecentTicketsTable />
    </main>
  );
}
