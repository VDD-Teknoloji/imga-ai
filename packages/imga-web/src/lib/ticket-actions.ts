// Ticket action vocabulary.
//
// Backend's POST /tickets/{id}/transition takes a `to_state` (and an
// optional `cancellation_reason`). Frontend wants to surface verb-level
// actions ("Üstlen", "Çöz", "Yeniden Aç") with state-aware visibility
// and per-role gating. This module owns that mapping.
//
// The role matrix mirrors imga_api/services/ticket_state_machine.py
// ROLE_MATRIX exactly so the UI never offers an action the backend
// would reject. Any change in the backend matrix MUST land here too
// or the dashboard will surface dead buttons.

import type { TicketPriority, TicketState, UserTenantRole } from "@/lib/types";

export type TicketActionId =
  | "claim"
  | "wait_customer"
  | "resume"
  | "resolve"
  | "close"
  | "regression"
  | "reopen"
  | "uncancel"
  | "cancel"
  | "unclaim"
  | "quick_resolve";

interface TicketActionDef {
  id: TicketActionId;
  label: string;
  /** to_state mapping. quick_resolve is the only action that doesn't
   * map to a single transition — its mutation runs claim+resolve back
   * to back, so we hand-handle it in useTicketMutations. */
  toState: TicketState | null;
  fromStates: ReadonlyArray<TicketState>;
  allowedRoles: ReadonlyArray<UserTenantRole>;
  /** Some actions need a follow-up dialog before firing. */
  needsCancellationReason?: boolean;
  /** Self-only guard — analyst can only un-claim a ticket they own. */
  selfOnly?: boolean;
  /** Render variant. */
  variant?: "default" | "destructive" | "secondary" | "outline" | "ghost";
}

const ANALYST_OR_ADMIN: ReadonlyArray<UserTenantRole> = ["analyst", "tenant_admin"];
const ADMIN_ONLY: ReadonlyArray<UserTenantRole> = ["tenant_admin"];

export const TICKET_ACTIONS: Record<TicketActionId, TicketActionDef> = {
  claim: {
    id: "claim",
    label: "Üstlen",
    toState: "in_progress",
    fromStates: ["open"],
    allowedRoles: ANALYST_OR_ADMIN,
    variant: "default",
  },
  wait_customer: {
    id: "wait_customer",
    label: "Müşteri bekleniyor",
    toState: "pending_customer",
    fromStates: ["in_progress"],
    allowedRoles: ANALYST_OR_ADMIN,
    variant: "secondary",
  },
  resume: {
    id: "resume",
    label: "Devam et",
    toState: "in_progress",
    fromStates: ["pending_customer"],
    allowedRoles: ANALYST_OR_ADMIN,
    variant: "default",
  },
  resolve: {
    id: "resolve",
    label: "Çöz",
    toState: "resolved",
    fromStates: ["in_progress", "pending_customer"],
    allowedRoles: ANALYST_OR_ADMIN,
    variant: "default",
  },
  close: {
    id: "close",
    label: "Kapat",
    toState: "closed",
    fromStates: ["resolved"],
    allowedRoles: ANALYST_OR_ADMIN,
    variant: "secondary",
  },
  regression: {
    id: "regression",
    label: "Yeniden aç",
    toState: "in_progress",
    fromStates: ["resolved"],
    allowedRoles: ANALYST_OR_ADMIN,
    variant: "outline",
  },
  reopen: {
    id: "reopen",
    label: "Yeniden aç",
    toState: "open",
    fromStates: ["closed"],
    allowedRoles: ADMIN_ONLY,
    variant: "outline",
  },
  uncancel: {
    id: "uncancel",
    label: "Geri al",
    toState: "open",
    fromStates: ["cancelled"],
    allowedRoles: ADMIN_ONLY,
    variant: "outline",
  },
  cancel: {
    id: "cancel",
    label: "İptal",
    toState: "cancelled",
    // OPEN -> CANCELLED is analyst+admin; IN_PROGRESS -> CANCELLED is
    // admin-only (7.5 revision 5). We handle the role split via the
    // resolver below — fromStates only declares where the transition
    // is graph-legal.
    fromStates: ["open", "in_progress"],
    allowedRoles: ANALYST_OR_ADMIN, // overridden per from-state below
    needsCancellationReason: true,
    variant: "destructive",
  },
  unclaim: {
    id: "unclaim",
    label: "Bırak",
    toState: "open",
    fromStates: ["in_progress"],
    allowedRoles: ANALYST_OR_ADMIN,
    selfOnly: true,
    variant: "ghost",
  },
  quick_resolve: {
    id: "quick_resolve",
    label: "Hızlı çöz",
    toState: null,
    fromStates: ["open"],
    allowedRoles: ANALYST_OR_ADMIN,
    variant: "secondary",
  },
};

// --- Turkish labels -----------------------------------------------------

export const TICKET_PRIORITY_LABELS: Record<TicketPriority, string> = {
  low: "Düşük",
  normal: "Normal",
  high: "Yüksek",
  urgent: "Acil",
};

export const CANCELLATION_REASON_LABELS: Record<string, string> = {
  false_positive: "Yanlış pozitif",
  duplicate: "Mükerrer",
  spam: "Spam",
  off_topic: "Konu dışı",
  other: "Diğer",
};

// --- Role / state resolver ---------------------------------------------

interface ResolverInput {
  ticketState: TicketState;
  ticketAssigneeId: string | null;
  userRole: UserTenantRole | null;
  userId: string;
  isSuperAdmin: boolean;
}

/**
 * Returns the action ids that are valid + role-allowed for the given
 * ticket + user. Used by the action bar to render only legal buttons.
 *
 * VIEWER role short-circuits to an empty list (read-only).
 */
export function availableActions({
  ticketState,
  ticketAssigneeId,
  userRole,
  userId,
  isSuperAdmin,
}: ResolverInput): TicketActionId[] {
  if (!isSuperAdmin && (userRole === null || userRole === "viewer")) {
    return [];
  }
  const effectiveRole: UserTenantRole = isSuperAdmin
    ? "tenant_admin"
    : (userRole as UserTenantRole);

  const out: TicketActionId[] = [];
  for (const action of Object.values(TICKET_ACTIONS)) {
    if (!action.fromStates.includes(ticketState)) continue;

    // Per-state role override for cancel: IN_PROGRESS -> CANCELLED is
    // admin-only, but OPEN -> CANCELLED is analyst+admin. The action
    // def uses the looser allowedRoles; tighten for the IN_PROGRESS case.
    if (action.id === "cancel" && ticketState === "in_progress") {
      if (effectiveRole !== "tenant_admin") continue;
    } else if (!action.allowedRoles.includes(effectiveRole)) {
      continue;
    }

    // Self-only un-claim: analyst can only un-claim if they own the ticket.
    if (
      action.selfOnly &&
      effectiveRole === "analyst" &&
      ticketAssigneeId !== null &&
      ticketAssigneeId !== userId
    ) {
      continue;
    }

    out.push(action.id);
  }
  return out;
}
