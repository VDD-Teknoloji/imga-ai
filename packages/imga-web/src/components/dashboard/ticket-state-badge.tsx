import { TICKET_STATE_BADGE_CLASS, TICKET_STATE_LABELS } from "@/lib/ticket-helpers";
import type { TicketState } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Colour-coded inline badge for a ticket's state. Reused by recent
 * tickets table + (Sprint 7.6.4) the ticket list page.
 */
export function TicketStateBadge({ state, className }: { state: TicketState; className?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        TICKET_STATE_BADGE_CLASS[state],
        className,
      )}
    >
      {TICKET_STATE_LABELS[state]}
    </span>
  );
}
