"use client";

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import {
  ACTIVE_TICKET_STATES,
  HIGH_PRIORITIES,
  TERMINAL_TICKET_STATES,
} from "@/lib/ticket-helpers";
import type { Ticket, TicketListResponse } from "@/lib/types";

/**
 * Single underlying GET /tickets fetch.
 *
 * Sprint 7.6.3 dashboard ships four card-level hooks plus a list
 * hook plus a category-distribution hook, all of them sharing the
 * SAME queryKey `["tickets","all"]`. TanStack Query dedupes the
 * network call so the dashboard fires one HTTP request, while each
 * consumer hook receives a tailored shape via `select`.
 *
 * Backend gap (logged in docs/post-sprint-7-roadmap.md A5): /tickets
 * doesn't yet support multi-state, date-range, or priority filters,
 * so all aggregations are computed client-side. When `GET /tickets/stats`
 * lands, each hook below collapses to a thin fetch of its own
 * pre-aggregated count.
 */

const TICKETS_QUERY_KEY = ["tickets", "all"] as const;

async function fetchAllTickets(): Promise<Ticket[]> {
  const data = await apiRequest<TicketListResponse>("/tickets");
  return data.tickets;
}

function isToday(iso: string): boolean {
  const opened = new Date(iso);
  const now = new Date();
  return (
    opened.getFullYear() === now.getFullYear() &&
    opened.getMonth() === now.getMonth() &&
    opened.getDate() === now.getDate()
  );
}

function isWithinLast7d(iso: string | null): boolean {
  if (iso === null) return false;
  const ts = new Date(iso).getTime();
  const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
  return ts >= cutoff;
}

// --- Card-level hooks (each is logically separate, all share cache) -

export function useOpenTicketsCount() {
  return useQuery({
    queryKey: TICKETS_QUERY_KEY,
    queryFn: fetchAllTickets,
    select: (tickets) => tickets.filter((t) => ACTIVE_TICKET_STATES.includes(t.state)).length,
  });
}

export function useTodayOpenedTicketsCount() {
  return useQuery({
    queryKey: TICKETS_QUERY_KEY,
    queryFn: fetchAllTickets,
    select: (tickets) => tickets.filter((t) => isToday(t.opened_at)).length,
  });
}

export function useHighPriorityTicketsCount() {
  return useQuery({
    queryKey: TICKETS_QUERY_KEY,
    queryFn: fetchAllTickets,
    select: (tickets) =>
      tickets.filter(
        (t) =>
          HIGH_PRIORITIES.includes(t.priority) &&
          !TERMINAL_TICKET_STATES.includes(t.state),
      ).length,
  });
}

export function useRecentlyResolvedTicketsCount() {
  return useQuery({
    queryKey: TICKETS_QUERY_KEY,
    queryFn: fetchAllTickets,
    select: (tickets) =>
      tickets.filter((t) => t.state === "resolved" || t.state === "closed")
        .filter((t) => isWithinLast7d(t.closed_at) || isWithinLast7d(t.resolved_at)).length,
  });
}

// --- List + chart hooks -----------------------------------------------

/** Default-sorted (last_state_change_at desc — backend's default). */
export function useTicketsList() {
  return useQuery({
    queryKey: TICKETS_QUERY_KEY,
    queryFn: fetchAllTickets,
  });
}

export interface CategoryDistributionEntry {
  categoryId: string;
  count: number;
}

/**
 * Group tickets by category_id, return [{categoryId, count}].
 * Sorted by count desc so the chart's tallest bar is leftmost.
 */
export function useCategoryDistribution() {
  return useQuery({
    queryKey: TICKETS_QUERY_KEY,
    queryFn: fetchAllTickets,
    select: (tickets): CategoryDistributionEntry[] => {
      const counts = new Map<string, number>();
      for (const ticket of tickets) {
        counts.set(ticket.category_id, (counts.get(ticket.category_id) ?? 0) + 1);
      }
      return Array.from(counts.entries())
        .map(([categoryId, count]) => ({ categoryId, count }))
        .sort((a, b) => b.count - a.count);
    },
  });
}
