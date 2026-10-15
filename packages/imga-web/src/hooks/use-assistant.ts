"use client";

// Veri asistanı — POST /tenants/me/assistant/ask, GET /suggestions.
// Sohbet geçmişi istemci tarafında tutulur (sayfa state'i); sunucu
// durumsuzdur ve son 8 turu istemle birlikte alır.

import { useMutation, useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";

export interface AssistantTurn {
  role: "user" | "assistant";
  content: string;
}

export interface AssistantWindow {
  from: string;
  to: string;
  total: number;
  sentiment: Record<string, number>;
  negative_share: number;
  categories: Record<string, { total: number; negatif: number; label: string }>;
  stages: Record<string, { total: number; negatif: number }>;
  content_types: Record<string, number>;
  focus: {
    total: number;
    negatif: number;
    ticket_linked: number;
    share_of_all: number;
    perspectives: { code: string; total: number; label?: string }[];
    dimensions: Record<string, { value: string; total: number }[]>;
    stages: Record<string, number>;
  } | null;
}

export interface AssistantMover {
  code: string;
  label: string;
  current: number;
  previous: number;
  diff: number;
  pct_change: number | null;
  current_negatif: number;
  previous_negatif: number;
}

export interface AssistantQuote {
  ref: number;
  review_id: string;
  text: string;
  date: string;
  source: string | null;
  category: string;
  perspective_code: string | null;
  perspective_label: string | null;
  stage: string | null;
  sentiment: string;
}

export interface AssistantEvidence {
  current: AssistantWindow;
  previous: AssistantWindow;
  overall_delta: {
    total_diff: number;
    total_pct_change: number | null;
    negative_share_diff_points: number;
  };
  focus_delta: {
    total_diff: number;
    total_pct_change: number | null;
    negatif_diff: number;
    negatif_pct_change: number | null;
    share_diff_points: number;
    sample_status: "sufficient" | "insufficient";
  } | null;
  category_movers: AssistantMover[];
  category_fallers: AssistantMover[];
  stage_delta: Record<string, { current: number; previous: number }>;
  quotes: AssistantQuote[];
  data_quality: { excludes_flagged_rows: boolean; stage_unassigned_current: number };
}

export interface AssistantScope {
  period_label: string;
  current: { from: string; to: string };
  previous: { from: string; to: string };
  window_days: number;
  focus_category: string | null;
  focus_category_label: string | null;
  focus_stage: string | null;
  focus_stage_label: string | null;
  focus_sentiment: string | null;
}

export interface AssistantAnswer {
  answer: string;
  highlights: string[];
  follow_ups: string[];
  data_gaps: string[];
  scope: AssistantScope;
  evidence: AssistantEvidence;
  llm_used: boolean;
  model: string | null;
  provider: string | null;
  warnings: string[];
}

export function useAssistantSuggestions() {
  const tenant = useAuthStore((state) => state.activeContext?.tenant_id ?? "");
  return useQuery<{ items: string[] }>({
    queryKey: ["assistant-suggestions", tenant],
    enabled: !!tenant,
    queryFn: ({ signal }) =>
      apiRequest<{ items: string[] }>("/tenants/me/assistant/suggestions", { signal }),
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
}

export function useAskAssistant() {
  return useMutation<AssistantAnswer, Error, { question: string; history: AssistantTurn[] }>({
    mutationFn: ({ question, history }) =>
      apiRequest<AssistantAnswer>("/tenants/me/assistant/ask", {
        method: "POST",
        body: { question, history: history.slice(-8) },
      }),
  });
}
