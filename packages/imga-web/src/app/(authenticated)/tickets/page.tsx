"use client";

import { useMemo, useState } from "react";

import {
  TicketFilters,
  useTicketFilters,
  type TicketFilterValues,
} from "@/components/tickets/ticket-filters";
import { TicketListTable } from "@/components/tickets/ticket-list-table";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useCategoryLabelMap } from "@/hooks/use-categories";
import { useTicketsList } from "@/hooks/use-tickets";
import { useAuthStore } from "@/lib/auth-store";
import type { Ticket } from "@/lib/types";

const PAGE_SIZE = 100;

export default function TicketsListPage() {
  const filters = useTicketFilters();
  const tickets = useTicketsList();
  const labelMap = useCategoryLabelMap();
  const currentUserId = useAuthStore((s) => s.user?.id);

  const [displayLimit, setDisplayLimit] = useState(PAGE_SIZE);

  const filtered = useMemo(
    () => applyFilters(tickets.data ?? [], filters, currentUserId),
    [tickets.data, filters, currentUserId],
  );

  const visible = filtered.slice(0, displayLimit);
  const hasMore = filtered.length > displayLimit;

  return (
    <main className="mx-auto w-full max-w-7xl space-y-4 p-6 md:p-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">Ticket&apos;lar</h1>
        <p className="text-muted-foreground text-sm">
          {tickets.isLoading
            ? "Yükleniyor..."
            : `${filtered.length} ticket / toplam ${tickets.data?.length ?? 0}`}
        </p>
      </header>

      <TicketFilters filters={filters} />

      {tickets.isLoading ? (
        <SkeletonTable />
      ) : tickets.isError ? (
        <p className="text-destructive py-12 text-center text-sm">
          Ticket&apos;lar yüklenemedi.
        </p>
      ) : filtered.length === 0 ? (
        <p className="text-muted-foreground py-12 text-center text-sm">
          {tickets.data && tickets.data.length === 0
            ? "Henüz ticket yok."
            : "Bu filtrelerle eşleşen ticket'ı yok."}
        </p>
      ) : (
        <>
          <TicketListTable tickets={visible} categoryLabelMap={labelMap.data ?? new Map()} />
          {hasMore ? (
            <div className="flex justify-center">
              <Button
                variant="outline"
                onClick={() => setDisplayLimit((d) => d + PAGE_SIZE)}
              >
                Daha fazla göster ({filtered.length - displayLimit} kaldı)
              </Button>
            </div>
          ) : null}
        </>
      )}
    </main>
  );
}

function applyFilters(
  tickets: ReadonlyArray<Ticket>,
  filters: TicketFilterValues,
  currentUserId: string | undefined,
): Ticket[] {
  return tickets.filter((t) => {
    if (filters.states.size > 0 && !filters.states.has(t.state)) return false;
    if (filters.priorities.size > 0 && !filters.priorities.has(t.priority)) return false;
    if (filters.categories.size > 0 && !filters.categories.has(t.category_id)) return false;
    if (filters.assignee === "me") {
      if (currentUserId === undefined || t.assigned_to_user_id !== currentUserId) return false;
    } else if (filters.assignee === "unassigned") {
      if (t.assigned_to_user_id !== null) return false;
    }
    return true;
  });
}

function SkeletonTable() {
  return (
    <div className="space-y-2 rounded-lg border p-4">
      {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
        <div key={i} className="flex items-center gap-4 py-2">
          <Skeleton className="h-4 flex-1" />
          <Skeleton className="hidden h-4 w-24 md:block" />
          <Skeleton className="h-5 w-16" />
          <Skeleton className="hidden h-5 w-14 sm:block" />
          <Skeleton className="hidden h-4 w-20 lg:block" />
        </div>
      ))}
    </div>
  );
}
