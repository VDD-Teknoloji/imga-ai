// Display helpers for tenant users (Sprint 7.7.2 — assignee dropdown,
// comment author block, timeline actor resolution).

import type { TicketCommentKind, UserTenantRole } from "@/lib/types";

export const USER_ROLE_LABELS: Record<UserTenantRole, string> = {
  tenant_admin: "Yönetici",
  analyst: "Analist",
  viewer: "İzleyici",
};

export const COMMENT_KIND_LABELS: Record<TicketCommentKind, string> = {
  internal_note: "İç not",
  customer_reply: "Müşteri yanıtı",
};

/**
 * Two-letter avatar initials from a full name. Falls back to the first
 * two letters of the email local part when the user's name is empty.
 */
export function userInitials(input: {
  full_name?: string | null;
  email?: string | null;
}): string {
  const name = input.full_name?.trim();
  if (name && name.length > 0) {
    const parts = name.split(/\s+/);
    if (parts.length >= 2) {
      const first = parts[0]?.[0] ?? "";
      const last = parts[parts.length - 1]?.[0] ?? "";
      return (first + last).toUpperCase();
    }
    return name.slice(0, 2).toUpperCase();
  }
  const email = input.email?.trim();
  if (email && email.length > 0) {
    const local = email.split("@")[0] ?? "";
    return local.slice(0, 2).toUpperCase();
  }
  return "?";
}
