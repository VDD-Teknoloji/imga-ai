"use client";

import { useMemo, useState } from "react";

import { CancelDialog } from "@/components/tickets/cancel-dialog";
import { Button } from "@/components/ui/button";
import { useTicketAction } from "@/hooks/use-ticket-mutations";
import { useAuthStore } from "@/lib/auth-store";
import {
  TICKET_ACTIONS,
  availableActions,
  type TicketActionId,
} from "@/lib/ticket-actions";
import type { CancellationReason, Ticket, UserTenantRole } from "@/lib/types";

interface TicketActionBarProps {
  ticket: Ticket;
}

/**
 * State-aware action buttons for a ticket. Reads the user's role from
 * the auth store and renders only buttons the backend would accept.
 *
 *   - VIEWER → renders nothing (read-only).
 *   - ANALYST → claim / wait_customer / resume / resolve / close /
 *               regression / quick_resolve, plus self-only un-claim
 *               and OPEN→CANCELLED.
 *   - TENANT_ADMIN → all of the above + reopen, uncancel,
 *               IN_PROGRESS→CANCELLED.
 *
 * The "Cancel" action opens a dialog because the backend requires a
 * cancellation_reason (false_positive | duplicate | spam | off_topic
 * | other). All other actions fire directly.
 */
export function TicketActionBar({ ticket }: TicketActionBarProps) {
  const user = useAuthStore((s) => s.user);
  const activeContext = useAuthStore((s) => s.activeContext);
  const action = useTicketAction();

  const [cancelDialogOpen, setCancelDialogOpen] = useState(false);

  const actionIds = useMemo<TicketActionId[]>(() => {
    if (!user) return [];
    return availableActions({
      ticketState: ticket.state,
      ticketAssigneeId: ticket.assigned_to_user_id,
      userRole: (activeContext?.role ?? null) as UserTenantRole | null,
      userId: user.id,
      isSuperAdmin: user.is_super_admin,
    });
  }, [ticket.state, ticket.assigned_to_user_id, user, activeContext]);

  if (actionIds.length === 0) {
    return null; // viewer or no role
  }

  function handleClick(id: TicketActionId) {
    if (id === "cancel") {
      setCancelDialogOpen(true);
      return;
    }
    action.mutate({ ticketId: ticket.id, action: id });
  }

  function handleCancelConfirm(reason: CancellationReason) {
    action.mutate(
      { ticketId: ticket.id, action: "cancel", cancellationReason: reason },
      {
        onSuccess: () => setCancelDialogOpen(false),
      },
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {actionIds.map((id) => {
        const def = TICKET_ACTIONS[id];
        return (
          <Button
            key={id}
            variant={def.variant ?? "default"}
            size="sm"
            onClick={() => handleClick(id)}
            disabled={action.isPending}
          >
            {def.label}
          </Button>
        );
      })}
      <CancelDialog
        open={cancelDialogOpen}
        onOpenChange={setCancelDialogOpen}
        onConfirm={handleCancelConfirm}
        isPending={action.isPending}
      />
    </div>
  );
}
