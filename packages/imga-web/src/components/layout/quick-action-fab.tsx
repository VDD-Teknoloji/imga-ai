"use client";

// Sprint 9.6 redesign — universal floating action button.
//
// Apple-style multi-entry: the four primary actions live on the
// dashboard tiles AND inside this FAB, reachable from every
// authenticated route. Same model as the iPhone camera being
// available on lock screen + control center + apps drawer — high-
// frequency actions get redundant surfaces.
//
// On md+ screens the FAB sits at bottom-right with a soft elevation.
// On mobile it lands above the OS gesture area. Click opens a
// popover with 4 large rows; same routes as the dashboard tiles.
//
// We hide the FAB on /login and on the public invite-accept flow
// — those routes don't live inside AppShell so it's already a no-
// op there, but a defensive pathname check stays here in case
// someone wires the layout differently later.

import { ClipboardList, Compass, ListChecks, Plus, Upload, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { useTranslation } from "@/lib/i18n/use-translation";
import { cn } from "@/lib/utils";

interface QuickActionRow {
  href: string;
  /** i18n anahtarı — render sırasında t() ile çözülür. */
  labelKey: string;
  /** i18n anahtarı — render sırasında t() ile çözülür. */
  hintKey: string;
  Icon: typeof Upload;
}

const ROWS: ReadonlyArray<QuickActionRow> = [
  {
    href: "/analyze/upload",
    labelKey: "shell.fab.newUpload.label",
    hintKey: "shell.fab.newUpload.hint",
    Icon: Upload,
  },
  {
    href: "/executive-briefing",
    labelKey: "shell.fab.executiveSummary.label",
    hintKey: "shell.fab.executiveSummary.hint",
    Icon: ClipboardList,
  },
  {
    href: "/action-items",
    labelKey: "shell.fab.actionItems.label",
    hintKey: "shell.fab.actionItems.hint",
    Icon: ListChecks,
  },
  {
    href: "/strategy",
    labelKey: "shell.fab.strategy.label",
    hintKey: "shell.fab.strategy.hint",
    Icon: Compass,
  },
];

export function QuickActionFab() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const { t } = useTranslation();

  // Close on route change so a click-through doesn't leave the
  // panel open over the new page.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOpen(false);
  }, [pathname]);

  // Close on outside click + Escape.
  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (!panelRef.current) return;
      if (!panelRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div
      ref={panelRef}
      className="fixed bottom-5 right-5 z-40 flex flex-col items-end gap-3 md:bottom-7 md:right-7"
    >
      {open ? (
        <div
          className="glass ring-foreground/10 shadow-pop rise-in w-80 origin-bottom-right rounded-2xl p-2 ring-1"
          role="menu"
          aria-label={t("shell.fab.title")}
        >
          <p className="text-muted-foreground px-3 pb-2 pt-2 text-[10px] font-semibold uppercase tracking-[0.14em]">
            {t("shell.fab.title")}
          </p>
          {ROWS.map((row) => (
            <Link
              key={row.href}
              href={row.href}
              role="menuitem"
              className="hover:bg-accent/80 group flex items-center gap-3 rounded-xl px-2 py-2.5 transition-colors duration-[var(--motion-duration)]"
            >
              <div className="from-primary/15 to-primary/5 text-primary ring-primary/15 flex size-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ring-1">
                <row.Icon className="size-4" aria-hidden />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold truncate">{t(row.labelKey)}</p>
                <p className="text-muted-foreground text-xs truncate">
                  {t(row.hintKey)}
                </p>
              </div>
            </Link>
          ))}
        </div>
      ) : null}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={open ? t("shell.fab.close") : t("shell.fab.open")}
        className={cn(
          "text-primary-foreground focus-visible:ring-ring inline-flex size-14 items-center justify-center rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2",
          "shadow-pop hover:shadow-glow transition-[transform,box-shadow] duration-[var(--motion-duration)] [transition-timing-function:var(--motion-ease)]",
          "bg-gradient-to-br from-primary to-brand",
          open && "rotate-45 scale-95",
          !open && "hover:scale-[1.04]",
        )}
      >
        {open ? (
          <X className="size-5" aria-hidden />
        ) : (
          <Plus className="size-6" aria-hidden strokeWidth={2.4} />
        )}
      </button>
    </div>
  );
}
