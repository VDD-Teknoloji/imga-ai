// 2026-08-21 — Operasyonel analitik (SLA/CSAT/efor/tazmin/teslimat) hook'ları.
//
// Backend (imga-api) paralel bir ajan tarafından yazılıyor; buradaki
// tipler + query-string inşası görev sözleşmesindeki 5 uca birebir
// uyuyor. use-business-dimensions.ts'teki dateOnlyToLocalIso deseni
// aynen tekrarlanıyor (URL YYYY-MM-DD taşır, backend ISO datetime
// bekler — ISO'ya burada, hook seviyesinde genişletilir).

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { BreakdownDimensionKey } from "@/hooks/use-business-dimensions";

function dateOnlyToLocalIso(value: string | undefined, endOfDay: boolean): string | undefined {
  if (!value) return undefined;
  const d = new Date(`${value}${endOfDay ? "T23:59:59" : "T00:00:00"}`);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

// --- 1) GET /tenants/me/operations/summary --------------------------------

export interface OperationsSlaBucket {
  within: number;
  violated: number;
  violation_rate_pct: number;
}

export interface OperationsSummary {
  total_reviews: number;
  facts_coverage: {
    sla_resolution: number;
    sla_first_response: number;
    csat: number;
    effort: number;
    delivery: number;
    compensation: number;
  };
  sla: {
    resolution: OperationsSlaBucket;
    first_response: OperationsSlaBucket;
    avg_resolution_minutes: number | null;
    median_resolution_minutes: number | null;
    avg_first_response_minutes: number | null;
  };
  effort: {
    avg_agent_interactions: number | null;
    avg_customer_interactions: number | null;
  };
  csat: {
    count: number;
    avg_score: number | null;
    distribution: Record<string, number>;
  };
  compensation: {
    statuses: Record<string, number>;
    freight_cost_sum: number;
    goods_cost_sum: number;
  };
  delivery: {
    statuses: Record<string, number>;
  };
}

export interface OperationsQueryFilters {
  date_from?: string;
  date_to?: string;
  include_flagged?: boolean;
}

function commonOperationsParams(filters: OperationsQueryFilters): URLSearchParams {
  const params = new URLSearchParams();
  const isoFrom = dateOnlyToLocalIso(filters.date_from, false);
  const isoTo = dateOnlyToLocalIso(filters.date_to, true);
  if (isoFrom) params.set("date_from", isoFrom);
  if (isoTo) params.set("date_to", isoTo);
  // Backend default false — yalnız açık true'yu gönderiyoruz ki
  // varsayılan durumda query-cache anahtarı temiz kalsın.
  if (filters.include_flagged) params.set("include_flagged", "true");
  return params;
}

export function useOperationsSummary(filters: OperationsQueryFilters) {
  const qs = commonOperationsParams(filters).toString();
  return useQuery<OperationsSummary>({
    queryKey: ["operations-summary", qs],
    queryFn: () =>
      apiRequest<OperationsSummary>(`/tenants/me/operations/summary?${qs}`),
  });
}

// --- 2) GET /tenants/me/operations/breakdown -------------------------------

export type OperationsBreakdownDimension = BreakdownDimensionKey;

export type OperationsMetricKey =
  | "violation_rate"
  | "first_response_violation_rate"
  | "avg_resolution_minutes"
  | "avg_first_response_minutes"
  | "avg_agent_interactions"
  | "avg_customer_interactions"
  | "csat_avg";

export interface OperationsBreakdownBucket {
  value: string;
  count: number;
  /** Sözleşmedeki tek alan adı — score hedge'i YOK (o yalnız eski
   *  business-dimensions breakdown ucunda kalıyor, burada değil). */
  metric_value: number | null;
}

export interface OperationsBreakdown {
  dimension: string;
  metric_key: string;
  buckets: OperationsBreakdownBucket[];
  total_count: number;
  coverage_count: number;
}

export interface OperationsBreakdownFilters extends OperationsQueryFilters {
  dimension: OperationsBreakdownDimension;
  metric_key: OperationsMetricKey;
}

export function useOperationsBreakdown(filters: OperationsBreakdownFilters) {
  const { dimension, metric_key, ...rest } = filters;
  const params = commonOperationsParams(rest);
  params.set("dimension", dimension);
  params.set("metric_key", metric_key);
  const qs = params.toString();

  return useQuery<OperationsBreakdown>({
    queryKey: ["operations-breakdown", qs],
    queryFn: () =>
      apiRequest<OperationsBreakdown>(`/tenants/me/operations/breakdown?${qs}`),
  });
}

// --- 3) GET /tenants/me/operations/sentiment-correlation -------------------

export interface SentimentCorrelationBucket {
  NEGATIF: number;
  NOTR: number;
  POZITIF: number;
}

export interface CsatMatrixRow extends SentimentCorrelationBucket {
  csat_score: number;
}

export interface SentimentCorrelation {
  sla: {
    violated: SentimentCorrelationBucket;
    within: SentimentCorrelationBucket;
  };
  csat_matrix: CsatMatrixRow[];
  agreement: {
    csat_high_model_positive_pct: number | null;
    csat_low_model_negative_pct: number | null;
    n_csat: number;
  };
}

export function useSentimentCorrelation(filters: OperationsQueryFilters) {
  const qs = commonOperationsParams(filters).toString();
  return useQuery<SentimentCorrelation>({
    queryKey: ["operations-sentiment-correlation", qs],
    queryFn: () =>
      apiRequest<SentimentCorrelation>(
        `/tenants/me/operations/sentiment-correlation?${qs}`,
      ),
  });
}

// --- 4) fact-mappings (GET/PUT, tam-replace) --------------------------------

export type FactField =
  | "sla_resolution_status"
  | "sla_first_response_status"
  | "resolution_time"
  | "first_response_time"
  | "csat"
  | "agent_interactions"
  | "customer_interactions"
  | "compensation_status"
  | "freight_cost"
  | "goods_cost"
  | "refund_reason"
  | "delivery_status"
  | "delivery_detail";

export interface FactMapping {
  fact_field: FactField;
  csv_column_mapping: string | null;
  enabled: boolean;
}

const FACT_MAPPINGS_QUERY_KEY = ["fact-mappings"] as const;

export function useFactMappings() {
  return useQuery<FactMapping[]>({
    queryKey: FACT_MAPPINGS_QUERY_KEY,
    queryFn: () => apiRequest<FactMapping[]>("/tenants/me/fact-mappings"),
  });
}

export function useSaveFactMappings() {
  const queryClient = useQueryClient();
  return useMutation<FactMapping[], Error, FactMapping[]>({
    mutationFn: (body) =>
      apiRequest<FactMapping[]>("/tenants/me/fact-mappings", {
        method: "PUT",
        body,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: FACT_MAPPINGS_QUERY_KEY });
    },
  });
}
