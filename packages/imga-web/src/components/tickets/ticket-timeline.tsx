"use client";

import {
  ArrowRight,
  CirclePlay,
  MessageSquare,
  MessageSquareReply,
  UserMinus,
  UserPlus,
  UserRoundCog,
} from "lucide-react";
import { useMemo } from "react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { useTicketTimeline } from "@/hooks/use-ticket-timeline";
import { useTenantMembers } from "@/hooks/use-tenant-members";
import { useAuthStore } from "@/lib/auth-store";
import { formatTimelineDate } from "@/lib/date-format";
import { useTranslation } from "@/lib/i18n/use-translation";
import { TICKET_STATE_LABELS } from "@/lib/ticket-helpers";
import type { TenantMember, TimelineEvent } from "@/lib/types";
import { COMMENT_KIND_LABELS, userInitials } from "@/lib/user-helpers";
import { cn } from "@/lib/utils";

interface TicketTimelineProps {
  ticketId: string;
}

/**
 * Polymorphic timeline: backend's GET /tickets/{id}/timeline merges
 * state_transitions and comments into a single chronologically-sorted
 * stream. We discriminate per ``event.type`` and render two distinct
 * card variants:
 *
 *   * state_transition — creation marker (from == to == "open") shows
 *     as "Açıldı"; everything else is "X → Y" with optional reason.
 *   * comment          — internal_note vs customer_reply badge,
 *     archived rows render with strikethrough body and a muted
 *     "Arşivlenmiş" badge so the historical record stays visible.
 *
 * Backend doesn't yet emit assignment_changed events (assigns write
 * to audit_logs but not to the timeline). Sprint 7.7.2 closeout
 * flags this as a backend gap.
 */
export function TicketTimeline({ ticketId }: TicketTimelineProps) {
  const { t } = useTranslation();
  const timeline = useTicketTimeline(ticketId);
  const activeTenantId = useAuthStore((s) => s.activeContext?.tenant_id);
  const members = useTenantMembers(activeTenantId);

  const memberMap = useMemo<ReadonlyMap<string, TenantMember>>(() => {
    const map = new Map<string, TenantMember>();
    for (const m of members.data ?? []) {
      map.set(m.user_id, m);
    }
    return map;
  }, [members.data]);

  return (
    <section className="space-y-3">
      <h2 className="text-base font-semibold tracking-tight">{t("tickets.timeline.title")}</h2>

      {timeline.isLoading ? (
        <div className="space-y-2">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-12" />
          ))}
        </div>
      ) : timeline.isError ? (
        <p className="text-destructive text-sm">{t("tickets.timeline.loadError")}</p>
      ) : !timeline.data || timeline.data.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("tickets.timeline.empty")}</p>
      ) : (
        <ol className="border-border space-y-3 border-l pl-5">
          {timeline.data.map((event) => (
            <TimelineRow
              key={`${event.type}-${event.id}`}
              event={event}
              actor={
                event.actor_user_id
                  ? memberMap.get(event.actor_user_id)
                  : undefined
              }
              fromMember={
                event.from_user_id
                  ? memberMap.get(event.from_user_id)
                  : undefined
              }
              toMember={
                event.to_user_id
                  ? memberMap.get(event.to_user_id)
                  : undefined
              }
            />
          ))}
        </ol>
      )}
    </section>
  );
}

interface TimelineRowProps {
  event: TimelineEvent;
  actor: TenantMember | undefined;
  /** Resolved from event.from_user_id (assignment_changed branch). */
  fromMember?: TenantMember | undefined;
  /** Resolved from event.to_user_id (assignment_changed branch). */
  toMember?: TenantMember | undefined;
}

function TimelineRow({ event, actor, fromMember, toMember }: TimelineRowProps) {
  if (event.type === "state_transition") {
    return <TransitionRow event={event} actor={actor} />;
  }
  if (event.type === "comment") {
    return <CommentRow event={event} actor={actor} />;
  }
  return (
    <AssignmentRow
      event={event}
      actor={actor}
      fromMember={fromMember}
      toMember={toMember}
    />
  );
}

// --- state_transition ---------------------------------------------------

function TransitionRow({ event, actor }: TimelineRowProps) {
  const { t } = useTranslation();
  const fromState = event.from_state;
  const toState = event.to_state;
  const isCreation =
    fromState != null && toState != null && fromState === toState;

  return (
    <li className="relative">
      <span
        className="bg-primary absolute -left-[1.4rem] top-2 size-2 rounded-full"
        aria-hidden
      />
      <div className="bg-card rounded-md border p-3">
        <div className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-2 text-sm font-medium">
            {isCreation ? (
              <>
                <CirclePlay className="text-primary size-3.5" aria-hidden />
                {t("tickets.timeline.created")}
              </>
            ) : fromState && toState ? (
              <>
                {TICKET_STATE_LABELS[fromState]}
                <ArrowRight className="text-muted-foreground size-3.5" aria-hidden />
                {TICKET_STATE_LABELS[toState]}
              </>
            ) : (
              t("tickets.timeline.stateUpdated")
            )}
          </span>
          <span className="text-muted-foreground text-xs">
            {formatTimelineDate(event.occurred_at)}
          </span>
        </div>
        <p className="text-muted-foreground mt-1 text-xs">
          {actor
            ? actor.full_name
            : event.actor_user_id
              ? t("tickets.timeline.actorUser")
              : t("tickets.timeline.actorSystem")}
          {event.reason ? ` — ${event.reason}` : ""}
        </p>
      </div>
    </li>
  );
}

// --- comment ------------------------------------------------------------

// --- assignment_changed (Sprint 7.7.2 patch) ----------------------------

interface AssignmentRowProps {
  event: TimelineEvent;
  actor: TenantMember | undefined;
  fromMember: TenantMember | undefined;
  toMember: TenantMember | undefined;
}

function AssignmentRow({
  event,
  actor,
  fromMember,
  toMember,
}: AssignmentRowProps) {
  const { t } = useTranslation();
  const isAssign = event.from_user_id == null && event.to_user_id != null;
  const isUnassign = event.from_user_id != null && event.to_user_id == null;
  const Icon = isAssign ? UserPlus : isUnassign ? UserMinus : UserRoundCog;

  // Friendly labels for either side. Falls through to "Atanmamış" when
  // null and to "Bilinmeyen kullanıcı" for users that the directory
  // can't resolve (e.g. soft-deleted member; FK is SET NULL).
  const fromLabel =
    event.from_user_id == null
      ? t("tickets.common.unassigned")
      : (fromMember?.full_name ?? t("tickets.common.unknownUser"));
  const toLabel =
    event.to_user_id == null
      ? t("tickets.common.unassigned")
      : (toMember?.full_name ?? t("tickets.common.unknownUser"));

  return (
    <li className="relative">
      <span
        className="bg-secondary-foreground/40 absolute -left-[1.4rem] top-2 size-2 rounded-full"
        aria-hidden
      />
      <div className="bg-card rounded-md border p-3">
        <div className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-2 text-sm font-medium">
            <Icon className="text-muted-foreground size-3.5" aria-hidden />
            {fromLabel}
            <ArrowRight
              className="text-muted-foreground size-3.5"
              aria-hidden
            />
            {toLabel}
          </span>
          <span className="text-muted-foreground text-xs">
            {formatTimelineDate(event.occurred_at)}
          </span>
        </div>
        <p className="text-muted-foreground mt-1 text-xs">
          {actor
            ? t("tickets.timeline.assignedBy", { name: actor.full_name })
            : event.actor_user_id
              ? t("tickets.timeline.assignedByUser")
              : t("tickets.timeline.assignedBySystem")}
        </p>
      </div>
    </li>
  );
}

function CommentRow({ event, actor }: TimelineRowProps) {
  const { t } = useTranslation();
  const kind = event.kind ?? "internal_note";
  const isCustomerReply = kind === "customer_reply";
  const isArchived = event.is_archived === true;
  const Icon = isCustomerReply ? MessageSquareReply : MessageSquare;

  return (
    <li className="relative">
      <span
        className={cn(
          "absolute -left-[1.4rem] top-2 size-2 rounded-full",
          isCustomerReply ? "bg-primary" : "bg-muted-foreground",
        )}
        aria-hidden
      />
      <div
        className={cn(
          "bg-card rounded-md border p-3",
          isArchived && "opacity-60",
          isCustomerReply && !isArchived && "border-primary/40",
        )}
      >
        <div className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-2 text-sm font-medium">
            <Icon
              className={cn(
                "size-3.5",
                isCustomerReply ? "text-primary" : "text-muted-foreground",
              )}
              aria-hidden
            />
            <Avatar size="sm" className="size-5">
              <AvatarFallback className="text-[10px]">
                {userInitials({
                  full_name: actor?.full_name,
                  email: actor?.email,
                })}
              </AvatarFallback>
            </Avatar>
            {actor?.full_name ?? t("tickets.common.unknownUser")}
            <Badge
              variant={isCustomerReply ? "default" : "secondary"}
              className="h-5 px-1.5 text-xs"
            >
              {COMMENT_KIND_LABELS[kind]}
            </Badge>
            {isArchived ? (
              <Badge variant="outline" className="h-5 px-1.5 text-xs">
                {t("tickets.common.archived")}
              </Badge>
            ) : null}
          </span>
          <span className="text-muted-foreground text-xs">
            {formatTimelineDate(event.occurred_at)}
          </span>
        </div>
        {event.body ? (
          <p
            className={cn(
              "text-foreground mt-2 text-sm whitespace-pre-wrap break-words",
              isArchived && "line-through",
            )}
          >
            {event.body}
          </p>
        ) : null}
      </div>
    </li>
  );
}
