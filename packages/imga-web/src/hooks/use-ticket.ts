"use client";

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { Ticket } from "@/lib/types";

export function useTicket(ticketId: string | undefined) {
  return useQuery({
    queryKey: ["tickets", "detail", ticketId],
    queryFn: () => apiRequest<Ticket>(`/tickets/${ticketId}`),
    enabled: typeof ticketId === "string" && ticketId.length > 0,
  });
}
