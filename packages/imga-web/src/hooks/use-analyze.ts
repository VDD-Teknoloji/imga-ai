"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { TenantAnalyzeResponse } from "@/lib/types";

/**
 * Manual analyze + auto-ticket bridge — hits the Sprint 7.5.5
 * `POST /tenants/me/analyze` endpoint (Alt-Faz 3). Returns the
 * `TenantAnalyzeResponse` so the caller can branch on
 * `decision` (one of five values) and follow `ticket_id` when
 * the bridge minted or matched a ticket.
 *
 * On a `create` decision the dashboard's stats endpoints become
 * stale, so we invalidate the ticket-list / stats caches. On
 * `skipped_dedup` the existing ticket may have its
 * `last_state_change_at` bumped (the bridge only links, but
 * downstream UI may re-fetch); same invalidation is safe.
 */
export interface AnalyzeInput {
  text: string;
  /** Sprint 8.3.5 — optional NPS score (0–10). Omit when the form
   *  doesn't capture it; the backend ignores undefined and only
   *  persists when present. */
  nps_score?: number;
}

export function useAnalyze() {
  const qc = useQueryClient();
  return useMutation<TenantAnalyzeResponse, Error, AnalyzeInput>({
    mutationFn: async ({ text, nps_score }) => {
      return apiRequest<TenantAnalyzeResponse>("/tenants/me/analyze", {
        method: "POST",
        body: { text, nps_score },
      });
    },
    onSuccess: (data) => {
      if (data.decision === "create" || data.decision === "skipped_dedup") {
        qc.invalidateQueries({ queryKey: ["tickets-list"] });
        qc.invalidateQueries({ queryKey: ["tickets-infinite"] });
        qc.invalidateQueries({ queryKey: ["tickets-stats"] });
      }
    },
  });
}
