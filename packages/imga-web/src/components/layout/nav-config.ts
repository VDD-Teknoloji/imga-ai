import {
  Building2,
  FileSearch,
  LayoutDashboard,
  Settings,
  Sparkles,
  Ticket,
  Upload,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

/**
 * Single source of truth for sidebar navigation. The order here is
 * the order rendered. `roles` filters items by the user's active
 * tenant role; an empty array means "anyone with a tenant".
 */
export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: ReadonlyArray<NavItem> = [
  { label: "Panel", href: "/", icon: LayoutDashboard },
  { label: "Ticket'lar", href: "/tickets", icon: Ticket },
  { label: "Analiz", href: "/analyze", icon: Sparkles },
  { label: "Toplu Yükleme", href: "/analyze/upload", icon: Upload },
  { label: "Analizler", href: "/reviews", icon: FileSearch },
  { label: "Ayarlar", href: "/settings", icon: Settings },
];

/**
 * Sprint 7.7.4 — admin-only nav. Rendered as a separate "YÖNETİM"
 * section under the main NAV_ITEMS, gated entirely behind
 * `user.is_super_admin === true` so non-admins never see the
 * heading at all.
 */
export const ADMIN_NAV_ITEMS: ReadonlyArray<NavItem> = [
  { label: "Tenant'lar", href: "/admin/tenants", icon: Building2 },
];
