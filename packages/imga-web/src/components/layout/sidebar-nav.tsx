"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useAuthStore } from "@/lib/auth-store";
import { cn } from "@/lib/utils";

import {
  ADMIN_NAV_ITEMS,
  NAV_SECTIONS,
  type NavItem,
} from "./nav-config";

interface SidebarNavProps {
  /** When true, only the icon is shown; label appears as a tooltip. */
  collapsed: boolean;
  /** Optional click handler — used by the mobile Sheet to dismiss
   * itself on navigation. Desktop callers can omit it. */
  onNavigate?: () => void;
}

/**
 * Sprint 9.6 redesign — renders NAV_SECTIONS as grouped blocks
 * with optional headings. Sections without a heading still render
 * their items but skip the section title; a thin divider sits
 * between consecutive groups so the eye can chunk them.
 */
export function SidebarNav({ collapsed, onNavigate }: SidebarNavProps) {
  const pathname = usePathname();
  const isSuperAdmin = useAuthStore((s) => s.user?.is_super_admin ?? false);

  return (
    <nav aria-label="Ana menü" className="flex flex-col gap-1 px-2">
      {NAV_SECTIONS.map((section, sectionIdx) => (
        <SidebarSection
          key={`section-${sectionIdx}`}
          heading={section.heading}
          items={section.items}
          showDivider={sectionIdx > 0}
          collapsed={collapsed}
          pathname={pathname}
          onNavigate={onNavigate}
        />
      ))}

      {/* Sprint 7.7.4: admin section is fully hidden for non-admins
          — no heading, no separator, no DOM at all. */}
      {isSuperAdmin ? (
        <SidebarSection
          heading="Yönetim"
          items={ADMIN_NAV_ITEMS}
          showDivider
          collapsed={collapsed}
          pathname={pathname}
          onNavigate={onNavigate}
        />
      ) : null}
    </nav>
  );
}

interface SidebarSectionProps {
  heading: string;
  items: ReadonlyArray<NavItem>;
  showDivider: boolean;
  collapsed: boolean;
  pathname: string;
  onNavigate?: () => void;
}

function SidebarSection({
  heading,
  items,
  showDivider,
  collapsed,
  pathname,
  onNavigate,
}: SidebarSectionProps) {
  return (
    <>
      {showDivider ? (
        collapsed ? (
          <div
            role="separator"
            aria-orientation="horizontal"
            className="bg-sidebar-border mx-3 my-2 h-px"
          />
        ) : heading ? (
          <p
            className="text-muted-foreground mt-4 mb-1 px-3 text-[10px] font-semibold tracking-wider uppercase"
            aria-label={`${heading} bölümü`}
          >
            {heading}
          </p>
        ) : (
          // Headingless follow-up section gets a divider but no
          // heading — keeps Ayarlar visually separated from
          // Operasyon without a 1-item label.
          <div
            role="separator"
            aria-orientation="horizontal"
            className="bg-sidebar-border mx-3 my-2 h-px"
          />
        )
      ) : null}
      {items.map((item) => (
        <SidebarNavLink
          key={item.href}
          item={item}
          isActive={isActiveLink(pathname, item.href)}
          collapsed={collapsed}
          onNavigate={onNavigate}
        />
      ))}
    </>
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
