"use client";

// Sprint 12 — sağ raydaki kompakt işlem listesi.
//
// "Ana sayfayı açan yönetici kolayca işlem yapabilsin": rapor sol
// kolonda akarken, sık kullanılan dört kapı sağ rayda dikey ve
// sade durur. UploadDock'un altında yaşar.

import { ArrowUpRight, Compass, FileBarChart, FileText, Sparkles, Ticket } from "lucide-react";
import Link from "next/link";

import { useTranslation } from "@/lib/i18n/use-translation";

const LINKS = [
  {
    href: "/executive-briefing",
    labelKey: "dashboard.quickLinks.briefing.label",
    descKey: "dashboard.quickLinks.briefing.desc",
    icon: FileText,
  },
  {
    href: "/strategy",
    labelKey: "dashboard.quickLinks.strategy.label",
    descKey: "dashboard.quickLinks.strategy.desc",
    icon: Compass,
  },
  {
    href: "/tickets",
    labelKey: "dashboard.quickLinks.tickets.label",
    descKey: "dashboard.quickLinks.tickets.desc",
    icon: Ticket,
  },
  {
    href: "/reports",
    labelKey: "dashboard.quickLinks.reports.label",
    descKey: "dashboard.quickLinks.reports.desc",
    icon: FileBarChart,
  },
] as const;

export function QuickLinks() {
  const { t } = useTranslation();
  return (
    <nav
      aria-label={t("dashboard.common.quickActions")}
      className="rise-in shadow-soft bg-card ring-foreground/5 overflow-hidden rounded-3xl ring-1"
      style={{ animationDelay: "120ms" }}
    >
      <h2 className="text-muted-foreground flex items-center gap-1.5 px-5 pt-4 pb-1 text-xs font-semibold">
        <Sparkles className="size-3.5" aria-hidden />
        {t("dashboard.common.quickActions")}
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
                  <span className="block truncate text-sm font-semibold">{t(link.labelKey)}</span>
                  <span className="text-muted-foreground block truncate text-xs">
                    {t(link.descKey)}
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
