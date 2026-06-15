"use client";

import { useMemo } from "react";

import {
  TicketFilters,
  useTicketFilters,
  type TicketFilterValues,
} from "@/components/tickets/ticket-filters";
import { TicketListTable } from "@/components/tickets/ticket-list-table";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useCategoryLabelMap } from "@/hooks/use-categories";
import { flattenInfinitePages, useInfiniteTickets } from "@/hooks/use-tickets";
import type {
  AssigneeFilterValue,
  TicketBackendFilters,
} from "@/lib/types";

const PAGE_SIZE = 100;

export default function TicketsListPage() {
  const filters = useTicketFilters();
  const backendFilters = useMemo(
    () => toBackendFilters(filters),
    [filters],
  );
  const tickets = useInfiniteTickets(backendFilters, PAGE_SIZE);
  const labelMap = useCategoryLabelMap();

  const rows = flattenInfinitePages(tickets.data?.pages);
  const total = tickets.data?.pages[0]?.total ?? 0;

  return (
    <main className="mx-auto w-full max-w-7xl space-y-4 p-6 md:p-8">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">Ticket&apos;lar</h1>
        <p className="text-muted-foreground text-sm">
          {tickets.isLoading
            ? "Yükleniyor..."
            : `${rows.length} Ticket gösteriliyor / toplam ${total}`}
        </p>
      </header>

      <TicketFilters filters={filters} />

      {tickets.isLoading ? (
        <SkeletonTable />
      ) : tickets.isError ? (
        <p className="text-destructive py-12 text-center text-sm">
          Ticket&apos;lar yüklenemedi.
        </p>
      ) : rows.length === 0 ? (
        <p className="text-muted-foreground py-12 text-center text-sm">
          {total === 0
            ? "Henüz ticket yok."
            : "Bu filtrelerle eşleşen ticket'ı yok."}
        </p>
      ) : (
        <>
          <TicketListTable
            tickets={rows}
            categoryLabelMap={labelMap.data ?? new Map()}
          />
          {tickets.hasNextPage ? (
            <div className="flex justify-center">
              <Button
                variant="outline"
                onClick={() => tickets.fetchNextPage()}
                disabled={tickets.isFetchingNextPage}
              >
                {tickets.isFetchingNextPage
                  ? "Yükleniyor..."
                  : `Daha fazla göster (${total - rows.length} kaldı)`}
              </Button>
            </div>
          ) : null}
        </>
      )}
    </main>
  );
}

/**
 * Translate the URL-derived filter Sets into the backend's array
 * shape. The "me" / "unassigned" / UUID disambiguation happens
 * server-side now (the JWT carries the user id), so we can pass
 * "me" through verbatim — the previous client-side `currentUserId`
 * lookup is gone.
 */
function toBackendFilters(filters: TicketFilterValues): TicketBackendFilters {
  const out: TicketBackendFilters = {};
  if (filters.states.size > 0) out.states = Array.from(filters.states);
  if (filters.priorities.size > 0) {
    out.priorities = Array.from(filters.priorities);
  }
  if (filters.categories.size > 0) {
    out.category_ids = Array.from(filters.categories);
  }
  if (filters.assignee !== "any") {
    out.assignee = filters.assignee as AssigneeFilterValue;
  }
  return out;
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
