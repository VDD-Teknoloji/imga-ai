// Sprint 13 — kategori bazlı ticket yönlendirme kuralları + email outbox.
//
// Beş hook — /tenants/me/ticket-routing/*:
//   * useTicketRoutingRules — list
//   * useCreateTicketRoutingRule — POST (409 = kategori için kural zaten var)
//   * useUpdateTicketRoutingRule — PATCH (kısmi)
//   * useDeleteTicketRoutingRule — DELETE (soft, is_active=false)
//   * useTicketRoutingOutbox — GET /outbox (son e-posta bildirimleri)
//
// Tipler bilinçli olarak burada — lib/types.ts başka ajanların sahasında.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiRequest } from "@/lib/api-client";

export interface TicketRoutingRule {
  id: string;
  category_code: string;
  notify_email: string;
  assignee_user_id: string | null;
  sla_hours: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface TicketRoutingRulesResponse {
  rules: TicketRoutingRule[];
}

export interface TicketRoutingRuleCreateRequest {
  category_code: string;
  notify_email: string;
  assignee_user_id?: string;
  sla_hours?: number;
}

export interface TicketRoutingRuleUpdateRequest {
  category_code?: string;
  notify_email?: string;
  assignee_user_id?: string | null;
  sla_hours?: number | null;
  is_active?: boolean;
}

export type OutboxEventType = "ticket_opened" | "sla_breach";
export type OutboxEmailStatus = "pending" | "sent" | "failed";

export interface OutboxEmail {
  id: string;
  to_email: string;
  subject: string;
  event_type: OutboxEventType;
  status: OutboxEmailStatus;
  attempts: number;
  last_error: string | null;
  related_ticket_id: string | null;
  created_at: string;
  sent_at: string | null;
}

interface OutboxResponse {
  emails: OutboxEmail[];
}

const RULES_KEY = ["ticket-routing", "rules"] as const;
const OUTBOX_KEY = ["ticket-routing", "outbox"] as const;

export function useTicketRoutingRules() {
  return useQuery<TicketRoutingRule[]>({
    queryKey: RULES_KEY,
    queryFn: async () => {
      const data = await apiRequest<TicketRoutingRulesResponse>(
        "/tenants/me/ticket-routing",
      );
      return data.rules;
    },
  });
}

export function useCreateTicketRoutingRule() {
  const qc = useQueryClient();
  return useMutation<TicketRoutingRule, Error, TicketRoutingRuleCreateRequest>({
    mutationFn: (body) =>
      apiRequest<TicketRoutingRule>("/tenants/me/ticket-routing", {
        method: "POST",
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: RULES_KEY });
    },
  });
}

export function useUpdateTicketRoutingRule() {
  const qc = useQueryClient();
  return useMutation<
    TicketRoutingRule,
    Error,
    { id: string; body: TicketRoutingRuleUpdateRequest }
  >({
    mutationFn: ({ id, body }) =>
      apiRequest<TicketRoutingRule>(`/tenants/me/ticket-routing/${id}`, {
        method: "PATCH",
        body,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: RULES_KEY });
    },
  });
}

export function useDeleteTicketRoutingRule() {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: async (id) => {
      await apiRequest<unknown>(`/tenants/me/ticket-routing/${id}`, {
        method: "DELETE",
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: RULES_KEY });
    },
  });
}

export function useTicketRoutingOutbox(limit = 50) {
  return useQuery<OutboxEmail[]>({
    queryKey: [...OUTBOX_KEY, { limit }],
    queryFn: async () => {
      const data = await apiRequest<OutboxResponse>(
        `/tenants/me/ticket-routing/outbox?limit=${limit}`,
      );
      return data.emails;
    },
  });
}
