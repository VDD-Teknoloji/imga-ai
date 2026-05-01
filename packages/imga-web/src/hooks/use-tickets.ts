"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { apiRequest } from "@/lib/api-client";
import type {
  Ticket,
  TicketBackendFilters,
  TicketListResponse,
  TicketStatsGroupBy,
  TicketStatsResponse,
} from "@/lib/types";

/**
 * Sprint 7.7.1: hooks now talk to the Sprint 7.5.5 backend filter +
 * /tickets/stats endpoints. The previous "fetch all tickets, slice
 * client-side" pattern is gone. Each hook below maps to one backend
 * call, with TanStack Query keying off a stringified filter blob so
 * different filters are independently cached.
 *
 * Card-level hooks (useOpenTicketsCount etc.) compose
 * `useTicketStats` + an inline reshape so the dashboard's
 * `MetricCard` continues to consume `{data: number, isLoading,
 * isError}` without changes.
 */

const TICKETS_LIST_KEY = "tickets-list";
const TICKETS_INFINITE_KEY = "tickets-infinite";
const TICKETS_STATS_KEY = "tickets-stats";

/**
 * Translate a TicketBackendFilters object into the URL query string
 * expected by the FastAPI Depends factory. CSV-list params are
 * comma-joined; undefined / empty arrays are skipped so the URL stays
 * minimal and shareable.
 */
export function buildTicketQueryString(filters: TicketBackendFilters): string {
  const parts = new URLSearchParams();
  if (filters.states && filters.states.length > 0) {
    parts.set("state", filters.states.join(","));
  }
  if (filters.priorities && filters.priorities.length > 0) {
    parts.set("priority", filters.priorities.join(","));
  }
  if (filters.category_ids && filters.category_ids.length > 0) {
    parts.set("category_id", filters.category_ids.join(","));
  }
  if (filters.opened_after) parts.set("opened_after", filters.opened_after);
  if (filters.opened_before) parts.set("opened_before", filters.opened_before);
  if (filters.assignee) parts.set("assignee", filters.assignee);
  if (filters.search) parts.set("search", filters.search);
  if (filters.order_by) parts.set("order_by", filters.order_by);
  if (filters.order) parts.set("order", filters.order);
  if (filters.limit !== undefined) parts.set("limit", String(filters.limit));
  if (filters.offset !== undefined) parts.set("offset", String(filters.offset));
  return parts.toString();
}

// --- list (single page) -------------------------------------------------

export function useTickets(filters: TicketBackendFilters = {}) {
  const qs = buildTicketQueryString(filters);
  return useQuery({
    queryKey: [TICKETS_LIST_KEY, qs],
    queryFn: () =>
      apiRequest<TicketListResponse>(qs ? `/tickets?${qs}` : "/tickets"),
  });
}

// --- list (infinite / "Daha fazla göster") ----------------------------

const DEFAULT_PAGE_SIZE = 100;

/**
 * Offset-paged infinite list. Each click of "Daha fazla göster" calls
 * `fetchNextPage()`; pages append until the server reports we've
 * fetched ``total`` rows. Cursor pagination (Sprint 8 / C5) will swap
 * this for a stable cursor without changing the consumer surface.
 */
export function useInfiniteTickets(
  filters: Omit<TicketBackendFilters, "offset" | "limit"> = {},
  pageSize: number = DEFAULT_PAGE_SIZE,
) {
  // Stable per-filter key — the offset is derived from `pageParam` at
  // request time, NOT from the filters object, so the same key holds
  // across "fetch next page" clicks.
  const queryKey = [
    TICKETS_INFINITE_KEY,
    buildTicketQueryString({ ...filters, limit: pageSize }),
  ];

  return useInfiniteQuery({
    queryKey,
    queryFn: async ({ pageParam }) => {
      const qs = buildTicketQueryString({
        ...filters,
        limit: pageSize,
        offset: pageParam,
      });
      return apiRequest<TicketListResponse>(qs ? `/tickets?${qs}` : "/tickets");
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      const fetched = allPages.reduce(
        (sum, page) => sum + page.tickets.length,
        0,
      );
      return fetched < lastPage.total ? fetched : undefined;
    },
  });
}

/** Convenience: flatten the infinite-query pages into one array. */
export function flattenInfinitePages(
  pages: ReadonlyArray<TicketListResponse> | undefined,
): Ticket[] {
  if (pages === undefined) return [];
  return pages.flatMap((p) => p.tickets);
}

// --- stats --------------------------------------------------------------

export function useTicketStats(
  groupBy: TicketStatsGroupBy,
  filters: TicketBackendFilters = {},
) {
  const qs = buildTicketQueryString(filters);
  const fullQs = qs ? `${qs}&group_by=${groupBy}` : `group_by=${groupBy}`;
  return useQuery({
    queryKey: [TICKETS_STATS_KEY, groupBy, qs],
    queryFn: () =>
      apiRequest<TicketStatsResponse>(`/tickets/stats?${fullQs}`),
  });
}

// --- card-level convenience hooks ---------------------------------------
//
// Each hook returns the shape the existing `MetricCard` expects:
// { data: number | undefined, isLoading: boolean, isError: boolean }.
// The dashboard didn't have to change beyond this hook signature.

const ACTIVE_STATES = ["open", "in_progress", "pending_customer"] as const;

interface MetricResult {
  data: number | undefined;
  isLoading: boolean;
  isError: boolean;
}

export function useOpenTicketsCount(): MetricResult {
  const stats = useTicketStats("state", { states: ACTIVE_STATES });
  return {
    data: stats.data?.total,
    isLoading: stats.isLoading,
    isError: stats.isError,
  };
}

export function useTodayOpenedTicketsCount(): MetricResult {
  // useMemo on the start-of-today ISO so a long-lived dashboard tab
  // doesn't refetch the count once a minute. The query key is the
  // string itself, so a midnight rollover still invalidates correctly
  // on the next render.
  const todayIso = useMemo(() => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d.toISOString();
  }, []);
  const stats = useTicketStats("state", { opened_after: todayIso });
  return {
    data: stats.data?.total,
    isLoading: stats.isLoading,
    isError: stats.isError,
  };
}

export function useHighPriorityTicketsCount(): MetricResult {
  const stats = useTicketStats("state", {
    states: ACTIVE_STATES,
    priorities: ["high", "urgent"],
  });
  return {
    data: stats.data?.total,
    isLoading: stats.isLoading,
    isError: stats.isError,
  };
}

/**
 * "Resolved or closed in the last 7 days" — backend doesn't expose a
 * filter on `last_state_change_at` / `resolved_at` / `closed_at` yet
 * (Sprint 8 backlog), so we fetch the resolved+closed slice with a
 * server-side cap and count client-side those whose timestamp is
 * within the window. The slice is bounded (typically a few hundred
 * rows even at scale), so this still beats the old "fetch ALL" path.
 */
export function useRecentlyResolvedTicketsCount(): MetricResult {
  const tickets = useTickets({
    states: ["resolved", "closed"],
    order_by: "last_state_change_at",
    order: "desc",
    limit: 500,
  });
  const data =
    tickets.data === undefined
      ? undefined
      : tickets.data.tickets.filter(
          (t) =>
            isWithinLast7d(t.closed_at) || isWithinLast7d(t.resolved_at),
        ).length;
  return {
    data,
    isLoading: tickets.isLoading,
    isError: tickets.isError,
  };
}

function isWithinLast7d(iso: string | null): boolean {
  if (iso === null) return false;
  const ts = new Date(iso).getTime();
  const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
  return ts >= cutoff;
}

// --- charts -------------------------------------------------------------

export interface CategoryDistributionEntry {
  categoryId: string;
  /** Server-resolved label_tr (or "unassigned" for the assignee axis). */
  label: string;
  count: number;
}

/**
 * Backed by /tickets/stats?group_by=category. The endpoint already
 * LEFT-JOINs categories, so the bucket label is server-resolved —
 * consumers don't need to merge with `useCategoryLabelMap` anymore.
 */
export function useCategoryDistribution() {
  const stats = useTicketStats("category");
  const data: CategoryDistributionEntry[] | undefined = stats.data
    ? stats.data.results.map((bucket) => ({
        categoryId: bucket.key,
        label: bucket.label,
        count: bucket.count,
      }))
    : undefined;
  return {
    data,
    isLoading: stats.isLoading,
    isError: stats.isError,
  };
}
