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
  CompanyPerspectiveDistResponse,
  Granularity,
  HeadlineMetrics,
  NPSMonthlyPoint,
  NPSSummary,
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

// AnalyticsFilters carries YYYY-MM-DD date strings (URL-friendly, no
// timezone slide). The backend expects ISO datetimes, so we expand to
// local-midnight (start) and local-end-of-day (end) here. Invalid dates
// are dropped instead of rejected — the URL bar is user-edited so a
// half-typed value just means "filter not yet committed".
function dateOnlyToLocalIso(value: string | undefined, endOfDay: boolean): string | undefined {
  if (!value) return undefined;
  const d = new Date(`${value}${endOfDay ? "T23:59:59" : "T00:00:00"}`);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

function commonParams(f: AnalyticsFilters): Record<string, string | string[] | undefined> {
  return {
    date_from: dateOnlyToLocalIso(f.date_from, false),
    date_to: dateOnlyToLocalIso(f.date_to, true),
    sentiment_labels: f.sentiment_labels,
    category_ids: f.category_ids,
    source_types: f.source_types,
    batch_job_id: f.batch_job_id,
  };
}

function dateRangeParams(f: AnalyticsFilters): Record<string, string | undefined> {
  return {
    date_from: dateOnlyToLocalIso(f.date_from, false),
    date_to: dateOnlyToLocalIso(f.date_to, true),
  };
}

export function useSentimentDistribution(filters: AnalyticsFilters) {
  const query = qs(commonParams(filters));
  return useQuery<SentimentDistResponse>({
    queryKey: ["analytics-sentiment-dist", query],
    queryFn: () =>
      apiRequest<SentimentDistResponse>(`/tenants/me/analytics/sentiment-distribution?${query}`),
  });
}

export function useCategoryDistribution(filters: AnalyticsFilters, limit = 10) {
  const query = qs({ ...commonParams(filters), limit });
  return useQuery<CategoryDistResponse>({
    queryKey: ["analytics-category-dist", query],
    queryFn: () =>
      apiRequest<CategoryDistResponse>(`/tenants/me/analytics/category-distribution?${query}`),
  });
}

export function useSentimentByCategory(filters: AnalyticsFilters, topN = 10) {
  const query = qs({
    ...dateRangeParams(filters),
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
    ...dateRangeParams(filters),
    source_types: filters.source_types,
  });
  return useQuery<OverrideStatsResponse>({
    queryKey: ["analytics-override-stats", query],
    queryFn: () =>
      apiRequest<OverrideStatsResponse>(`/tenants/me/analytics/override-stats?${query}`),
  });
}

export function useSentimentTimeline(filters: AnalyticsFilters, granularity: Granularity = "day") {
  const query = qs({
    granularity,
    ...dateRangeParams(filters),
    source_types: filters.source_types,
  });
  return useQuery<SentimentTimelineResponse>({
    queryKey: ["analytics-sentiment-timeline", query],
    queryFn: () =>
      apiRequest<SentimentTimelineResponse>(`/tenants/me/analytics/sentiment-timeline?${query}`),
  });
}

export function useTicketResolutionTime(filters: AnalyticsFilters) {
  const query = qs({
    ...dateRangeParams(filters),
    category_ids: filters.category_ids,
  });
  return useQuery<TicketResolutionResponse>({
    queryKey: ["analytics-ticket-resolution", query],
    queryFn: () =>
      apiRequest<TicketResolutionResponse>(`/tenants/me/analytics/ticket-resolution-time?${query}`),
  });
}

export function useSensitivityDistribution(filters: AnalyticsFilters) {
  const query = qs({
    ...dateRangeParams(filters),
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

// --- Sprint 8.3.5 / 8.3.5.6 — NPS + headline + perspective distribution --

/** ``date_from`` / ``date_to`` are bare YYYY-MM-DD strings (no timezone
 *  expansion needed; the NPS endpoints accept ``date`` query params and
 *  widen server-side). The shape matches the FastAPI date binding. */
interface NpsDateFilters {
  date_from?: string;
  date_to?: string;
  batch_job_id?: string;
}

export function useNpsSummary(filters: NpsDateFilters) {
  const query = qs({
    date_from: filters.date_from,
    date_to: filters.date_to,
    batch_job_id: filters.batch_job_id,
  });
  return useQuery<NPSSummary>({
    queryKey: ["analytics-nps-summary", query],
    queryFn: () => apiRequest<NPSSummary>(`/tenants/me/analytics/nps-summary?${query}`),
  });
}

export function useNpsMonthlyTrend(monthsBack: number = 12) {
  const query = qs({ months_back: monthsBack });
  return useQuery<NPSMonthlyPoint[]>({
    queryKey: ["analytics-nps-trend", query],
    queryFn: () =>
      apiRequest<NPSMonthlyPoint[]>(`/tenants/me/analytics/nps-monthly-trend?${query}`),
  });
}

export function useHeadlineMetrics(filters: NpsDateFilters) {
  // Sprint 9.5 B4 — forward batch_job_id. NpsDateFilters already
  // declared the field but the hook silently dropped it; the
  // strategy page passes it to scope NPS + the headline counts to a
  // single batch's review set.
  const query = qs({
    date_from: filters.date_from,
    date_to: filters.date_to,
    batch_id: filters.batch_job_id,
  });
  return useQuery<HeadlineMetrics>({
    queryKey: ["analytics-headline-metrics", query],
    queryFn: () => apiRequest<HeadlineMetrics>(`/tenants/me/analytics/headline-metrics?${query}`),
  });
}

export function useCompanyPerspectiveDistribution(filters: AnalyticsFilters, limit = 10) {
  const query = qs({ ...commonParams(filters), limit });
  return useQuery<CompanyPerspectiveDistResponse>({
    queryKey: ["analytics-company-perspective-dist", query],
    queryFn: () =>
      apiRequest<CompanyPerspectiveDistResponse>(
        `/tenants/me/analytics/company-perspective-distribution?${query}`,
      ),
  });
}
