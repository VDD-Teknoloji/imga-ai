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
}

export function useAnalyze() {
  const qc = useQueryClient();
  return useMutation<TenantAnalyzeResponse, Error, AnalyzeInput>({
    mutationFn: async ({ text }) => {
      return apiRequest<TenantAnalyzeResponse>("/tenants/me/analyze", {
        method: "POST",
        body: { text },
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
