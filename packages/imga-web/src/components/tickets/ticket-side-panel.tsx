"use client";

import { TicketStateBadge } from "@/components/dashboard/ticket-state-badge";
import { AssigneeDropdown } from "@/components/tickets/assignee-dropdown";
import { TicketPriorityBadge } from "@/components/tickets/ticket-priority-badge";
import { useAuthStore } from "@/lib/auth-store";
import { formatFullDate } from "@/lib/date-format";
import { useTranslation } from "@/lib/i18n/use-translation";
import { CANCELLATION_REASON_LABELS } from "@/lib/ticket-actions";
import type { Ticket } from "@/lib/types";

interface TicketSidePanelProps {
  ticket: Ticket;
  categoryLabel: string | undefined;
}

/**
 * Right rail of the detail page. Sprint 7.7.2 swap: the simple
 * "Bana ata / Bırak / Bana al" buttons are replaced with the new
 * AssigneeDropdown (combobox over /tenants/me/users) so admins
 * can reassign to any tenant member by name.
 */
export function TicketSidePanel({ ticket, categoryLabel }: TicketSidePanelProps) {
  const { t } = useTranslation();
  const user = useAuthStore((s) => s.user);
  const role = useAuthStore((s) => s.activeContext?.role);

  const isAdmin =
    role === "tenant_admin" || user?.is_super_admin === true;
  const canMutate =
    !!user && !!role && role !== "viewer" &&
    !["closed", "cancelled"].includes(ticket.state);

  return (
    <aside className="bg-card flex w-full flex-col gap-5 rounded-lg border p-5">
      <Section label={t("tickets.detail.state")}>
        <TicketStateBadge state={ticket.state} className="text-sm" />
      </Section>

      <Section label={t("tickets.detail.priority")}>
        <TicketPriorityBadge priority={ticket.priority} className="text-sm" />
      </Section>

      <Section label={t("tickets.detail.category")}>
        <span className="text-sm">{categoryLabel ?? "—"}</span>
      </Section>

      <Section label={t("tickets.detail.assignee")}>
        <AssigneeDropdown
          ticketId={ticket.id}
          currentAssigneeId={ticket.assigned_to_user_id}
          isAdmin={isAdmin}
          enabled={canMutate}
        />
      </Section>

      {ticket.state === "cancelled" && ticket.cancellation_reason ? (
        <Section label={t("tickets.detail.cancellationReason")}>
          <span className="text-sm">
            {CANCELLATION_REASON_LABELS[ticket.cancellation_reason] ??
              ticket.cancellation_reason}
          </span>
        </Section>
      ) : null}

      <Section label={t("tickets.detail.openedAt")}>
        <span className="text-muted-foreground text-sm">
          {formatFullDate(ticket.opened_at)}
        </span>
      </Section>

      {ticket.resolved_at ? (
        <Section label={t("tickets.detail.resolvedAt")}>
          <span className="text-muted-foreground text-sm">
            {formatFullDate(ticket.resolved_at)}
          </span>
        </Section>
      ) : null}

      {ticket.closed_at ? (
        <Section label={t("tickets.detail.closedAt")}>
          <span className="text-muted-foreground text-sm">
            {formatFullDate(ticket.closed_at)}
          </span>
        </Section>
      ) : null}

      {ticket.customer_inbound_received_at ? (
        <Section label={t("tickets.detail.customerReplyAt")}>
          <span className="text-muted-foreground text-sm">
            {formatFullDate(ticket.customer_inbound_received_at)}
          </span>
        </Section>
      ) : null}
    </aside>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-muted-foreground text-xs font-medium">{label}</span>
      {children}
    </div>
  );
}
