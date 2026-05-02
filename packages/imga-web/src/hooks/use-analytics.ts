// Sprint 8.3.3 analytics hooks.
//
// Seven query hooks against /tenants/me/analytics/*. All share a
// common ``AnalyticsFilters`` shape; per-endpoint helpers compose
// only the filters the corresponding backend route actually accepts.
//
// Cache strategy: every hook keys on the serialised filter QS so the
// /insights filter bar's URL-state changes invalidate cleanly.

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type {
  AnalyticsFilters,
  CategoryDistResponse,
  Granularity,
  OverrideStatsResponse,
  SensitivityDistResponse,
  SentimentByCategoryResponse,
  SentimentDistResponse,
  SentimentTimelineResponse,
  TicketResolutionResponse,
} from "@/lib/types";

function qs(params: Record<string, string | number | undefined | string[]>): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === "") continue;
    if (Array.isArray(v)) {
      if (v.length > 0) u.set(k, v.join(","));
    } else {
      u.set(k, String(v));
    }
  }
  return u.toString();
}

function commonParams(f: AnalyticsFilters): Record<string, string | string[] | undefined> {
  return {
    date_from: f.date_from,
    date_to: f.date_to,
    sentiment_labels: f.sentiment_labels,
    category_ids: f.category_ids,
    source_types: f.source_types,
    batch_job_id: f.batch_job_id,
  };
}

export function useSentimentDistribution(filters: AnalyticsFilters) {
  const query = qs(commonParams(filters));
  return useQuery<SentimentDistResponse>({
    queryKey: ["analytics-sentiment-dist", query],
    queryFn: () =>
      apiRequest<SentimentDistResponse>(
        `/tenants/me/analytics/sentiment-distribution?${query}`,
      ),
  });
}

export function useCategoryDistribution(filters: AnalyticsFilters, limit = 10) {
  const query = qs({ ...commonParams(filters), limit });
  return useQuery<CategoryDistResponse>({
    queryKey: ["analytics-category-dist", query],
    queryFn: () =>
      apiRequest<CategoryDistResponse>(
        `/tenants/me/analytics/category-distribution?${query}`,
      ),
  });
}

export function useSentimentByCategory(filters: AnalyticsFilters, topN = 10) {
  const query = qs({
    date_from: filters.date_from,
    date_to: filters.date_to,
    source_types: filters.source_types,
    batch_job_id: filters.batch_job_id,
    top_n_categories: topN,
  });
  return useQuery<SentimentByCategoryResponse>({
    queryKey: ["analytics-sentiment-by-category", query],
    queryFn: () =>
      apiRequest<SentimentByCategoryResponse>(
        `/tenants/me/analytics/sentiment-by-category?${query}`,
      ),
  });
}

export function useOverrideStats(filters: AnalyticsFilters) {
  const query = qs({
    date_from: filters.date_from,
    date_to: filters.date_to,
    source_types: filters.source_types,
  });
  return useQuery<OverrideStatsResponse>({
    queryKey: ["analytics-override-stats", query],
    queryFn: () =>
      apiRequest<OverrideStatsResponse>(
        `/tenants/me/analytics/override-stats?${query}`,
      ),
  });
}

export function useSentimentTimeline(
  filters: AnalyticsFilters,
  granularity: Granularity = "day",
) {
  const query = qs({
    granularity,
    date_from: filters.date_from,
    date_to: filters.date_to,
    source_types: filters.source_types,
  });
  return useQuery<SentimentTimelineResponse>({
    queryKey: ["analytics-sentiment-timeline", query],
    queryFn: () =>
      apiRequest<SentimentTimelineResponse>(
        `/tenants/me/analytics/sentiment-timeline?${query}`,
      ),
  });
}

export function useTicketResolutionTime(filters: AnalyticsFilters) {
  const query = qs({
    date_from: filters.date_from,
    date_to: filters.date_to,
    category_ids: filters.category_ids,
  });
  return useQuery<TicketResolutionResponse>({
    queryKey: ["analytics-ticket-resolution", query],
    queryFn: () =>
      apiRequest<TicketResolutionResponse>(
        `/tenants/me/analytics/ticket-resolution-time?${query}`,
      ),
  });
}

export function useSensitivityDistribution(filters: AnalyticsFilters) {
  const query = qs({
    date_from: filters.date_from,
    date_to: filters.date_to,
    source_types: filters.source_types,
  });
  return useQuery<SensitivityDistResponse>({
    queryKey: ["analytics-sensitivity-dist", query],
    queryFn: () =>
      apiRequest<SensitivityDistResponse>(
        `/tenants/me/analytics/sensitivity-distribution?${query}`,
      ),
  });
}
