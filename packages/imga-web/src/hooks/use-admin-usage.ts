"use client";

// C1/C2 (2026-08-20 süper-admin envanteri) — /admin/usage sayfasının iki
// veri kaynağı: platform genelinde LLM kullanım + maliyet raporu, ve
// altyapı sağlık özeti. Backend: imga_api routes/admin/{llm_usage,
// system_health}.py.

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

export interface AdminLlmUsageByTenant {
  tenant_id: string;
  tenant_name: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  /** Bilinen maliyetlerin toplamı; hiç bilinen maliyet yoksa null
   *  (0 DEĞİL — "bilinmiyor" ile "gerçekten sıfır" karışmasın, bkz.
   *  routes/admin/llm_usage.py modül docstring'i). */
  total_cost_usd: number | null;
  unknown_cost_calls: number;
  /** 0-1 arası oran (görüntülerken *100). */
  error_rate: number;
}

export interface AdminLlmUsageByCallType {
  call_type: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  total_cost_usd: number | null;
}

export interface AdminLlmUsagePlatformTotals {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  total_cost_usd: number | null;
  unknown_cost_calls: number;
  error_rate: number;
}

export interface AdminLlmUsageResponse {
  date_from: string;
  date_to: string;
  tenants: AdminLlmUsageByTenant[];
  call_types: AdminLlmUsageByCallType[];
  platform: AdminLlmUsagePlatformTotals;
}

export interface AdminLlmUsageFilters {
  /** YYYY-MM-DD (bare date — backend `date_from: date | None`, tam ISO
   *  datetime DEĞİL, use-analytics.ts'teki gibi genişletme gerekmiyor).
   *  Boş bırakılırsa backend varsayılanı uygular (son 30 gün). */
  date_from?: string;
  date_to?: string;
}

export function useAdminLlmUsage(filters: AdminLlmUsageFilters = {}) {
  const qs = new URLSearchParams();
  if (filters.date_from) qs.set("date_from", filters.date_from);
  if (filters.date_to) qs.set("date_to", filters.date_to);
  const qsStr = qs.toString();
  return useQuery<AdminLlmUsageResponse>({
    queryKey: ["admin-llm-usage", filters.date_from ?? "", filters.date_to ?? ""],
    queryFn: () => apiRequest<AdminLlmUsageResponse>(`/admin/llm-usage${qsStr ? `?${qsStr}` : ""}`),
  });
}

export interface AdminJobStatusCount {
  status: string;
  count: number;
}

export interface AdminSystemHealth {
  redis_ok: boolean;
  /** Redis erişilemezse null (best-effort — bkz. routes/admin/system_health.py). */
  arq_queue_depth: number | null;
  /** Worker health-check anahtarının ham değeri, ya da "unknown" (taze
   *  worker ilk health-check turunu henüz atmamışsa). Sabit bir enum
   *  değil — olduğu gibi gösterilir. */
  workers: string;
  jobs_by_status: AdminJobStatusCount[];
}

export function useAdminSystemHealth() {
  return useQuery<AdminSystemHealth>({
    queryKey: ["admin-system-health"],
    queryFn: () => apiRequest<AdminSystemHealth>("/admin/system-health"),
    staleTime: 30_000,
  });
}
