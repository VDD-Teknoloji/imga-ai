"use client";

import { CalendarPlus, CircleAlert, Inbox, ShieldCheck } from "lucide-react";

import { MetricCard } from "@/components/dashboard/metric-card";
import {
  useHighPriorityTicketsCount,
  useOpenTicketsCount,
  useRecentlyResolvedTicketsCount,
  useTodayOpenedTicketsCount,
} from "@/hooks/use-tickets";
import { useTranslation } from "@/lib/i18n/use-translation";

/**
 * Four card grid. Each card subscribes to its own selector hook so
 * loading / error states render independently. Underneath, all four
 * hooks share a single GET /tickets fetch (TanStack Query dedupes).
 *
 * Card mapping (Sprint 7.6.3 — ticket-derived metrics, since the
 * /analyze→ticket bridge that would feed SHI / crisis is still an
 * A3 backlog item):
 *
 *   1. Açık                — open + in_progress + pending_customer
 *   2. Bugün Açılan        — opened_at >= today 00:00
 *   3. Yüksek Öncelik      — priority high|urgent, non-terminal
 *   4. Son 7 Gün Çözülen   — resolved|closed in the last 7 days
 */
export function MetricCards() {
  const { t } = useTranslation();
  const open = useOpenTicketsCount();
  const today = useTodayOpenedTicketsCount();
  const highPriority = useHighPriorityTicketsCount();
  const resolved = useRecentlyResolvedTicketsCount();

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
      <MetricCard
        title={t("dashboard.metricCards.openTickets")}
        hint={t("dashboard.metricCards.openTicketsHint")}
        value={open.data}
        isLoading={open.isLoading}
        isError={open.isError}
        icon={Inbox}
        iconClassName="text-primary size-4"
      />
      <MetricCard
        title={t("dashboard.metricCards.openedToday")}
        hint={t("dashboard.metricCards.openedTodayHint")}
        value={today.data}
        isLoading={today.isLoading}
        isError={today.isError}
        icon={CalendarPlus}
      />
      <MetricCard
        title={t("dashboard.metricCards.highPriority")}
        hint={t("dashboard.metricCards.highPriorityHint")}
        value={highPriority.data}
        isLoading={highPriority.isLoading}
        isError={highPriority.isError}
        icon={CircleAlert}
        iconClassName="text-destructive size-4"
      />
      <MetricCard
        title={t("dashboard.metricCards.resolved7d")}
        hint={t("dashboard.metricCards.resolved7dHint")}
        value={resolved.data}
        isLoading={resolved.isLoading}
        isError={resolved.isError}
        icon={ShieldCheck}
        iconClassName="text-emerald-600 size-4"
      />
    </div>
  );
}
