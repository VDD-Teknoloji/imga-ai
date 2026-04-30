"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

import { NAV_ITEMS, type NavItem } from "./nav-config";

interface SidebarNavProps {
  /** When true, only the icon is shown; label appears as a tooltip. */
  collapsed: boolean;
  /** Optional click handler — used by the mobile Sheet to dismiss
   * itself on navigation. Desktop callers can omit it. */
  onNavigate?: () => void;
}

export function SidebarNav({ collapsed, onNavigate }: SidebarNavProps) {
  const pathname = usePathname();

  return (
    <nav aria-label="Ana menü" className="flex flex-col gap-1 px-2">
      {NAV_ITEMS.map((item) => (
        <SidebarNavLink
          key={item.href}
          item={item}
          isActive={isActiveLink(pathname, item.href)}
          collapsed={collapsed}
          onNavigate={onNavigate}
        />
      ))}
    </nav>
  );
}

function isActiveLink(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

interface SidebarNavLinkProps {
  item: NavItem;
  isActive: boolean;
  collapsed: boolean;
  onNavigate?: () => void;
}

function SidebarNavLink({ item, isActive, collapsed, onNavigate }: SidebarNavLinkProps) {
  const Icon = item.icon;
  // In collapsed mode the icon-only link gets the full label via the
  // native `title` attribute (browser-native tooltip). Base UI's
  // Tooltip primitive is button-only and would emit the wrong ARIA
  // for an anchor; the title attribute is simple and accessible.
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={isActive ? "page" : undefined}
      aria-label={collapsed ? item.label : undefined}
      title={collapsed ? item.label : undefined}
      className={cn(
        "flex h-9 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors",
        "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
        isActive && "bg-sidebar-accent text-sidebar-accent-foreground",
        collapsed && "justify-center px-0",
      )}
    >
      <Icon className="size-4 shrink-0" aria-hidden />
      {collapsed ? null : <span className="truncate">{item.label}</span>}
    </Link>
  );
}
