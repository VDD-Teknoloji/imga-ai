// Sprint 9.3 A — LLM call audit list + summary hooks.

import { useQuery } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

export interface LlmCallAuditRow {
  id: string;
  call_type: string;
  related_entity_type: string | null;
  related_entity_id: string | null;
  prompt_template_key: string | null;
  prompt_template_version: string | null;
  prompt_hash: string;
  model_name: string;
  model_provider: string;
  model_temperature: number | null;
  model_max_tokens: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  duration_ms: number | null;
  success: boolean;
  error_type: string | null;
  error_message: string | null;
  fallback_used: boolean;
  actor_user_id: string | null;
  request_id: string | null;
  created_at: string;
}

export interface LlmAuditListResponse {
  items: LlmCallAuditRow[];
  total: number;
}

export interface DailyUsagePoint {
  day: string;
  call_count: number;
  success_count: number;
  failure_count: number;
  total_tokens: number;
}

export interface LlmAuditSummary {
  days: DailyUsagePoint[];
  total_calls: number;
  total_failures: number;
  total_tokens: number;
}

interface ListFilters {
  call_type?: string;
  success?: boolean;
  limit?: number;
  offset?: number;
}

export function useLlmAuditList(filters: ListFilters = {}) {
  const qs = new URLSearchParams();
  if (filters.call_type) qs.set("call_type", filters.call_type);
  if (filters.success !== undefined) qs.set("success", String(filters.success));
  qs.set("limit", String(filters.limit ?? 100));
  qs.set("offset", String(filters.offset ?? 0));
  const qsStr = qs.toString();
  return useQuery<LlmAuditListResponse>({
    queryKey: ["llm-audit", filters],
    queryFn: () =>
      apiRequest<LlmAuditListResponse>(
        `/tenants/me/llm-audit${qsStr ? `?${qsStr}` : ""}`,
      ),
  });
}

export function useLlmAuditSummary() {
  return useQuery<LlmAuditSummary>({
    queryKey: ["llm-audit", "summary"],
    queryFn: () =>
      apiRequest<LlmAuditSummary>("/tenants/me/llm-audit/summary"),
    staleTime: 60_000,
  });
}
