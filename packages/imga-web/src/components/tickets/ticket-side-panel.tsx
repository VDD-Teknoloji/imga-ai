"use client";

import { TicketStateBadge } from "@/components/dashboard/ticket-state-badge";
import { TicketPriorityBadge } from "@/components/tickets/ticket-priority-badge";
import { Button } from "@/components/ui/button";
import { useTicketAssign } from "@/hooks/use-ticket-mutations";
import { useAuthStore } from "@/lib/auth-store";
import { CANCELLATION_REASON_LABELS } from "@/lib/ticket-actions";
import type { Ticket } from "@/lib/types";

interface TicketSidePanelProps {
  ticket: Ticket;
  categoryLabel: string | undefined;
}

/**
 * Right rail of the detail page. Surfaces the ticket's metadata
 * (state badge, priority, category, timestamps, cancellation
 * reason if any) and offers the assignment quick-actions:
 *
 *   - Unassigned   → "Bana ata"
 *   - Assigned to me → "Bırak"
 *   - Assigned to other → "Bana al" (if user is admin)
 *
 * Full assignee picker (showing other users' names) needs the
 * Sprint 7.5.5 tenant directory endpoint (roadmap A7).
 */
export function TicketSidePanel({ ticket, categoryLabel }: TicketSidePanelProps) {
  const user = useAuthStore((s) => s.user);
  const role = useAuthStore((s) => s.activeContext?.role);
  const assign = useTicketAssign();

  const canMutate =
    !!user &&
    !!role &&
    role !== "viewer" &&
    !["closed", "cancelled"].includes(ticket.state);

  const isMine = user?.id === ticket.assigned_to_user_id;
  const isUnassigned = ticket.assigned_to_user_id === null;
  const isAdmin = role === "tenant_admin" || user?.is_super_admin;

  return (
    <aside className="bg-card flex w-full flex-col gap-5 rounded-lg border p-5">
      <Section label="Durum">
        <TicketStateBadge state={ticket.state} className="text-sm" />
      </Section>

      <Section label="Öncelik">
        <TicketPriorityBadge priority={ticket.priority} className="text-sm" />
      </Section>

      <Section label="Kategori">
        <span className="text-sm">{categoryLabel ?? "—"}</span>
      </Section>

      <Section label="Atanan">
        <span className="text-sm">
          {isUnassigned ? "Atanmamış" : isMine ? "Sana" : "Başka kullanıcı"}
        </span>
        {canMutate ? (
          <div className="flex gap-2 pt-1">
            {isUnassigned ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  assign.mutate({ ticketId: ticket.id, assigneeUserId: user!.id })
                }
                disabled={assign.isPending}
              >
                Bana ata
              </Button>
            ) : isMine ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  assign.mutate({ ticketId: ticket.id, assigneeUserId: null })
                }
                disabled={assign.isPending}
              >
                Bırak
              </Button>
            ) : isAdmin ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  assign.mutate({ ticketId: ticket.id, assigneeUserId: user!.id })
                }
                disabled={assign.isPending}
              >
                Bana al
              </Button>
            ) : null}
          </div>
        ) : null}
      </Section>

      {ticket.state === "cancelled" && ticket.cancellation_reason ? (
        <Section label="İptal sebebi">
          <span className="text-sm">
            {CANCELLATION_REASON_LABELS[ticket.cancellation_reason] ??
              ticket.cancellation_reason}
          </span>
        </Section>
      ) : null}

      <Section label="Açılış">
        <span className="text-muted-foreground text-sm">{formatDate(ticket.opened_at)}</span>
      </Section>

      {ticket.resolved_at ? (
        <Section label="Çözüm">
          <span className="text-muted-foreground text-sm">
            {formatDate(ticket.resolved_at)}
          </span>
        </Section>
      ) : null}

      {ticket.closed_at ? (
        <Section label="Kapanış">
          <span className="text-muted-foreground text-sm">
            {formatDate(ticket.closed_at)}
          </span>
        </Section>
      ) : null}

      {ticket.customer_inbound_received_at ? (
        <Section label="Müşteri yanıtı">
          <span className="text-muted-foreground text-sm">
            {formatDate(ticket.customer_inbound_received_at)}
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

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("tr-TR", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
