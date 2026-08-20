// Sprint 8.3.9 — cohort analysis read hook for /insights cohort tab.

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { BreakdownDimensionKey } from "@/hooks/use-business-dimensions";
import type {
  CohortDimension,
  CohortPeriod,
  CohortResponse,
} from "@/lib/types";

// 2026-08-20 (Boyutlar sekmesi) — cohort seçicisine 6 yeni boyut
// eklendi (channel/business_segment/product_line/customer_tier/
// entered_by/source). lib/types.ts'teki CohortDimension'a dokunmuyoruz
// (backend ajanıyla eşzamanlı düzenleme riski — bkz. use-analytics.ts
// AnalyticsQueryFilters'taki aynı desen); superset tip burada, tek
// kullanım noktası (request-side dimension param) için tanımlı.
// CohortResponse.dimension hâlâ dar CohortDimension'a bağlı ama hiçbir
// tüketici onu okumuyor (bkz. cohort-tab.tsx buildChartData), bu yüzden
// zararsız.
export type CohortDimensionExt = CohortDimension | BreakdownDimensionKey;

interface CohortFilters {
  period: CohortPeriod;
  dimension: CohortDimensionExt;
  date_from?: string;
  date_to?: string;
  limit_cohorts?: number;
}

function queryString(filters: CohortFilters): string {
  const params = new URLSearchParams();
  params.set("period", filters.period);
  params.set("dimension", filters.dimension);
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  params.set("limit_cohorts", String(filters.limit_cohorts ?? 10));
  return params.toString();
}

export function useInsightsCohort(filters: CohortFilters) {
  const qs = queryString(filters);
  return useQuery<CohortResponse>({
    queryKey: ["insights-cohort", qs],
    queryFn: () =>
      apiRequest<CohortResponse>(`/tenants/me/insights/cohort?${qs}`),
    // Backend caches for 1h; matching the frontend staleTime keeps
    // the dashboard from re-firing on rapid tab switches.
    staleTime: 60 * 60 * 1000,
  });
}
