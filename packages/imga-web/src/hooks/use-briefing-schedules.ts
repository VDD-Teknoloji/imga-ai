// Sprint 9.2 D — scheduled briefings CRUD + run-now hook.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

export type SchedulePeriod = "weekly" | "monthly";

export interface BriefingSchedule {
  id: string;
  period: SchedulePeriod;
  schedule_day: number;
  schedule_hour: number;
  timezone: string;
  recipients: string[];
  email_recipients: string[];
  enabled: boolean;
  last_run_at: string | null;
  last_run_briefing_id: string | null;
  last_run_status: "success" | "failed" | null;
  last_run_error: string | null;
  next_run_at: string;
  created_at: string;
}

export interface BriefingScheduleCreateRequest {
  period: SchedulePeriod;
  schedule_day: number;
  schedule_hour?: number;
  timezone?: string;
  recipients?: string[];
  email_recipients?: string[];
  enabled?: boolean;
}

export interface BriefingScheduleUpdateRequest {
  enabled?: boolean;
  schedule_day?: number;
  schedule_hour?: number;
  recipients?: string[];
  email_recipients?: string[];
}

const QUERY_KEY = ["briefing-schedules"] as const;

export function useBriefingSchedules() {
  return useQuery<BriefingSchedule[]>({
    queryKey: QUERY_KEY,
    queryFn: () =>
      apiRequest<BriefingSchedule[]>("/tenants/me/briefing-schedules"),
  });
}

export function useCreateBriefingSchedule() {
  const qc = useQueryClient();
  return useMutation<
    BriefingSchedule,
    Error,
    BriefingScheduleCreateRequest
  >({
    mutationFn: (body) =>
      apiRequest<BriefingSchedule>("/tenants/me/briefing-schedules", {
        method: "POST",
        body,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}

export function useUpdateBriefingSchedule() {
  const qc = useQueryClient();
  return useMutation<
    BriefingSchedule,
    Error,
    { id: string; body: BriefingScheduleUpdateRequest }
  >({
    mutationFn: ({ id, body }) =>
      apiRequest<BriefingSchedule>(
        `/tenants/me/briefing-schedules/${id}`,
        { method: "PATCH", body },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}

export function useDeleteBriefingSchedule() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (id) =>
      apiRequest<void>(`/tenants/me/briefing-schedules/${id}`, {
        method: "DELETE",
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}

export function useRunBriefingScheduleNow() {
  const qc = useQueryClient();
  return useMutation<BriefingSchedule, Error, string>({
    mutationFn: (id) =>
      apiRequest<BriefingSchedule>(
        `/tenants/me/briefing-schedules/${id}/run-now`,
        { method: "POST" },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}
