"use client";

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { TicketState } from "@/lib/types";

export interface TicketTransition {
  id: string;
  from_state: TicketState;
  to_state: TicketState;
  actor_user_id: string | null;
  reason: string | null;
  occurred_at: string;
}

interface TransitionsResponse {
  transitions: TicketTransition[];
}

export function useTicketTimeline(ticketId: string | undefined) {
  return useQuery({
    queryKey: ["tickets", "timeline", ticketId],
    queryFn: async () => {
      const data = await apiRequest<TransitionsResponse>(
        `/tickets/${ticketId}/transitions`,
      );
      return data.transitions;
    },
    enabled: typeof ticketId === "string" && ticketId.length > 0,
  });
}
