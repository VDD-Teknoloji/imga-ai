"use client";

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { InvitationPreview } from "@/lib/types";

/**
 * Reads invitation metadata without consuming the token. Backend
 * is rate-limited (token + IP); we cap retries at 0 so a 404
 * doesn't bombard the endpoint. The api-client wrapper recognises
 * /invitations/* paths as auth-bootstrap and skips the 401-retry
 * loop for them, so a logged-out invitee on /invite/[token] hits
 * the route cleanly.
 *
 * Sprint 7.5.5 amendment: response carries `email_exists`, which
 * the consumer uses to pick between the new-account form and the
 * re-auth form on first paint.
 */
export function useInvitationPreview(token: string | undefined) {
  return useQuery({
    queryKey: ["invitation-preview", token],
    queryFn: async () => {
      return apiRequest<InvitationPreview>(
        `/invitations/${encodeURIComponent(token ?? "")}/preview`,
        { method: "POST" },
      );
    },
    enabled: typeof token === "string" && token.length > 0,
    retry: false,
    staleTime: 60_000,
  });
}
