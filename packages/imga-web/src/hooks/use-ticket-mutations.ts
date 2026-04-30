"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { ApiError, apiRequest } from "@/lib/api-client";
import { TICKET_ACTIONS, type TicketActionId } from "@/lib/ticket-actions";
import type { CancellationReason, Ticket, TicketState } from "@/lib/types";

interface TransitionInput {
  ticketId: string;
  toState: TicketState;
  reason?: string;
  cancellationReason?: CancellationReason;
}

interface AssignInput {
  ticketId: string;
  assigneeUserId: string | null; // null clears
}

interface ActionInput {
  ticketId: string;
  action: TicketActionId;
  cancellationReason?: CancellationReason;
}

/** Centralised cache invalidation — bumps every ticket-bound query. */
function invalidateTicketCaches(qc: ReturnType<typeof useQueryClient>, ticketId: string): void {
  qc.invalidateQueries({ queryKey: ["tickets", "all"] }); // dashboard + list
  qc.invalidateQueries({ queryKey: ["tickets", "detail", ticketId] });
  qc.invalidateQueries({ queryKey: ["tickets", "timeline", ticketId] });
}

/** Map the helper-thrown ApiError to a Turkish toast string. */
function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 403) return "Bu işlem için yetkin yok.";
    if (err.status === 404) return "Ticket bulunamadı.";
    if (err.status === 409) return "Geçersiz durum geçişi veya zaman penceresi doldu.";
    if (err.status === 422) return "Eksik alan: iptal sebebi gerekli.";
  }
  return "İşlem gerçekleştirilemedi.";
}

export function useTicketAction() {
  const qc = useQueryClient();
  return useMutation<Ticket, ApiError, ActionInput>({
    mutationFn: async ({ ticketId, action, cancellationReason }) => {
      const def = TICKET_ACTIONS[action];

      // quick_resolve has its own endpoint (POST /quick-resolve) and
      // performs two transitions atomically on the backend.
      if (action === "quick_resolve") {
        return apiRequest<Ticket>(`/tickets/${ticketId}/quick-resolve`, {
          method: "POST",
        });
      }

      if (def.toState === null) {
        throw new ApiError(500, `Action ${action} has no toState mapping`);
      }

      return apiRequest<Ticket>(`/tickets/${ticketId}/transition`, {
        method: "POST",
        body: {
          to_state: def.toState,
          ...(cancellationReason ? { cancellation_reason: cancellationReason } : {}),
        },
      });
    },
    onSuccess: (_data, vars) => {
      const def = TICKET_ACTIONS[vars.action];
      toast.success(`${def.label} işlemi tamamlandı`);
      invalidateTicketCaches(qc, vars.ticketId);
    },
    onError: (err) => {
      toast.error(describeError(err));
    },
  });
}

export function useTicketAssign() {
  const qc = useQueryClient();
  return useMutation<Ticket, ApiError, AssignInput>({
    mutationFn: async ({ ticketId, assigneeUserId }) => {
      return apiRequest<Ticket>(`/tickets/${ticketId}/assign`, {
        method: "POST",
        body: { assignee_user_id: assigneeUserId },
      });
    },
    onSuccess: (_data, vars) => {
      toast.success(vars.assigneeUserId === null ? "Atama kaldırıldı" : "Atama güncellendi");
      invalidateTicketCaches(qc, vars.ticketId);
    },
    onError: (err) => {
      toast.error(describeError(err));
    },
  });
}

/** Lower-level transition mutation if a caller wants the raw to_state
 * path instead of the action-id wrapper. Currently unused; kept as a
 * stable export for Sprint 7.7's bulk-action UI. */
export function useTicketTransition() {
  const qc = useQueryClient();
  return useMutation<Ticket, ApiError, TransitionInput>({
    mutationFn: async ({ ticketId, toState, reason, cancellationReason }) => {
      return apiRequest<Ticket>(`/tickets/${ticketId}/transition`, {
        method: "POST",
        body: {
          to_state: toState,
          ...(reason ? { reason } : {}),
          ...(cancellationReason ? { cancellation_reason: cancellationReason } : {}),
        },
      });
    },
    onSuccess: (_data, vars) => {
      invalidateTicketCaches(qc, vars.ticketId);
    },
    onError: (err) => {
      toast.error(describeError(err));
    },
  });
}
