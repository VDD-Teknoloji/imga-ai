"use client";

import { CategoryChart } from "@/components/dashboard/category-chart";
import { MetricCards } from "@/components/dashboard/metric-cards";
import { RecentTicketsTable } from "@/components/dashboard/recent-tickets";
import { useAuthStore } from "@/lib/auth-store";

/**
 * Tenant dashboard. Three blocks:
 *
 *   1. Header     — greeting + active tenant name
 *   2. Metric grid — four ticket-derived counts (Sprint 7.6.3 mapping;
 *      SHI / crisis cards land in 7.5.5/8 once analyze→ticket bridge ships)
 *   3. Two-column body — category distribution chart + recent tickets table
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
        <CategoryChart />
        <RecentTicketsTable />
      </div>
    </main>
  );
}
