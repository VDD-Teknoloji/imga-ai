"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { useAuthStore } from "@/lib/auth-store";
import { useTranslation } from "@/lib/i18n/use-translation";
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
  const { t } = useTranslation();

  return (
    <nav aria-label={t("shell.nav.mainMenu")} className="flex flex-col gap-1 px-2">
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
          heading="shell.nav.section.admin"
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
  const { t } = useTranslation();
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
              aria-label={t("shell.nav.sectionAria", { name: t(heading) })}
            >
              {t(heading)}
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
      {/* Sprint 9.9 — Madde 3: ardışık aynı subgroup'lu item'lardan
          ilkinin önüne mini bir "subgroup heading" + indent ekle.
          Kullanıcı Operasyon altında "Veri Yükle" alt-konusunu
          görsel olarak ayırt eder. collapsed mode'da subgroup
          tamamen gizleniyor — icon dock'unun sade kalmasını
          istiyoruz. */}
      {items.map((item, i) => {
        const prev = items[i - 1];
        const showSubgroupHeader =
          !collapsed &&
          !!item.subgroup &&
          item.subgroup !== prev?.subgroup;
        const indented = !collapsed && !!item.subgroup;
        const subgroupLabel = item.subgroup ? t(item.subgroup) : "";
        return (
          <React.Fragment key={item.href}>
            {showSubgroupHeader ? (
              <p
                className="text-sidebar-foreground/55 mt-2 mb-0.5 px-3 text-[10px] font-semibold tracking-[0.10em] uppercase"
                aria-label={t("shell.nav.subgroupAria", {
                  name: subgroupLabel,
                })}
              >
                {subgroupLabel}
              </p>
            ) : null}
            <SidebarNavLink
              item={item}
              isActive={isActiveLink(pathname, item.href)}
              collapsed={collapsed}
              indented={indented}
              onNavigate={onNavigate}
            />
          </React.Fragment>
        );
      })}
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
  /** Sprint 9.9 — Madde 3: subgroup item ise sol kenarda 4 unit
   *  ek padding ve ince bir indikatör çizgi. Görsel hiyerarşi:
   *  "Operasyon > Veri Yükle > Manuel/Toplu". */
  indented?: boolean;
  onNavigate?: () => void;
}

function SidebarNavLink({
  item,
  isActive,
  collapsed,
  indented = false,
  onNavigate,
}: SidebarNavLinkProps) {
  const { t } = useTranslation();
  const Icon = item.icon;
  const label = t(item.label);
  // In collapsed mode the icon-only link gets the full label via the
  // native `title` attribute (browser-native tooltip). Base UI's
  // Tooltip primitive is button-only and would emit the wrong ARIA
  // for an anchor; the title attribute is simple and accessible.
  //
  // Sprint 10.2 — sidebar artık marka laciverti. Aktif item:
  // bir ton açık lacivert pill + parlak turuncu metin + sol kenarda
  // TURUNCU KARE — logodaki merkez karenin motifi ("sinyal").
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      aria-current={isActive ? "page" : undefined}
      aria-label={collapsed ? label : undefined}
      title={collapsed ? label : undefined}
      className={cn(
        "relative flex h-10 items-center gap-3 rounded-xl px-3 text-sm font-medium",
        "transition-[background,color,box-shadow] duration-[var(--motion-duration)] [transition-timing-function:var(--motion-ease)]",
        "text-sidebar-foreground/85 hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
        isActive &&
          "bg-sidebar-accent text-sidebar-primary ring-1 ring-sidebar-primary/25",
        collapsed && "justify-center px-0",
        // Sprint 9.9 — Madde 3: subgroup item ise sol tarafa ek
        // padding + ince border-l ile alt-grup işareti. Active
        // state daha güçlü visual taşıdığı için border-l rengini
        // soft tutuyoruz; non-active'lerde gri/sidebar-border.
        indented && !collapsed && "ml-4 border-l border-sidebar-border/60 pl-3 rounded-l-none",
      )}
    >
      {/* Active marker — logodaki merkez turuncu kare. Arka plan
          tek başına yetmediğinde (yoğun lacivert rail) aktif öğeyi
          marka motifiyle işaretler. */}
      {isActive && !collapsed ? (
        <span
          aria-hidden
          className="bg-sidebar-primary absolute left-1 top-1/2 size-1.5 -translate-y-1/2 rounded-[2px]"
        />
      ) : null}
      <Icon
        className={cn("size-4 shrink-0", isActive && "text-sidebar-primary")}
        aria-hidden
      />
      {collapsed ? null : <span className="truncate">{label}</span>}
    </Link>
  );
}
