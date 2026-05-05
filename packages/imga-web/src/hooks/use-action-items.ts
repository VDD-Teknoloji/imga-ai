// Sprint 8.3.10 — action items CRUD + extract-from-report hook.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";
import type {
  ActionItem,
  ActionItemCreateRequest,
  ActionItemPriority,
  ActionItemStatus,
  ActionItemUpdateRequest,
} from "@/lib/types";

const QUERY_KEY = ["action-items"] as const;

interface ListFilters {
  status?: ActionItemStatus;
  priority?: ActionItemPriority;
  assignee_user_id?: string;
}

function listKey(filters: ListFilters): readonly unknown[] {
  return [
    ...QUERY_KEY,
    {
      status: filters.status ?? null,
      priority: filters.priority ?? null,
      assignee: filters.assignee_user_id ?? null,
    },
  ];
}

function listQs(filters: ListFilters): string {
  const params = new URLSearchParams();
  if (filters.status) params.set("status_filter", filters.status);
  if (filters.priority) params.set("priority", filters.priority);
  if (filters.assignee_user_id) {
    params.set("assignee_user_id", filters.assignee_user_id);
  }
  return params.toString();
}

export function useActionItems(filters: ListFilters = {}) {
  const qs = listQs(filters);
  return useQuery<ActionItem[]>({
    queryKey: listKey(filters),
    queryFn: () =>
      apiRequest<ActionItem[]>(
        qs ? `/tenants/me/action-items?${qs}` : "/tenants/me/action-items",
      ),
  });
}

export function useCreateActionItem() {
  const qc = useQueryClient();
  return useMutation<ActionItem, Error, ActionItemCreateRequest>({
    mutationFn: (body) =>
      apiRequest<ActionItem>("/tenants/me/action-items", {
        method: "POST",
        body,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}

export function useUpdateActionItem() {
  const qc = useQueryClient();
  return useMutation<
    ActionItem,
    Error,
    { id: string; body: ActionItemUpdateRequest }
  >({
    mutationFn: ({ id, body }) =>
      apiRequest<ActionItem>(`/tenants/me/action-items/${id}`, {
        method: "PATCH",
        body,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}

export function useDeleteActionItem() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (id) =>
      apiRequest<void>(`/tenants/me/action-items/${id}`, {
        method: "DELETE",
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}

export function useExtractFromReport() {
  const qc = useQueryClient();
  return useMutation<ActionItem[], Error, string>({
    mutationFn: (reportId) =>
      apiRequest<ActionItem[]>(
        `/tenants/me/action-items/extract-from-report/${reportId}`,
        { method: "POST" },
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: QUERY_KEY }),
  });
}
