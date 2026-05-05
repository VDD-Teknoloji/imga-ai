// Sprint 8.3.9 — cohort analysis read hook for /insights cohort tab.

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type {
  CohortDimension,
  CohortPeriod,
  CohortResponse,
} from "@/lib/types";

interface CohortFilters {
  period: CohortPeriod;
  dimension: CohortDimension;
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
