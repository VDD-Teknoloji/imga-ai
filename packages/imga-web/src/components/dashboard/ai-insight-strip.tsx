"use client";

// Sprint 12 — Yönetici Özeti şeridi.
//
// Son yönetici özetinin headline'ı + en kritik 3 içgörüsü.
// Sakinleştirildi: sparkle ikon + turuncu gradient kaldırıldı
// (o motif "yapay zeka ürünü" hissi veriyordu). Aydınlık sade kart;
// içerik konuşsun. Özet yoksa düşük-tonlu CTA.

import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import type { ExecutiveBriefingSnapshot } from "@/hooks/use-executive-overview";
import { useTranslation } from "@/lib/i18n/use-translation";
import { formatDateTr, relativeTimeTr } from "@/lib/relative-time";

const PERIOD_KEYS: Record<string, string> = {
  week: "dashboard.aiInsight.period.week",
  month: "dashboard.aiInsight.period.month",
  quarter: "dashboard.aiInsight.period.quarter",
};

interface Props {
  briefing: ExecutiveBriefingSnapshot | null | undefined;
  isLoading: boolean;
}

export function AiInsightStrip({ briefing, isLoading }: Props) {
  const { t } = useTranslation();
  if (isLoading) return <Skeleton className="h-40 w-full rounded-3xl" />;

  if (!briefing) {
    return (
      <Link
        href="/executive-briefing"
        className="rise-in hover-lift shadow-soft group bg-card ring-foreground/5 flex items-center gap-4 rounded-3xl p-5 ring-1 md:p-6"
      >
        <div className="min-w-0 flex-1">
          <p className="text-base font-semibold">
            {t("dashboard.aiInsight.empty.title")}
          </p>
          <p className="text-muted-foreground mt-1 text-sm">
            {t("dashboard.aiInsight.empty.desc")}
          </p>
        </div>
        <ArrowRight
          className="text-muted-foreground/50 group-hover:text-foreground size-5 shrink-0 transition-colors"
          aria-hidden
        />
      </Link>
    );
  }

  const periodKey = PERIOD_KEYS[briefing.period];

  return (
    <section
      className="rise-in shadow-soft bg-card ring-foreground/5 rounded-3xl p-6 ring-1 md:p-8"
      aria-label={t("dashboard.aiInsight.aria")}
    >
      <p className="text-muted-foreground text-sm font-medium">
        {t("dashboard.aiInsight.label")} ·{" "}
        {periodKey ? t(periodKey) : briefing.period} ·{" "}
        <span title={formatDateTr(briefing.created_at)}>
          {relativeTimeTr(briefing.created_at)}
        </span>
      </p>
      <p className="mt-2 text-xl font-semibold leading-snug tracking-tight md:text-2xl">
        {briefing.headline}
      </p>
      {briefing.critical_insights.length > 0 && (
        <ul className="mt-4 space-y-2.5">
          {briefing.critical_insights.map((insight, i) => (
            <li
              key={i}
              className="text-foreground/80 flex items-start gap-2.5 text-sm leading-relaxed md:text-base"
            >
              <span
                className="bg-primary/60 mt-2.5 size-1.5 shrink-0 rounded-full"
                aria-hidden
              />
              {insight}
            </li>
          ))}
        </ul>
      )}
      <Link
        href="/executive-briefing"
        className="text-foreground/70 hover:text-foreground mt-5 inline-flex items-center gap-1.5 text-sm font-semibold transition-colors"
      >
        {t("dashboard.aiInsight.seeFull")}
        <ArrowRight className="size-4" aria-hidden />
      </Link>
    </section>
  );
}
