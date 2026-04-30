import { LayoutDashboard, Settings, Ticket } from "lucide-react";
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
  { label: "Ayarlar", href: "/settings", icon: Settings },
];
