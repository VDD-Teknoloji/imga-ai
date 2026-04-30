"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { useTicketTimeline, type TicketTransition } from "@/hooks/use-ticket-timeline";
import { TICKET_STATE_LABELS } from "@/lib/ticket-helpers";

interface TicketTimelineProps {
  ticketId: string;
}

/**
 * Vertical event log of every state transition for the ticket.
 * Backend's GET /tickets/{id}/transitions writes a marker row at
 * creation time (from_state == to_state == "open") so the very
 * first entry is rendered as "Açıldı"; everything after is a
 * X → Y transition.
 */
export function TicketTimeline({ ticketId }: TicketTimelineProps) {
  const timeline = useTicketTimeline(ticketId);

  return (
    <section className="space-y-3">
      <h2 className="text-base font-semibold tracking-tight">Geçmiş</h2>

      {timeline.isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
      ) : timeline.isError ? (
        <p className="text-destructive text-sm">Geçmiş yüklenemedi.</p>
      ) : !timeline.data || timeline.data.length === 0 ? (
        <p className="text-muted-foreground text-sm">Henüz aktivite yok.</p>
      ) : (
        <ol className="border-border space-y-3 border-l pl-5">
          {timeline.data.map((event) => (
            <TimelineEvent key={event.id} event={event} />
          ))}
        </ol>
      )}
    </section>
  );
}

function TimelineEvent({ event }: { event: TicketTransition }) {
  const isCreation = event.from_state === event.to_state;
  return (
    <li className="relative">
      <span
        className="bg-primary absolute -left-[1.4rem] top-2 size-2 rounded-full"
        aria-hidden
      />
      <div className="bg-card rounded-md border p-3">
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium">
            {isCreation
              ? "Açıldı"
              : `${TICKET_STATE_LABELS[event.from_state]} → ${TICKET_STATE_LABELS[event.to_state]}`}
          </span>
          <span className="text-muted-foreground text-xs">
            {formatTimelineDate(event.occurred_at)}
          </span>
        </div>
        <p className="text-muted-foreground mt-1 text-xs">
          {event.actor_user_id === null ? "Sistem" : "Kullanıcı"}
          {event.reason ? ` — ${event.reason}` : ""}
        </p>
      </div>
    </li>
  );
}

function formatTimelineDate(iso: string): string {
  return new Date(iso).toLocaleString("tr-TR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
