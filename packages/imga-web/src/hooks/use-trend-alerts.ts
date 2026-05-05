// Sprint 8.3.10 — trend alerts list + acknowledge + manual evaluate.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { TrendAlert, TrendAlertStatus } from "@/lib/types";

const QUERY_KEY = ["trend-alerts"] as const;

export function useTrendAlerts(statusFilter: TrendAlertStatus | "all" = "active") {
  return useQuery<TrendAlert[]>({
    queryKey: [...QUERY_KEY, { status: statusFilter }],
    queryFn: () => {
      const qs = statusFilter ? `?status_filter=${statusFilter}` : "";
      return apiRequest<TrendAlert[]>(`/tenants/me/trend-alerts${qs}`);
    },
  });
}

export function useUpdateTrendAlert() {
  const qc = useQueryClient();
  return useMutation<
    TrendAlert,
    Error,
    { id: string; status: TrendAlertStatus }
  >({
    mutationFn: ({ id, status }) =>
      apiRequest<TrendAlert>(`/tenants/me/trend-alerts/${id}`, {
        method: "PATCH",
        body: { status },
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}

export function useEvaluateTrendAlerts() {
  const qc = useQueryClient();
  return useMutation<TrendAlert[], Error, void>({
    mutationFn: () =>
      apiRequest<TrendAlert[]>("/tenants/me/trend-alerts/evaluate", {
        method: "POST",
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}
