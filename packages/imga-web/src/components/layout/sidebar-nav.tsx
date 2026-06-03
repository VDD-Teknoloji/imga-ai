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
          // Sprint 9.8 — Madde 2: Hiyerarşik gruplama görsel olarak
          // daha belirgin. Header'lar daha kalın + ince üst divider
          // ile gruplar arası ayrım netleştirildi.
          <div className="mt-5 mb-1 px-3">
            <div className="bg-sidebar-border mx-0 mb-2 h-px" aria-hidden />
            <p
              className="text-sidebar-foreground/70 text-[11px] font-bold tracking-[0.12em] uppercase"
              aria-label={`${heading} bölümü`}
            >
              {heading}
            </p>
          </div>
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
  //
  // Sprint 9.6.1 — active item: indigo-tinted gradient pill with a
  // soft brand-coloured ring + glow shadow. The hover state shares
  // the same indigo wash so the affordance feels continuous (hover
  // is the lighter precursor to active).
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={isActive ? "page" : undefined}
      aria-label={collapsed ? item.label : undefined}
      title={collapsed ? item.label : undefined}
      className={cn(
        "relative flex h-10 items-center gap-3 rounded-xl px-3 text-sm font-medium",
        "transition-[background,color,box-shadow] duration-[var(--motion-duration)] [transition-timing-function:var(--motion-ease)]",
        "text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
        isActive &&
          "bg-gradient-to-r from-primary/15 to-primary/5 text-primary ring-1 ring-primary/15 dark:from-primary/20 dark:to-primary/5 dark:text-primary dark:ring-primary/25",
        collapsed && "justify-center px-0",
      )}
    >
      {/* Active marker — a thin gradient bar on the left edge. Gives
          the active item a magazine-style indicator without relying
          on background alone (helps when sidebar bg is busy). */}
      {isActive && !collapsed ? (
        <span
          aria-hidden
          className="from-primary to-[oklch(0.55_0.22_290)] dark:to-[oklch(0.78_0.18_290)] absolute left-1.5 top-1/2 h-5 w-1 -translate-y-1/2 rounded-full bg-gradient-to-b"
        />
      ) : null}
      <Icon
        className={cn("size-4 shrink-0", isActive && "text-primary")}
        aria-hidden
      />
      {collapsed ? null : <span className="truncate">{item.label}</span>}
    </Link>
  );
}
