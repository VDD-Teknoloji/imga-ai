// Display helpers for tenant users (Sprint 7.7.2 — assignee dropdown,
// comment author block, timeline actor resolution) plus tenant
// plan / automation labels (Sprint 7.7.4 — admin tenant CRUD).

import { localeLabels } from "@/lib/i18n/locale-labels";
import type {
  AutomationMode,
  TicketCommentKind,
  UserTenantRole,
} from "@/lib/types";

export const USER_ROLE_LABELS: Record<UserTenantRole, string> = localeLabels({
  tr: { tenant_admin: "Yönetici", analyst: "Analist", viewer: "İzleyici" },
  en: { tenant_admin: "Admin", analyst: "Analyst", viewer: "Viewer" },
});

export const COMMENT_KIND_LABELS: Record<TicketCommentKind, string> = localeLabels({
  tr: { internal_note: "İç not", customer_reply: "Müşteri yanıtı" },
  en: { internal_note: "Internal note", customer_reply: "Customer reply" },
});

export const AUTOMATION_MODE_LABELS: Record<AutomationMode, string> = localeLabels({
  tr: { manual: "Manuel", semi_auto: "Yarı otomatik", full_auto: "Tam otomatik" },
  en: { manual: "Manual", semi_auto: "Semi-automatic", full_auto: "Fully automatic" },
});

export const PLAN_TIER_LABELS: Record<string, string> = localeLabels({
  tr: { trial: "Deneme", starter: "Başlangıç", business: "Kurumsal", enterprise: "Enterprise" },
  en: { trial: "Trial", starter: "Starter", business: "Business", enterprise: "Enterprise" },
});

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
