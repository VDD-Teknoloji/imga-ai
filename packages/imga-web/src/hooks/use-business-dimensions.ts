// Sprint 9.3 B — business dimension config + breakdown hooks.

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

export type DimensionKey =
  | "business_segment"
  | "product_line"
  | "channel"
  | "customer_tier";

export interface DimensionConfig {
  id: string;
  dimension: DimensionKey;
  display_label: string;
  enabled: boolean;
  allowed_values: string[];
  csv_column_mapping: string | null;
  created_at: string;
  updated_at: string;
}

export interface DimensionConfigUpsertRequest {
  display_label: string;
  enabled?: boolean;
  allowed_values?: string[];
  csv_column_mapping?: string | null;
}

export interface DimensionBreakdown {
  metric_key: string;
  dimension: DimensionKey;
  buckets: { value: string; count: number; score: number }[];
  total_count: number;
  coverage_count: number;
}

const QUERY_KEY = ["business-dimensions"] as const;

export function useBusinessDimensions() {
  return useQuery<DimensionConfig[]>({
    queryKey: QUERY_KEY,
    queryFn: () =>
      apiRequest<DimensionConfig[]>("/tenants/me/business-dimensions"),
  });
}

export function useUpsertBusinessDimension() {
  const qc = useQueryClient();
  return useMutation<
    DimensionConfig,
    Error,
    { dimension: DimensionKey; body: DimensionConfigUpsertRequest }
  >({
    mutationFn: ({ dimension, body }) =>
      apiRequest<DimensionConfig>(
        `/tenants/me/business-dimensions/${dimension}`,
        { method: "PUT", body },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}

export function useDeleteBusinessDimension() {
  const qc = useQueryClient();
  return useMutation<void, Error, DimensionKey>({
    mutationFn: (dimension) =>
      apiRequest<void>(
        `/tenants/me/business-dimensions/${dimension}`,
        { method: "DELETE" },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}

export function useDimensionBreakdown(
  dimension: DimensionKey | undefined,
  metricKey = "review_volume",
) {
  return useQuery<DimensionBreakdown>({
    queryKey: ["dimension-breakdown", dimension, metricKey],
    enabled: typeof dimension === "string",
    queryFn: () =>
      apiRequest<DimensionBreakdown>(
        `/tenants/me/business-dimensions/${dimension}/breakdown?metric_key=${metricKey}`,
      ),
  });
}
