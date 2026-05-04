// Sprint 8.3.7-A — tenant SLA rule CRUD.
//
// Four hooks against /tenants/me/sla-rules/*:
//   * useSlaRules({ include_inactive }) — list (filtered)
//   * useCreateSlaRule — POST
//   * useUpdateSlaRule — PATCH
//   * useDeleteSlaRule — DELETE (soft, is_active=false)

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type {
  SlaRule,
  SlaRuleCreateRequest,
  SlaRuleUpdateRequest,
} from "@/lib/types";

const QUERY_KEY = ["sla-rules"] as const;

interface ListFilters {
  include_inactive?: boolean;
}

function listKey(filters: ListFilters): readonly unknown[] {
  return [...QUERY_KEY, { include_inactive: filters.include_inactive ?? false }];
}

export function useSlaRules(filters: ListFilters = {}) {
  const include = filters.include_inactive ?? false;
  const qs = include ? "?include_inactive=true" : "";
  return useQuery<SlaRule[]>({
    queryKey: listKey(filters),
    queryFn: () => apiRequest<SlaRule[]>(`/tenants/me/sla-rules${qs}`),
  });
}

export function useCreateSlaRule() {
  const qc = useQueryClient();
  return useMutation<SlaRule, Error, SlaRuleCreateRequest>({
    mutationFn: (body) =>
      apiRequest<SlaRule>("/tenants/me/sla-rules", {
        method: "POST",
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}

export function useUpdateSlaRule() {
  const qc = useQueryClient();
  return useMutation<
    SlaRule,
    Error,
    { id: string; body: SlaRuleUpdateRequest }
  >({
    mutationFn: ({ id, body }) =>
      apiRequest<SlaRule>(`/tenants/me/sla-rules/${id}`, {
        method: "PATCH",
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}

export function useDeleteSlaRule() {
  const qc = useQueryClient();
  return useMutation<SlaRule, Error, string>({
    mutationFn: (id) =>
      apiRequest<SlaRule>(`/tenants/me/sla-rules/${id}`, {
        method: "DELETE",
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QUERY_KEY });
    },
  });
}
