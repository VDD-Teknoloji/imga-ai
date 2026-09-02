// W3 — GET /tenants/me/reviews/summary. Filter-reactive summary panel
// next to the reviews list (see reviews/page.tsx). The endpoint takes
// the EXACT same filter surface as GET /tenants/me/reviews (minus
// limit/offset/order) — buildReviewFilterParams from use-reviews.ts is
// reused verbatim so the panel's counts never drift from the list's.
//
// Response types mirror packages/imga-api/src/imga_api/routes/
// tenant_reviews.py's pydantic models field-for-field. Kept local here
// rather than in lib/types.ts — same "parallel backend agent" caution
// as ReviewFacts in use-reviews.ts; this is a brand-new response shape
// with no existing callers to break.

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

import { buildReviewFilterParams, type ReviewListFiltersExt } from "@/hooks/use-reviews";

export interface ReviewSummaryNps {
  promoter: number;
  passive: number;
  detractor: number;
  with_nps: number;
  score: number | null;
}

export interface ReviewSummaryQuality {
  clean: number;
  duplicate: number;
  empty: number;
  informational: number;
  meaningless: number;
}

export interface ReviewSummaryCategoryCount {
  code: string;
  count: number;
  negative_count: number;
}

/** Shared shape for the sources list (value + count) — same fields as
 *  DimensionValueRow (use-dimension-values.ts) but kept separate since
 *  it's a distinct backend response model (DimensionValueItem). */
export interface ReviewSummaryValueCount {
  value: string;
  count: number;
}

export interface ReviewSummaryEnteredBy {
  value: string;
  total: number;
  flagged: number;
  question: number;
  negative: number;
}

export interface ReviewSummaryDaily {
  date: string;
  count: number;
  negative: number;
}

export interface ReviewSummaryTopQuestion {
  text: string;
  count: number;
}

export interface ReviewSummaryResponse {
  total: number;
  sentiment: Record<string, number>;
  avg_sentiment_score: number | null;
  nps: ReviewSummaryNps;
  sources: ReviewSummaryValueCount[];
  categories: ReviewSummaryCategoryCount[];
  quality: ReviewSummaryQuality;
  question_count: number;
  /** All five ContentType keys present once live (0 for absent types) —
   *  see lib/types.ts CONTENT_TYPES. Optional per the "parallel backend
   *  agent" caution atop this file: web and api images deploy
   *  independently, and this field ships in the same rollout as this
   *  UI change, so it can briefly be absent from an old api response.
   *  question_count above stays for backward compat. */
  content_types?: Record<string, number>;
  top_questions: ReviewSummaryTopQuestion[];
  entered_by: ReviewSummaryEnteredBy[];
  daily: ReviewSummaryDaily[];
  ticket_linked: number;
  /** F1 (2026-09-02) — viral olumsuz tweet sayacı (failing-processes-card.tsx).
   *  Backend alan adı birebir bu; tenant_reviews.py'nin ReviewSummaryResponse'una
   *  eşzamanlı bir backend görevi ekledi (kontrol edildi, kodda mevcut).
   *  Web + api bağımsız deploy edildiğinden yine de defansif okunuyor:
   *  tüketici tarafı `> 0` karşılaştırmasıyla okur — bir ortamda alan
   *  henüz `undefined` gelse bile `undefined > 0` `false` olduğundan
   *  sessizce 0 gibi davranır. */
  viral_negative_count: number;
}

/** filters must be the SAME object the list uses (prop-drilled from
 *  ReviewsPageInner) — this hook does not read the URL itself, per
 *  docs/agent-rules/url-state-patterns.md (one Suspense boundary, one
 *  useSearchParams call for the whole page). */
export function useReviewSummary(filters: ReviewListFiltersExt) {
  const qs = buildReviewFilterParams(filters).toString();
  return useQuery<ReviewSummaryResponse>({
    queryKey: ["reviews-summary", qs],
    queryFn: async () =>
      apiRequest<ReviewSummaryResponse>(`/tenants/me/reviews/summary?${qs}`),
  });
}
