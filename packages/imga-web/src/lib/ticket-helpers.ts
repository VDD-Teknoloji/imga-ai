// Display helpers for ticket-state and priority enums.
//
// Backend stores the canonical lowercase code; the UI displays a
// Turkish label. Centralised here so adding a new state in Sprint
// 7.5.5 or 8 only touches one file.

import type { TicketPriority, TicketState } from "@/lib/types";

export const TICKET_STATE_LABELS: Record<TicketState, string> = {
  open: "Açık",
  in_progress: "İlerlemekte",
  pending_customer: "Müşteri Bekleniyor",
  resolved: "Çözüldü",
  closed: "Kapatıldı",
  cancelled: "İptal",
};

/** Non-terminal states — used by "active ticket" counts. */
export const ACTIVE_TICKET_STATES: ReadonlyArray<TicketState> = [
  "open",
  "in_progress",
  "pending_customer",
];

/** Terminal states — once here a ticket is "off the queue". */
export const TERMINAL_TICKET_STATES: ReadonlyArray<TicketState> = ["closed", "cancelled"];

export const TICKET_PRIORITY_LABELS: Record<TicketPriority, string> = {
  low: "Düşük",
  normal: "Normal",
  high: "Yüksek",
  urgent: "Acil",
};

export const HIGH_PRIORITIES: ReadonlyArray<TicketPriority> = ["high", "urgent"];

/** Tailwind utility classes for the colored badge per state. */
export const TICKET_STATE_BADGE_CLASS: Record<TicketState, string> = {
  open: "bg-secondary text-secondary-foreground",
  in_progress: "bg-primary/15 text-primary",
  pending_customer: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  resolved: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  closed: "bg-muted text-muted-foreground",
  cancelled: "bg-destructive/10 text-destructive",
};
