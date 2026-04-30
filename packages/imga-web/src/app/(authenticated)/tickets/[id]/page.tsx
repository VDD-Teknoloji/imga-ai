"use client";

import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { notFound, useParams } from "next/navigation";

import { TicketActionBar } from "@/components/tickets/ticket-action-bar";
import { TicketSidePanel } from "@/components/tickets/ticket-side-panel";
import { TicketTimeline } from "@/components/tickets/ticket-timeline";
import { Skeleton } from "@/components/ui/skeleton";
import { useCategoryLabelMap } from "@/hooks/use-categories";
import { useTicket } from "@/hooks/use-ticket";
import { ApiError } from "@/lib/api-client";

/**
 * Single-ticket detail page. Two-column layout:
 *
 *   left (flex-1)  — back-link, title, summary, action bar, timeline
 *   right (320px)  — TicketSidePanel (state, priority, assignee,
 *                    timestamps, cancellation reason if any)
 *
 * On viewports below `lg` the columns stack: detail on top, side
 * panel below.
 *
 * Action bar visibility + button set is fully role + state driven
 * (see TicketActionBar). Viewers see no buttons.
 */
export default function TicketDetailPage() {
  const params = useParams<{ id: string }>();
  const ticketId = params.id;

  const ticket = useTicket(ticketId);
  const labelMap = useCategoryLabelMap();

  if (ticket.isError) {
    if (ticket.error instanceof ApiError && ticket.error.status === 404) {
      notFound();
    }
  }

  const data = ticket.data;
  const categoryLabel = data ? labelMap.data?.get(data.category_id) : undefined;

  return (
    <main className="mx-auto w-full max-w-7xl space-y-6 p-6 md:p-8">
      <Link
        href="/tickets"
        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
      >
        <ChevronLeft className="size-4" aria-hidden />
        Ticket listesi
      </Link>

      {ticket.isLoading ? (
        <DetailSkeleton />
      ) : ticket.isError ? (
        <p className="text-destructive py-12 text-center text-sm">Ticket yüklenemedi.</p>
      ) : !data ? null : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="space-y-6">
            <header className="space-y-2">
              <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">{data.title}</h1>
              {data.summary ? (
                <p className="text-muted-foreground text-sm whitespace-pre-wrap">
                  {data.summary}
                </p>
              ) : null}
            </header>

            <TicketActionBar ticket={data} />

            <TicketTimeline ticketId={data.id} />
          </div>

          <TicketSidePanel ticket={data} categoryLabel={categoryLabel} />
        </div>
      )}
    </main>
  );
}

function DetailSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
      <div className="space-y-6">
        <Skeleton className="h-9 w-3/4" />
        <Skeleton className="h-20" />
        <Skeleton className="h-9 w-48" />
        <Skeleton className="h-32" />
      </div>
      <Skeleton className="h-96" />
    </div>
  );
}
