// Sprint 8.3.1 reviews list + detail hooks.

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { ReviewDetail, ReviewListFilters, ReviewListResponse } from "@/lib/types";

// 2026-08-20 (Boyutlar filtreleri) — 6 yeni CSV filtresi. lib/types.ts'e
// dokunulmuyor (backend ajanıyla eşzamanlı düzenleme riski — bkz.
// use-analytics.ts AnalyticsQueryFilters'taki aynı desen); tip burada
// yerel olarak genişletiliyor. ReviewListFilters değerleri (bu 6 alan
// olmadan) yapısal olarak buraya atanabilir, mevcut çağıranlar
// değişmeden derlenmeye devam eder.
// 2026-08-21 (Operasyonel analitik) — /reviews/{id} yanıtına eklenen
// nullable "facts" nesnesi. Aynı desen: lib/types.ts'e dokunulmuyor
// (paralel backend ajanı henüz deploy etmedi — alan bir süre hiç
// gelmeyebilir, bu yüzden optional + nullable), ReviewDetail burada
// yerel olarak genişletiliyor.
export interface ReviewFacts {
  sla_resolution_status: "within" | "violated" | null;
  sla_first_response_status: "within" | "violated" | null;
  resolution_time_minutes: number | null;
  first_response_time_minutes: number | null;
  csat_score: number | null;
  csat_raw: string | null;
  agent_interactions: number | null;
  customer_interactions: number | null;
  compensation_status: string | null;
  freight_cost: number | null;
  goods_cost: number | null;
  refund_reason: string | null;
  delivery_status: string | null;
  delivery_detail: string | null;
}

export type ReviewDetailWithFacts = ReviewDetail & {
  facts?: ReviewFacts | null;
};

export interface ReviewDimensionFilterFields {
  channels?: string[];
  business_segments?: string[];
  product_lines?: string[];
  customer_tiers?: string[];
  entered_bys?: string[];
  sources?: string[];
}

export type ReviewListFiltersExt = ReviewListFilters & ReviewDimensionFilterFields;

export interface ManualPromotionResponse {
  review_id: string;
  ticket_id: string;
  ticket_state: string;
}

/** POST /tenants/me/reviews/{id}/create-ticket — manual override of a
 * skipped bridge decision. 409 if the review already has a ticket;
 * 403 if the caller is a viewer. */
export function useManualPromoteReview() {
  const queryClient = useQueryClient();
  return useMutation<ManualPromotionResponse, Error, string>({
    mutationFn: async (reviewId) =>
      apiRequest<ManualPromotionResponse>(`/tenants/me/reviews/${reviewId}/create-ticket`, {
        method: "POST",
      }),
    onSuccess: (_data, reviewId) => {
      queryClient.invalidateQueries({ queryKey: ["review-detail", reviewId] });
      queryClient.invalidateQueries({ queryKey: ["reviews"] });
      // W3 — ticket_linked sayacı /reviews/summary panelinde de değişir.
      queryClient.invalidateQueries({ queryKey: ["reviews-summary"] });
    },
  });
}

// --- Sprint 11.0 — kullanıcı düzeltmesi (düzeltme-geri-besleme) ------

export interface CorrectReviewPayload {
  reviewId: string;
  sentiment_label?: "POZITIF" | "NEGATIF" | "NÖTR";
  primary_category?: string;
  // 2026-08-18 (migration 0042) — duygu/kategoriden BAĞIMSIZ
  // düzeltilebilir; yalnız değişen alan gönderilir (dirty-check
  // dialog tarafında yapılır).
  sentiment_score?: number;
  experience_type?: "dijital" | "operasyonel";
  perspective_code?: string;
  reason?: string;
}

export interface CorrectReviewResponse {
  review_id: string;
  sentiment_label: string;
  sentiment_score: number;
  primary_category: string;
  experience_type: string | null;
  perspective_code: string | null;
  correction_id: string;
  embedding_stored: boolean;
}

/** POST /tenants/me/reviews/{id}/correct — yanlış model kararını
 * insan kararıyla değiştirir. Karar anında güncellenir; düzeltme
 * birebir-eşleşme sözlüğüne + Gemini few-shot havuzuna + (embedding
 * başarılıysa) anlamsal komşu aramasına girer. */
export function useCorrectReview() {
  const queryClient = useQueryClient();
  return useMutation<CorrectReviewResponse, Error, CorrectReviewPayload>({
    mutationFn: async ({ reviewId, ...body }) =>
      apiRequest<CorrectReviewResponse>(
        `/tenants/me/reviews/${reviewId}/correct`,
        { method: "POST", body },
      ),
    onSuccess: (_data, { reviewId }) => {
      queryClient.invalidateQueries({ queryKey: ["review-detail", reviewId] });
      queryClient.invalidateQueries({ queryKey: ["reviews"] });
      queryClient.invalidateQueries({ queryKey: ["executive-overview"] });
      // W3 — duygu/kategori düzeltmesi /reviews/summary panelinin
      // dağılımlarını da değiştirir (sentiment/categories/quality).
      queryClient.invalidateQueries({ queryKey: ["reviews-summary"] });
    },
  });
}

// filters.date_from/date_to carry YYYY-MM-DD (url-state-patterns.md
// kuralı — ISO datetime DEĞİL). Backend `date_to` alanı ham `<=`
// karşılaştırması yapıyor (review_list_service.py); bare "YYYY-MM-DD"
// T00:00:00'a parse olur ve tüm gün dışarıda kalır — use-analytics.ts
// ile aynı 1-günlük timezone-slide deneyimi. Burada da yerel gün
// başı/sonu ISO'ya genişletilir.
function dateOnlyToLocalIso(value: string | undefined, endOfDay: boolean): string | undefined {
  if (!value) return undefined;
  const d = new Date(`${value}${endOfDay ? "T23:59:59" : "T00:00:00"}`);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

/**
 * Filter-only query params — SAME surface as GET /tenants/me/reviews
 * minus limit/offset/order (list-only pagination/sort; the summary
 * endpoint doesn't accept them). Exported so useReviewSummary reuses
 * this EXACT builder instead of a second hand-maintained copy — panel
 * counts must always match the list 1:1 (task W3 requirement).
 */
export function buildReviewFilterParams(filters: ReviewListFiltersExt): URLSearchParams {
  const params = new URLSearchParams();
  const dateFrom = dateOnlyToLocalIso(filters.date_from, false);
  const dateTo = dateOnlyToLocalIso(filters.date_to, true);
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  if (filters.sentiment_labels?.length) {
    params.set("sentiment_labels", filters.sentiment_labels.join(","));
  }
  if (filters.has_ticket !== undefined) {
    params.set("has_ticket", String(filters.has_ticket));
  }
  if (filters.batch_job_id) params.set("batch_job_id", filters.batch_job_id);
  if (filters.source_types?.length) {
    params.set("source_types", filters.source_types.join(","));
  }
  if (filters.decisions?.length) {
    params.set("decisions", filters.decisions.join(","));
  }
  if (filters.perspective_codes?.length) {
    params.set("perspective_codes", filters.perspective_codes.join(","));
  }
  if (filters.primary_categories?.length) {
    params.set("primary_categories", filters.primary_categories.join(","));
  }
  // 2026-08-20 — Boyutlar filtreleri (case-insensitive eşleşir, backend
  // tarafında). Ad eşlemesi: field (tekil, dimension-values ucu) ↔
  // filtre param'ı (çoğul, burada + reviews/page.tsx DIMENSION_FILTER_
  // CONFIGS'te aynı sırayla tutuluyor).
  if (filters.channels?.length) {
    params.set("channels", filters.channels.join(","));
  }
  if (filters.business_segments?.length) {
    params.set("business_segments", filters.business_segments.join(","));
  }
  if (filters.product_lines?.length) {
    params.set("product_lines", filters.product_lines.join(","));
  }
  if (filters.customer_tiers?.length) {
    params.set("customer_tiers", filters.customer_tiers.join(","));
  }
  if (filters.entered_bys?.length) {
    params.set("entered_bys", filters.entered_bys.join(","));
  }
  if (filters.sources?.length) {
    params.set("sources", filters.sources.join(","));
  }
  // Sprint 9.5.1 B1.1 — heatmap drilldown time-bucket filters. Each
  // is a single integer; the backend route applies the matching
  // EXTRACT predicate. Skipping them when undefined keeps the URL
  // short on the default case (parent reviews page state-mirror
  // pattern relies on "missing param == default").
  if (filters.hour_of_day !== undefined) {
    params.set("hour_of_day", String(filters.hour_of_day));
  }
  if (filters.day_of_week !== undefined) {
    params.set("day_of_week", String(filters.day_of_week));
  }
  if (filters.week_of_year !== undefined) {
    params.set("week_of_year", String(filters.week_of_year));
  }
  if (filters.month !== undefined) {
    params.set("month", String(filters.month));
  }
  if (filters.search) params.set("search", filters.search);
  // 2026-08-18 (WS2 veri kalitesi) — quality_flags doluysa backend
  // include_flagged'i yok sayar; yalnız açık false'u gönderiyoruz
  // (varsayılan true ile URL'i kirletmemek için).
  if (filters.quality_flags?.length) {
    params.set("quality_flags", filters.quality_flags.join(","));
  }
  if (filters.include_flagged === false) {
    params.set("include_flagged", "false");
  }
  // W3 — "Soru" filtresi (content_type). Kalite bayrağından bağımsız:
  // aynı satır hem soru hem negatif olabilir, quality_flags gibi
  // include_flagged'i devre dışı bırakmaz.
  if (filters.content_types?.length) {
    params.set("content_types", filters.content_types.join(","));
  }
  return params;
}

function buildQueryString(filters: ReviewListFiltersExt, offset: number, limit: number): string {
  const params = buildReviewFilterParams(filters);
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  if (filters.order_by) params.set("order_by", filters.order_by);
  if (filters.order) params.set("order", filters.order);
  return params.toString();
}

export function useInfiniteReviews(filters: ReviewListFiltersExt, pageSize = 50) {
  const baseQs = buildQueryString(filters, 0, pageSize);
  return useInfiniteQuery<ReviewListResponse>({
    queryKey: ["reviews", baseQs],
    initialPageParam: 0,
    queryFn: async ({ pageParam }) => {
      const offset = typeof pageParam === "number" ? pageParam : 0;
      const qs = buildQueryString(filters, offset, pageSize);
      return apiRequest<ReviewListResponse>(`/tenants/me/reviews?${qs}`);
    },
    getNextPageParam: (lastPage, pages) => {
      const consumed = pages.reduce((sum, p) => sum + p.items.length, 0);
      return consumed >= lastPage.total ? undefined : consumed;
    },
  });
}

export function useReviewDetail(reviewId: string | null) {
  return useQuery<ReviewDetailWithFacts>({
    queryKey: ["review-detail", reviewId],
    queryFn: async () => {
      if (!reviewId) throw new Error("missing reviewId");
      return apiRequest<ReviewDetailWithFacts>(`/tenants/me/reviews/${reviewId}`);
    },
    enabled: reviewId !== null,
  });
}
