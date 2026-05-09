// Sprint 9.2 B — KPI goals CRUD + bulk progress hook.
//
// Three concerns:
//   * useKpiGoals(activeOnly): list-render the settings page table.
//   * useKpiGoalProgressBulk(): dashboard reads this and binds the
//     KpiGoalCards row.
//   * useCreateKpiGoal / useDeleteKpiGoal: form mutations.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

export type GoalPeriod = "weekly" | "monthly" | "quarterly" | "yearly";

export interface KpiGoal {
  id: string;
  metric_key: string;
  target_value: number;
  target_period: GoalPeriod;
  period_start: string; // ISO date
  period_end: string;
  set_by_user_id: string | null;
  set_at: string;
  notes: string | null;
}

export interface KpiGoalCreateRequest {
  metric_key: string;
  target_value: number;
  target_period: GoalPeriod;
  period_start: string;
  period_end: string;
  notes?: string | null;
}

export interface KpiGoalProgress {
  metric_key: string;
  target_value: number;
  current_value: number | null;
  achievement_pct: number | null;
  on_track: boolean;
  period_start: string;
  period_end: string;
  target_period: GoalPeriod;
  higher_is_better: boolean;
}

const QUERY_KEY = ["kpi-goals"] as const;
const PROGRESS_KEY = ["kpi-goals", "progress"] as const;

export function useKpiGoals(activeOnly = true) {
  return useQuery<KpiGoal[]>({
    queryKey: [...QUERY_KEY, { activeOnly }],
    queryFn: () =>
      apiRequest<KpiGoal[]>(
        `/tenants/me/kpi-goals?active_only=${activeOnly ? "true" : "false"}`,
      ),
  });
}

export function useKpiGoalProgressBulk() {
  return useQuery<KpiGoalProgress[]>({
    queryKey: PROGRESS_KEY,
    queryFn: () =>
      apiRequest<KpiGoalProgress[]>("/tenants/me/kpi-goals/progress"),
    // Sprint 9.2 — dashboard reads this on every render; staleTime
    // 60s avoids hammering the metric-bulk-fetch endpoint when the
    // user toggles between dashboard tabs.
    staleTime: 60_000,
  });
}

export function useCreateKpiGoal() {
  const qc = useQueryClient();
  return useMutation<KpiGoal, Error, KpiGoalCreateRequest>({
    mutationFn: (body) =>
      apiRequest<KpiGoal>("/tenants/me/kpi-goals", {
        method: "POST",
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
      qc.invalidateQueries({ queryKey: PROGRESS_KEY });
    },
  });
}

export function useDeleteKpiGoal() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (id) =>
      apiRequest<void>(`/tenants/me/kpi-goals/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
      qc.invalidateQueries({ queryKey: PROGRESS_KEY });
    },
  });
}
