// Sprint 9.0.5-B B — pending webhooks hooks.
//
// Backs the /pending-webhooks page and the sidebar's pending-count
// badge. Three hooks:
//   * useTenantPendingWebhooks(filter, page) — paginated list +
//     30s polling refresh on the active filter.
//   * useDispatchPendingWebhook() — POST /{id}/dispatch.
//   * useCancelPendingWebhook() — POST /{id}/cancel.
//
// The list query polls every 30s when the page is mounted so a new
// breach (queued by the SLA engine on a tenant in manual mode)
// shows up without a manual refresh. Polling stops when the page
// unmounts; the badge counter on the sidebar uses the same query
// key so it stays in sync without a duplicate fetch.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

export type PendingWebhookStatus =
  | "pending"
  | "sent"
  | "failed"
  | "dismissed";

export interface PendingWebhookEvent {
  id: string;
  sla_rule_id: string | null;
  review_id: string | null;
  webhook_target: "slack" | "teams";
  channel: string | null;
  payload: Record<string, unknown>;
  status: PendingWebhookStatus;
  retry_count: number;
  last_error: string | null;
  created_at: string;
  sent_at: string | null;
  dismissed_at: string | null;
}

export interface PendingWebhookListResponse {
  events: PendingWebhookEvent[];
  total: number;
  page: number;
  page_size: number;
}

export interface PendingWebhookListFilters {
  status?: PendingWebhookStatus | "all";
  page?: number;
  pageSize?: number;
}

export function useTenantPendingWebhooks(filters: PendingWebhookListFilters = {}) {
  const status = filters.status ?? "pending";
  const page = filters.page ?? 1;
  const pageSize = filters.pageSize ?? 25;
  const params = new URLSearchParams();
  if (status !== "all") params.set("status_filter", status);
  params.set("page", String(page));
  params.set("limit", String(pageSize));

  return useQuery<PendingWebhookListResponse>({
    queryKey: ["pending-webhooks", status, page, pageSize],
    queryFn: async () =>
      apiRequest<PendingWebhookListResponse>(
        `/tenants/me/pending-webhooks?${params.toString()}`,
      ),
    refetchInterval: 30_000,
  });
}

export function usePendingWebhookCount() {
  // Cheap "are there any pending?" probe for the sidebar badge.
  // Queries page 1, reads ``total``; doesn't render rows.
  return useQuery<number>({
    queryKey: ["pending-webhooks-count"],
    queryFn: async () => {
      const r = await apiRequest<PendingWebhookListResponse>(
        "/tenants/me/pending-webhooks?status_filter=pending&page=1&limit=1",
      );
      return r.total ?? 0;
    },
    refetchInterval: 30_000,
  });
}

export function useDispatchPendingWebhook() {
  const queryClient = useQueryClient();
  return useMutation<PendingWebhookEvent, Error, string>({
    mutationFn: async (id) =>
      apiRequest<PendingWebhookEvent>(
        `/tenants/me/pending-webhooks/${id}/dispatch`,
        { method: "POST" },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pending-webhooks"] });
      queryClient.invalidateQueries({ queryKey: ["pending-webhooks-count"] });
    },
  });
}

export function useCancelPendingWebhook() {
  const queryClient = useQueryClient();
  return useMutation<PendingWebhookEvent, Error, string>({
    mutationFn: async (id) =>
      apiRequest<PendingWebhookEvent>(
        `/tenants/me/pending-webhooks/${id}/cancel`,
        { method: "POST" },
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pending-webhooks"] });
      queryClient.invalidateQueries({ queryKey: ["pending-webhooks-count"] });
    },
  });
}
