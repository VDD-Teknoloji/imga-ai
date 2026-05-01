"use client";

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { TimelineEvent, TimelineResponse } from "@/lib/types";

/**
 * Sprint 7.7.2: switched from GET /tickets/{id}/transitions to the
 * polymorphic GET /tickets/{id}/timeline (Sprint 7.5.5 / Alt-Faz 4).
 * The endpoint merges state transitions and comments into a single
 * chronologically-sorted stream; consumers discriminate by ``type``.
 *
 * Existing /transitions endpoint is still around for backwards compat,
 * but no frontend code uses it after this commit.
 */
export type { TimelineEvent } from "@/lib/types";

export function useTicketTimeline(ticketId: string | undefined) {
  return useQuery({
    queryKey: ["tickets-timeline", ticketId],
    queryFn: async (): Promise<TimelineEvent[]> => {
      const data = await apiRequest<TimelineResponse>(
        `/tickets/${ticketId}/timeline`,
      );
      return data.events;
    },
    enabled: typeof ticketId === "string" && ticketId.length > 0,
  });
}
