"use client";

// Sprint 10.3 — sağ raydaki kompakt işlem listesi.
//
// "Ana sayfayı açan yönetici kolayca işlem yapabilsin": rapor sol
// kolonda akarken, sık kullanılan dört kapı sağ rayda dikey ve
// sade durur. UploadDock'un altında yaşar; FAB'ın aksine her zaman
// görünürdür (multi-entry pattern).

import {
  ArrowUpRight,
  ClipboardList,
  Compass,
  FileBarChart,
  Sparkles,
} from "lucide-react";
import Link from "next/link";

const LINKS = [
  {
    href: "/executive-briefing",
    label: "Yönetici Özeti oluştur",
    description: "Yapay zeka dönem raporu",
    icon: Sparkles,
  },
  {
    href: "/strategy",
    label: "SWOT / OKR oluştur",
    description: "Stratejik analiz",
    icon: Compass,
  },
  {
    href: "/tickets",
    label: "Talepler",
    description: "Açık müşteri talepleri",
    icon: ClipboardList,
  },
  {
    href: "/reports",
    label: "Rapor indir",
    description: "PDF / Excel dışa aktarım",
    icon: FileBarChart,
  },
] as const;

export function QuickLinks() {
  return (
    <nav
      aria-label="Hızlı işlemler"
      className="rise-in shadow-soft bg-card ring-foreground/8 overflow-hidden rounded-2xl ring-1"
      style={{ animationDelay: "120ms" }}
    >
      <h2 className="text-muted-foreground px-4 pt-3.5 pb-1 text-[11px] font-bold tracking-[0.12em] uppercase">
        Hızlı İşlemler
      </h2>
      <ul className="pb-1.5">
        {LINKS.map((link) => {
          const Icon = link.icon;
          return (
            <li key={link.href}>
              <Link
                href={link.href}
                className="hover:bg-accent/50 group flex items-center gap-3 px-4 py-2.5 transition-colors"
              >
                <span className="bg-accent text-accent-foreground flex size-8 shrink-0 items-center justify-center rounded-lg">
                  <Icon className="size-4" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">
                    {link.label}
                  </span>
                  <span className="text-muted-foreground block truncate text-[11px]">
                    {link.description}
                  </span>
                </span>
                <ArrowUpRight
                  className="text-muted-foreground/40 group-hover:text-primary size-4 shrink-0 transition-colors"
                  aria-hidden
                />
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
