// Sprint 8.3.1 reviews list + detail hooks.

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { ReviewDetail, ReviewListFilters, ReviewListResponse } from "@/lib/types";

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
    },
  });
}

function buildQueryString(filters: ReviewListFilters, offset: number, limit: number): string {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
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
  if (filters.order_by) params.set("order_by", filters.order_by);
  if (filters.order) params.set("order", filters.order);
  return params.toString();
}

export function useInfiniteReviews(filters: ReviewListFilters, pageSize = 50) {
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
  return useQuery<ReviewDetail>({
    queryKey: ["review-detail", reviewId],
    queryFn: async () => {
      if (!reviewId) throw new Error("missing reviewId");
      return apiRequest<ReviewDetail>(`/tenants/me/reviews/${reviewId}`);
    },
    enabled: reviewId !== null,
  });
}
