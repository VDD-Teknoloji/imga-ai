import { TICKET_PRIORITY_LABELS } from "@/lib/ticket-actions";
import type { TicketPriority } from "@/lib/types";
import { cn } from "@/lib/utils";

const PRIORITY_BADGE_CLASS: Record<TicketPriority, string> = {
  low: "bg-muted text-muted-foreground",
  normal: "bg-secondary text-secondary-foreground",
  high: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  urgent: "bg-destructive/15 text-destructive",
};

export function TicketPriorityBadge({
  priority,
  className,
}: {
  priority: TicketPriority;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        PRIORITY_BADGE_CLASS[priority],
        className,
      )}
    >
      {TICKET_PRIORITY_LABELS[priority]}
    </span>
  );
}
