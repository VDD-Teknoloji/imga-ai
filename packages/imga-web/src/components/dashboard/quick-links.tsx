"use client";

// Sprint 12 — sağ raydaki kompakt işlem listesi.
//
// "Ana sayfayı açan yönetici kolayca işlem yapabilsin": rapor sol
// kolonda akarken, sık kullanılan dört kapı sağ rayda dikey ve
// sade durur. UploadDock'un altında yaşar.

import {
  ArrowUpRight,
  Compass,
  FileBarChart,
  FileText,
  Ticket,
} from "lucide-react";
import Link from "next/link";

const LINKS = [
  {
    href: "/executive-briefing",
    label: "Yönetici Özeti oluştur",
    description: "Dönem raporu",
    icon: FileText,
  },
  {
    href: "/strategy",
    label: "SWOT / OKR oluştur",
    description: "Stratejik analiz",
    icon: Compass,
  },
  {
    href: "/tickets",
    label: "Ticket'lar",
    description: "Açık müşteri Ticket'ları",
    icon: Ticket,
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
      className="rise-in shadow-soft bg-card ring-foreground/5 overflow-hidden rounded-3xl ring-1"
      style={{ animationDelay: "120ms" }}
    >
      <h2 className="text-muted-foreground px-5 pt-4 pb-1 text-xs font-semibold">
        Hızlı işlemler
      </h2>
      <ul className="pb-2">
        {LINKS.map((link) => {
          const Icon = link.icon;
          return (
            <li key={link.href}>
              <Link
                href={link.href}
                className="hover:bg-accent/50 group flex items-center gap-3 px-5 py-3 transition-colors"
              >
                <span className="bg-muted text-foreground/70 flex size-9 shrink-0 items-center justify-center rounded-xl">
                  <Icon className="size-4" aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold">
                    {link.label}
                  </span>
                  <span className="text-muted-foreground block truncate text-xs">
                    {link.description}
                  </span>
                </span>
                <ArrowUpRight
                  className="text-muted-foreground/40 group-hover:text-foreground size-4 shrink-0 transition-colors"
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
