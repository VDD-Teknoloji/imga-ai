// Sprint 9.2 A — KPI metric registry, frontend cache.
//
// Single source of truth for metric labels, units, ranges, and
// "higher is better" direction. Loaded once per session via the
// /metrics/definitions route the api-server seeds from
// imga_core.metrics. Charts, KPI goal cards, executive briefing
// rendering, and the dashboard tooltip all bind to this so the UI
// never invents a label for a backend metric.

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

export type MetricUnit =
  | "score"
  | "percentage"
  | "count"
  | "ratio";

export interface MetricDefinition {
  metric_key: string;
  display_name: string;
  description: string;
  formula: string;
  unit: MetricUnit;
  range_min: number | null;
  range_max: number | null;
  higher_is_better: boolean;
  aggregation: string;
}

const QUERY_KEY = ["metric-definitions"] as const;

export function useMetricDefinitions() {
  return useQuery<MetricDefinition[]>({
    queryKey: QUERY_KEY,
    queryFn: () => apiRequest<MetricDefinition[]>("/metrics/definitions"),
    staleTime: 60 * 60 * 1000, // 1h — registry rarely changes
    gcTime: 24 * 60 * 60 * 1000, // 24h
  });
}

/** Format a metric value with the unit suffix the registry says
 *  ("score" → bare number, "percentage" → "75%", "count" → "12,345").
 *  ``definition`` is optional; without it we fall back to a bare
 *  toString. */
export function formatMetricValue(
  value: number,
  definition?: MetricDefinition,
): string {
  if (!definition) return value.toString();
  switch (definition.unit) {
    case "percentage":
      return `${value.toFixed(1)}%`;
    case "count":
      return value.toLocaleString("tr-TR");
    case "ratio":
      return value.toFixed(3);
    case "score":
    default:
      return value.toFixed(1);
  }
}
