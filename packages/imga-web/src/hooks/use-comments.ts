"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type {
  TicketComment,
  TicketCommentKind,
  TicketCommentsResponse,
} from "@/lib/types";

/**
 * Sprint 7.7.2 comment hooks. The backend ships:
 *
 *   POST /tickets/{id}/comments              — create
 *   GET  /tickets/{id}/comments              — list (?include_archived)
 *   POST /tickets/{id}/comments/{cid}/archive — soft-delete
 *
 * There is no edit endpoint yet. The "5-minute Düzenle" button from
 * the Sprint 7.7 spec is intentionally not wired in this iteration —
 * see the closeout report for the gap.
 *
 * Cache key family ``["tickets", "comments", ticketId]``. The
 * /timeline endpoint reads the same comment rows server-side, so any
 * comment mutation also invalidates ``["tickets", "timeline", ticketId]``
 * to keep the merged event list fresh.
 */

const COMMENTS_KEY = "tickets-comments";
const TIMELINE_KEY = "tickets-timeline";

function commentsQueryKey(ticketId: string): readonly unknown[] {
  return [COMMENTS_KEY, ticketId];
}

function timelineQueryKey(ticketId: string): readonly unknown[] {
  return [TIMELINE_KEY, ticketId];
}

export function useTicketComments(ticketId: string | undefined) {
  return useQuery({
    queryKey: commentsQueryKey(ticketId ?? ""),
    queryFn: async () => {
      const data = await apiRequest<TicketCommentsResponse>(
        `/tickets/${ticketId}/comments`,
      );
      return data.comments;
    },
    enabled: typeof ticketId === "string" && ticketId.length > 0,
  });
}

export interface CreateCommentInput {
  ticketId: string;
  body: string;
  kind: TicketCommentKind;
}

export function useCreateComment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: CreateCommentInput): Promise<TicketComment> => {
      return apiRequest<TicketComment>(
        `/tickets/${input.ticketId}/comments`,
        {
          method: "POST",
          body: { body: input.body, kind: input.kind },
        },
      );
    },
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: commentsQueryKey(vars.ticketId) });
      qc.invalidateQueries({ queryKey: timelineQueryKey(vars.ticketId) });
    },
  });
}

export interface ArchiveCommentInput {
  ticketId: string;
  commentId: string;
}

export function useArchiveComment() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: ArchiveCommentInput): Promise<TicketComment> => {
      return apiRequest<TicketComment>(
        `/tickets/${input.ticketId}/comments/${input.commentId}/archive`,
        { method: "POST" },
      );
    },
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: commentsQueryKey(vars.ticketId) });
      qc.invalidateQueries({ queryKey: timelineQueryKey(vars.ticketId) });
    },
  });
}
