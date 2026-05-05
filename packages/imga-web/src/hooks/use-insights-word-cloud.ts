// Sprint 8.3.9 — word cloud read hook for /insights wordcloud tab.

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type { WordCloudResponse, WordCloudSentiment } from "@/lib/types";

interface WordCloudFilters {
  sentiment?: WordCloudSentiment;
  taxonomy_code?: string;
  date_from?: string;
  date_to?: string;
  limit_words?: number;
  include_bigrams?: boolean;
}

function queryString(filters: WordCloudFilters): string {
  const params = new URLSearchParams();
  if (filters.sentiment) params.set("sentiment", filters.sentiment);
  if (filters.taxonomy_code) params.set("taxonomy_code", filters.taxonomy_code);
  if (filters.date_from) params.set("date_from", filters.date_from);
  if (filters.date_to) params.set("date_to", filters.date_to);
  params.set("limit_words", String(filters.limit_words ?? 100));
  params.set(
    "include_bigrams",
    String(filters.include_bigrams ?? true),
  );
  return params.toString();
}

export function useInsightsWordCloud(filters: WordCloudFilters) {
  const qs = queryString(filters);
  return useQuery<WordCloudResponse>({
    queryKey: ["insights-word-cloud", qs],
    queryFn: () =>
      apiRequest<WordCloudResponse>(`/tenants/me/insights/word-cloud?${qs}`),
    // Backend cache TTL is 6h; frontend matches so navigating
    // between tabs doesn't re-fire a heavy aggregation.
    staleTime: 6 * 60 * 60 * 1000,
  });
}
