// Sprint 8.3.3 analytics hooks.
//
// Seven query hooks against /tenants/me/analytics/*. All share a
// common ``AnalyticsFilters`` shape; per-endpoint helpers compose
// only the filters the corresponding backend route actually accepts.
//
// Cache strategy: every hook keys on the serialised filter QS so the
// /insights filter bar's URL-state changes invalidate cleanly.

import { keepPreviousData, useQuery } from "@tanstack/react-query";

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

function qs(
  params: Record<string, string | number | boolean | undefined | string[]>,
): string {
  const u = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    // false omitted like undefined — every include_flagged=false call
    // would otherwise add a distinct query-cache key for a value that's
    // already the backend default, churning every analytics query key.
    if (v === undefined || v === "" || v === false) continue;
    if (Array.isArray(v)) {
      if (v.length > 0) u.set(k, v.join(","));
    } else {
      u.set(k, String(v));
    }
  }
  return u.toString();
}

// 2026-08-18 (Dalga 3, WS2) — veri kalitesi include_flagged toggle.
// lib/types.ts'e dokunulmuyor (WS5 reviews ajanıyla eşzamanlı düzenleme
// riski) — root-cause hook desenindeki gibi tip burada genişletiliyor.
// AnalyticsFilters değerleri (include_flagged'sız) yapısal olarak buraya
// atanabilir, mevcut çağıranlar değişmeden derlenmeye devam eder.
export interface AnalyticsQueryFilters extends AnalyticsFilters {
  /** true → düşük kaliteli (duplicate/empty/informational/meaningless
   *  bayraklı) satırlar da dahil edilir. Varsayılan: hariç (backend
   *  default'uyla aynı). */
  include_flagged?: boolean;
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

function commonParams(
  f: AnalyticsQueryFilters,
): Record<string, string | string[] | boolean | undefined> {
  return {
    date_from: dateOnlyToLocalIso(f.date_from, false),
    date_to: dateOnlyToLocalIso(f.date_to, true),
    sentiment_labels: f.sentiment_labels,
    category_ids: f.category_ids,
    source_types: f.source_types,
    batch_job_id: f.batch_job_id,
    include_flagged: f.include_flagged,
  };
}

function dateRangeParams(
  f: AnalyticsQueryFilters,
): Record<string, string | boolean | undefined> {
  return {
    date_from: dateOnlyToLocalIso(f.date_from, false),
    date_to: dateOnlyToLocalIso(f.date_to, true),
    include_flagged: f.include_flagged,
  };
}

export function useSentimentDistribution(filters: AnalyticsFilters) {
  const query = qs(commonParams(filters));
  return useQuery<SentimentDistResponse>({
    queryKey: ["analytics-sentiment-dist", query],
    queryFn: () =>
      apiRequest<SentimentDistResponse>(`/tenants/me/analytics/sentiment-distribution?${query}`),
    // Dönem filtresi değişince önceki veri görünür kalır (skeleton flash yok).
    placeholderData: keepPreviousData,
  });
}

export function useCategoryDistribution(filters: AnalyticsFilters, limit = 10) {
  const query = qs({ ...commonParams(filters), limit });
  return useQuery<CategoryDistResponse>({
    queryKey: ["analytics-category-dist", query],
    queryFn: () =>
      apiRequest<CategoryDistResponse>(`/tenants/me/analytics/category-distribution?${query}`),
    placeholderData: keepPreviousData,
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
    placeholderData: keepPreviousData,
  });
}

// Sprint 13.1 — hiyerarşik drill-down 2. seviye. Kovalar backend'de
// YALNIZ review kolonlarından kurulur, bu yüzden her satır birebir
// /reviews?primary_categories=X&perspective_codes=Y bağlantısına
// çevrilebilir (sayılar tutar).
export interface CategoryDrilldownRow {
  code: string;
  label_tr: string;
  total: number;
  negative_count: number;
  negative_share: number;
  share: number;
}

export interface CategoryDrilldownResponse {
  primary_category: string;
  total: number;
  negative_total: number;
  data: CategoryDrilldownRow[];
}

export function useCategoryDrilldown(
  filters: AnalyticsFilters,
  primaryCategory: string | null,
) {
  const query = qs({
    ...dateRangeParams(filters),
    source_types: filters.source_types,
    batch_job_id: filters.batch_job_id,
    primary_category: primaryCategory ?? undefined,
  });
  return useQuery<CategoryDrilldownResponse>({
    queryKey: ["analytics-category-drilldown", query],
    // Yalnız satır açıldığında istek atılır.
    enabled: primaryCategory !== null,
    queryFn: () =>
      apiRequest<CategoryDrilldownResponse>(
        `/tenants/me/analytics/category-drilldown?${query}`,
      ),
    placeholderData: keepPreviousData,
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
  /** 2026-08-18 (Dalga 3, WS2) — bkz. AnalyticsQueryFilters. */
  include_flagged?: boolean;
}

export function useNpsSummary(filters: NpsDateFilters) {
  const query = qs({
    date_from: filters.date_from,
    date_to: filters.date_to,
    batch_job_id: filters.batch_job_id,
    include_flagged: filters.include_flagged,
  });
  return useQuery<NPSSummary>({
    queryKey: ["analytics-nps-summary", query],
    queryFn: () => apiRequest<NPSSummary>(`/tenants/me/analytics/nps-summary?${query}`),
    placeholderData: keepPreviousData,
  });
}

export function useNpsMonthlyTrend(monthsBack: number = 12, includeFlagged = false) {
  const query = qs({ months_back: monthsBack, include_flagged: includeFlagged });
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
    include_flagged: filters.include_flagged,
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
