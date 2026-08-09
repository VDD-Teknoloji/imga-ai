// Katılım Oranı — kurum tarafı hook'ları.
//
// Kurum yalnızca aylık işlem adedini girer; katılım tablosu ile
// değerlendirme bantları backend'den okunur (bantları süper yönetici
// düzenler, bkz. use-admin-engagement.ts).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

export interface MonthlyMetric {
  id: string;
  period_month: string; // ISO date, ayın ilk günü
  transaction_count: number;
  set_by_user_id: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface MonthlyMetricUpsertRequest {
  period_month: string;
  transaction_count: number;
  notes?: string | null;
}

export interface EngagementBand {
  min_pct: number;
  label: string;
}

export interface EngagementRow {
  period_month: string;
  transaction_count: number | null;
  review_count: number;
  engagement_pct: number | null;
  band_label: string | null;
  band_index: number | null;
}

export interface EngagementResponse {
  rows: EngagementRow[];
  bands: EngagementBand[];
}

const METRICS_KEY = ["monthly-metrics"] as const;
const ENGAGEMENT_KEY = ["engagement"] as const;

export function useMonthlyMetrics() {
  return useQuery<MonthlyMetric[]>({
    queryKey: METRICS_KEY,
    queryFn: () => apiRequest<MonthlyMetric[]>("/tenants/me/monthly-metrics"),
  });
}

export function useEngagement() {
  return useQuery<EngagementResponse>({
    queryKey: ENGAGEMENT_KEY,
    queryFn: () => apiRequest<EngagementResponse>("/tenants/me/engagement"),
  });
}

export function useUpsertMonthlyMetric() {
  const qc = useQueryClient();
  return useMutation<MonthlyMetric, Error, MonthlyMetricUpsertRequest>({
    mutationFn: (body) =>
      apiRequest<MonthlyMetric>("/tenants/me/monthly-metrics", {
        method: "PUT",
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: METRICS_KEY });
      qc.invalidateQueries({ queryKey: ENGAGEMENT_KEY });
    },
  });
}

export function useDeleteMonthlyMetric() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (periodMonth) =>
      apiRequest<void>(`/tenants/me/monthly-metrics/${periodMonth}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: METRICS_KEY });
      qc.invalidateQueries({ queryKey: ENGAGEMENT_KEY });
    },
  });
}
