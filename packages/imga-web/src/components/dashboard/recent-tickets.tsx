"use client";

import Link from "next/link";

import { TicketStateBadge } from "@/components/dashboard/ticket-state-badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useCategoryLabelMap } from "@/hooks/use-categories";
import { useTickets } from "@/hooks/use-tickets";
import { formatRelativeDate } from "@/lib/date-format";
import { useTranslation } from "@/lib/i18n/use-translation";

/**
 * Recent tickets table — first five rows of the tenant's ticket list,
 * default-sorted (last_state_change_at desc, set by the backend).
 *
 * Sprint 7.7.1: switched to backend `?limit=5` (Sprint 7.5.5 added
 * offset paging). The server total still flows through so the
 * "Tümünü gör" link could grow a counter later if we want.
 */
export function RecentTicketsTable() {
  const { t } = useTranslation();
  const tickets = useTickets({ limit: 5 });
  const labelMap = useCategoryLabelMap();

  const rows = tickets.data?.tickets ?? [];

  return (
    <section className="bg-card rounded-lg border p-5">
      <header className="mb-4 flex items-baseline justify-between">
        <h2 className="text-base font-semibold tracking-tight">
          {t("dashboard.recentTickets.title")}
        </h2>
        <Link
          href="/tickets"
          className="text-primary text-xs font-medium underline-offset-2 hover:underline"
        >
          {t("dashboard.recentTickets.seeAll")} →
        </Link>
      </header>

      {tickets.isLoading ? (
        <SkeletonRows />
      ) : tickets.isError ? (
        <p className="text-destructive py-8 text-center text-sm">
          {t("dashboard.common.loadFailed")}
        </p>
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground py-8 text-center text-sm">
          {t("dashboard.recentTickets.empty")}
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("dashboard.recentTickets.colTitle")}</TableHead>
              <TableHead className="hidden md:table-cell">
                {t("dashboard.recentTickets.colCategory")}
              </TableHead>
              <TableHead>{t("dashboard.recentTickets.colStatus")}</TableHead>
              <TableHead className="hidden lg:table-cell">
                {t("dashboard.recentTickets.colLastUpdate")}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((ticket) => (
              <TableRow key={ticket.id} className="cursor-pointer">
                <TableCell className="font-medium">
                  <Link
                    href={`/tickets/${ticket.id}`}
                    className="hover:text-primary block truncate"
                  >
                    {ticket.title}
                  </Link>
                </TableCell>
                <TableCell className="text-muted-foreground hidden md:table-cell">
                  {labelMap.data?.get(ticket.category_id) ?? "—"}
                </TableCell>
                <TableCell>
                  <TicketStateBadge state={ticket.state} />
                </TableCell>
                <TableCell className="text-muted-foreground hidden lg:table-cell">
                  {formatRelativeDate(ticket.last_state_change_at)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  );
}

function SkeletonRows() {
  return (
    <div className="space-y-3">
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className="flex items-center gap-4 py-2">
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="hidden h-4 w-20 md:block" />
          <Skeleton className="h-5 w-16" />
          <Skeleton className="hidden h-4 w-24 lg:block" />
        </div>
      ))}
    </div>
  );
}

