"use client";

// Sprint 9.6 redesign — dashboard quick-action tiles.
//
// Apple-style: the 4 actions a tenant_admin / C-level operator
// reaches for most frequently are surface-level affordances on the
// landing page itself, not 3 clicks deep into the nav. Same 4
// actions ALSO live in the universal FAB (see quick-action-fab.tsx)
// so they're reachable from every authenticated route — same
// pattern as the iPhone camera surfacing on lock screen + control
// center + apps.
//
//   1. Yeni yükleme (most common entry — CSV/XLSX batch)
//   2. Brifing üret (weekly habit for execs)
//   3. Bekleyen aksiyonlar (with badge — "what's owed to me")
//   4. Strateji raporu (SWOT/OKR, lower frequency but high stakes)
//
// The action-items badge reads from useActionItems so it stays
// honest about the user's actual queue rather than showing a static
// "Aksiyonlar" label.

import { ArrowRight, ClipboardList, Compass, ListChecks, Upload } from "lucide-react";
import Link from "next/link";

import { useActionItems } from "@/hooks/use-action-items";
import { useTranslation } from "@/lib/i18n/use-translation";

interface Tile {
  href: string;
  label: string;
  hint: string;
  Icon: typeof Upload;
  // Optional badge (numeric) — only the action-items tile uses it.
  badge?: number;
}

export function QuickActions() {
  const { t } = useTranslation();
  // Open + in-progress action items. Default filter on the page is
  // open-only; we mirror that here so the badge matches what the
  // user sees when they click through.
  const openItems = useActionItems({ status: "open" });
  const openCount = openItems.data?.length ?? 0;

  const tiles: Tile[] = [
    {
      href: "/analyze/upload",
      label: t("dashboard.quickActions.newUpload"),
      hint: t("dashboard.quickActions.newUploadHint"),
      Icon: Upload,
    },
    {
      href: "/executive-briefing",
      label: t("dashboard.quickActions.briefing"),
      hint: t("dashboard.quickActions.briefingHint"),
      Icon: ClipboardList,
    },
    {
      href: "/action-items",
      label: t("dashboard.quickActions.actionItemsLabel"),
      hint:
        openCount > 0
          ? t("dashboard.quickActions.actionItemsOpen", { n: openCount })
          : t("dashboard.quickActions.actionItemsNone"),
      Icon: ListChecks,
      badge: openCount,
    },
    {
      href: "/strategy",
      label: t("dashboard.quickActions.strategy"),
      hint: t("dashboard.quickActions.strategyHint"),
      Icon: Compass,
    },
  ];

  return (
    <section
      aria-label={t("dashboard.common.quickActions")}
      className="grid grid-cols-2 gap-3 md:grid-cols-4"
    >
      {tiles.map((tile, idx) => (
        <Link
          key={tile.href}
          href={tile.href}
          // Sprint 9.6.1 — tile design language. Layered: bg-card on
          // top of bg, very subtle ring (almost imperceptible), the
          // canonical .hover-lift utility upgrades the shadow on
          // hover. Focus state pulls the primary glow ring. Entry
          // animation staggered per tile so the row settles in like
          // an iOS home-screen page rather than appearing as a
          // sudden grid.
          style={{ animationDelay: `${idx * 40}ms` }}
          className="rise-in hover-lift group bg-card ring-foreground/5 hover:ring-primary/20 focus-visible:shadow-glow shadow-soft relative flex items-center gap-3 overflow-hidden rounded-2xl p-4 ring-1 transition-[box-shadow,transform] focus-visible:outline-none"
        >
          {/* Soft brand wash on hover — the gradient lives behind the
              content and fades in via opacity so the tile gains a
              subtle indigo glow when the operator hovers without
              the icon container moving. */}
          <span
            aria-hidden
            className="pointer-events-none absolute inset-0 bg-gradient-to-br from-primary/8 via-transparent to-transparent opacity-0 transition-opacity duration-[var(--motion-duration)] group-hover:opacity-100"
          />
          <div className="from-primary/15 to-primary/5 text-primary relative flex size-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ring-1 ring-primary/10">
            <tile.Icon className="size-5" aria-hidden />
          </div>
          <div className="relative flex-1 min-w-0">
            <p className="text-sm font-semibold truncate">{tile.label}</p>
            <p className="text-muted-foreground text-xs truncate">{tile.hint}</p>
          </div>
          {tile.badge && tile.badge > 0 ? (
            <span
              className="bg-primary text-primary-foreground shadow-glow absolute right-3 top-3 inline-flex h-5 min-w-[1.25rem] items-center justify-center rounded-full px-1.5 text-[10px] font-bold"
              aria-label={t("dashboard.quickActions.badgeAria", { n: tile.badge })}
            >
              {tile.badge > 99 ? "99+" : tile.badge}
            </span>
          ) : null}
          <ArrowRight
            className="text-muted-foreground/60 group-hover:text-primary group-hover:translate-x-0.5 relative size-4 shrink-0 self-center transition-[color,transform] duration-[var(--motion-duration)]"
            aria-hidden
          />
        </Link>
      ))}
    </section>
  );
}
