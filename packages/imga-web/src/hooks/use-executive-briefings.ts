// Sprint 8.3.10 — executive briefing read/write hooks.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type {
  BriefingGenerateRequest,
  BriefingListItem,
  ExecutiveBriefing,
} from "@/lib/types";

const QUERY_KEY = ["executive-briefings"] as const;

export function useExecutiveBriefings(limit: number = 50) {
  return useQuery<BriefingListItem[]>({
    queryKey: [...QUERY_KEY, { limit }],
    queryFn: () =>
      apiRequest<BriefingListItem[]>(
        `/tenants/me/executive-briefings?limit=${limit}`,
      ),
  });
}

export function useExecutiveBriefing(id: string | null) {
  return useQuery<ExecutiveBriefing>({
    queryKey: ["executive-briefing", id],
    queryFn: () => {
      if (!id) throw new Error("missing briefing id");
      return apiRequest<ExecutiveBriefing>(
        `/tenants/me/executive-briefings/${id}`,
      );
    },
    enabled: id !== null,
  });
}

export interface BriefingTopActionItem {
  id: string;
  title: string;
  description: string;
  rationale: string | null;
  priority: "high" | "medium" | "low";
  estimated_impact: "high" | "medium" | "low" | null;
  status: "open" | "in_progress" | "done" | "cancelled";
  due_date: string | null;
  assignee_user_id: string | null;
}

export interface BriefingTopActionsResponse {
  briefing_id: string;
  items: BriefingTopActionItem[];
}

export function useBriefingTopActions(id: string | null) {
  // Sprint 9.0.5-B G — pulls the ActionItem rows linked to a
  // briefing's top_actions text via the new
  // /executive-briefings/{id}/top-actions endpoint. The briefing
  // detail page renders these as clickable follow-up cards.
  return useQuery<BriefingTopActionsResponse>({
    queryKey: ["executive-briefing-top-actions", id],
    queryFn: () => {
      if (!id) throw new Error("missing briefing id");
      return apiRequest<BriefingTopActionsResponse>(
        `/tenants/me/executive-briefings/${id}/top-actions`,
      );
    },
    enabled: id !== null,
  });
}

export function useGenerateBriefing() {
  const qc = useQueryClient();
  return useMutation<ExecutiveBriefing, Error, BriefingGenerateRequest>({
    mutationFn: (body) =>
      apiRequest<ExecutiveBriefing>(
        "/tenants/me/executive-briefings/generate",
        { method: "POST", body },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}
