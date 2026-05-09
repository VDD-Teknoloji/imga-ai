// Sprint 9.3 C — operator-decision audit list hook.

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

export interface DecisionAuditRow {
  id: string;
  decision_type: string;
  related_entity_type: string;
  related_entity_id: string;
  actor_user_id: string | null;
  payload: Record<string, unknown>;
  rationale: string | null;
  request_id: string | null;
  created_at: string;
}

export interface DecisionAuditListResponse {
  items: DecisionAuditRow[];
  total: number;
}

interface ListFilters {
  decision_type?: string;
  related_entity_type?: string;
  actor_user_id?: string;
  limit?: number;
  offset?: number;
}

export function useDecisionAuditList(filters: ListFilters = {}) {
  const qs = new URLSearchParams();
  if (filters.decision_type) qs.set("decision_type", filters.decision_type);
  if (filters.related_entity_type)
    qs.set("related_entity_type", filters.related_entity_type);
  if (filters.actor_user_id) qs.set("actor_user_id", filters.actor_user_id);
  qs.set("limit", String(filters.limit ?? 100));
  qs.set("offset", String(filters.offset ?? 0));
  const qsStr = qs.toString();
  return useQuery<DecisionAuditListResponse>({
    queryKey: ["decision-audit", filters],
    queryFn: () =>
      apiRequest<DecisionAuditListResponse>(
        `/tenants/me/decision-audit${qsStr ? `?${qsStr}` : ""}`,
      ),
  });
}
