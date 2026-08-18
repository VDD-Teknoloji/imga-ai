// Sprint 8.3.9 — heatmap read hook for /insights heatmap tab.

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type {
  HeatmapMetric,
  HeatmapResponse,
  HeatmapXAxis,
  HeatmapYAxis,
} from "@/lib/types";

interface HeatmapFilters {
  x_axis: HeatmapXAxis;
  y_axis: HeatmapYAxis;
  metric: HeatmapMetric;
  date_from?: string;
  date_to?: string;
  taxonomy_top_n?: number;
  /** 2026-08-18 (Dalga 3, WS2) — düşük kaliteli (bayraklı) satırları da
   *  dahil et. Varsayılan: hariç (backend default'uyla aynı). */
  include_flagged?: boolean;
}

function queryString(filters: HeatmapFilters): string {
  const params = new URLSearchParams();
  params.set("x_axis", filters.x_axis);
  params.set("y_axis", filters.y_axis);
  params.set("metric", filters.metric);
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  if (filters.taxonomy_top_n !== undefined) {
    params.set("taxonomy_top_n", String(filters.taxonomy_top_n));
  }
  if (filters.include_flagged) params.set("include_flagged", "true");
  return params.toString();
}

export function useInsightsHeatmap(filters: HeatmapFilters) {
  const qs = queryString(filters);
  return useQuery<HeatmapResponse>({
    queryKey: ["insights-heatmap", qs],
    queryFn: () =>
      apiRequest<HeatmapResponse>(`/tenants/me/insights/heatmap?${qs}`),
    // 1h backend cache → 1h frontend staleTime.
    staleTime: 60 * 60 * 1000,
    // The component disables itself when x_axis === y_axis; don't
    // bother firing a query that would 400.
    enabled: filters.x_axis !== (filters.y_axis as unknown as HeatmapXAxis),
  });
}
