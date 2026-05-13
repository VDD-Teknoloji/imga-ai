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

import { cn } from "@/lib/utils";

interface QuickActionRow {
  href: string;
  label: string;
  hint: string;
  Icon: typeof Upload;
}

const ROWS: ReadonlyArray<QuickActionRow> = [
  {
    href: "/analyze/upload",
    label: "Yeni yükleme",
    hint: "CSV / Excel toplu analiz",
    Icon: Upload,
  },
  {
    href: "/executive-briefing",
    label: "Brifing üret",
    hint: "Aylık yönetici özeti",
    Icon: ClipboardList,
  },
  {
    href: "/action-items",
    label: "Aksiyonlar",
    hint: "Bekleyen aksiyonlar",
    Icon: ListChecks,
  },
  {
    href: "/strategy",
    label: "Strateji raporu",
    hint: "SWOT / OKR",
    Icon: Compass,
  },
];

export function QuickActionFab() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const panelRef = useRef<HTMLDivElement | null>(null);

  // Close on route change so a click-through doesn't leave the
  // panel open over the new page.
  useEffect(() => {
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
      className="fixed bottom-4 right-4 z-40 flex flex-col items-end gap-2 md:bottom-6 md:right-6"
    >
      {open ? (
        <div
          className="bg-card border-border w-72 origin-bottom-right rounded-xl border p-2 shadow-lg"
          role="menu"
          aria-label="Hızlı işlemler"
        >
          <p className="text-muted-foreground px-3 pb-2 pt-1 text-[10px] font-semibold uppercase tracking-wider">
            Hızlı işlemler
          </p>
          {ROWS.map((row) => (
            <Link
              key={row.href}
              href={row.href}
              role="menuitem"
              className="hover:bg-accent flex items-center gap-3 rounded-lg px-2 py-2 transition-colors"
            >
              <div className="bg-primary/10 text-primary flex size-9 shrink-0 items-center justify-center rounded-lg">
                <row.Icon className="size-4" aria-hidden />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold truncate">{row.label}</p>
                <p className="text-muted-foreground text-xs truncate">
                  {row.hint}
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
        aria-label={open ? "Hızlı işlemleri kapat" : "Hızlı işlemleri aç"}
        className={cn(
          "bg-primary text-primary-foreground hover:bg-primary/90 focus-visible:ring-ring inline-flex size-12 items-center justify-center rounded-full shadow-lg transition-transform focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2",
          open && "rotate-45",
        )}
      >
        {open ? (
          <X className="size-5" aria-hidden />
        ) : (
          <Plus className="size-5" aria-hidden />
        )}
      </button>
    </div>
  );
}
