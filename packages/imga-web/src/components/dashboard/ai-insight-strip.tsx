"use client";

// Sprint 10.0 — Yapay Zeka Özeti şeridi.
//
// Son yönetici özetinin (executive briefing) headline'ı + en
// kritik 3 içgörüsü. "Haftalarca süren işi dakikalara indirdik"
// anlatısının görünür kanıtı: yönetici, yapay zekanın yazdığı
// tek cümlelik durum özetini ana sayfada görür. Özet yoksa
// 1-dakika CTA'sı — demo akışının ikinci adımı.

import { ArrowRight, Sparkles } from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import type { ExecutiveBriefingSnapshot } from "@/hooks/use-executive-overview";
import { formatDateTr, relativeTimeTr } from "@/lib/relative-time";

const PERIOD_TR: Record<string, string> = {
  week: "Haftalık",
  month: "Aylık",
  quarter: "Üç aylık",
};

interface Props {
  briefing: ExecutiveBriefingSnapshot | null | undefined;
  isLoading: boolean;
}

export function AiInsightStrip({ briefing, isLoading }: Props) {
  if (isLoading) return <Skeleton className="h-36 w-full rounded-2xl" />;

  if (!briefing) {
    return (
      <Link
        href="/executive-briefing"
        className="rise-in hover-lift shadow-soft group flex items-center gap-4 rounded-2xl border border-primary/20 bg-gradient-to-r from-primary/8 via-card to-card p-5"
      >
        <span className="from-primary/20 to-primary/5 text-primary ring-primary/20 flex size-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ring-1">
          <Sparkles className="size-5" aria-hidden />
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-sm md:text-base font-semibold">
            Yapay zeka yönetici özetinizi 1 dakikada oluşturun
          </p>
          <p className="text-muted-foreground text-xs md:text-sm">
            Dönemin KPI değişimleri, kritik içgörüler ve öncelikli
            aksiyonlar — tek tıkla.
          </p>
        </div>
        <ArrowRight
          className="text-muted-foreground/60 group-hover:text-primary size-5 shrink-0 transition-colors"
          aria-hidden
        />
      </Link>
    );
  }

  return (
    <section
      className="rise-in shadow-soft rounded-2xl border border-primary/20 bg-gradient-to-r from-primary/8 via-card to-card p-5 md:p-6"
      aria-label="Yapay zeka özeti"
    >
      <div className="flex items-start gap-4">
        <span className="from-primary/20 to-primary/5 text-primary ring-primary/20 flex size-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ring-1">
          <Sparkles className="size-5" aria-hidden />
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-primary text-[11px] font-bold uppercase tracking-[0.14em]">
            Yapay Zeka Özeti · {PERIOD_TR[briefing.period] ?? briefing.period} ·{" "}
            <span
              className="text-muted-foreground font-semibold"
              title={formatDateTr(briefing.created_at)}
            >
              {relativeTimeTr(briefing.created_at)}
            </span>
          </p>
          <p className="mt-1.5 text-base md:text-xl font-semibold leading-snug">
            {briefing.headline}
          </p>
          {briefing.critical_insights.length > 0 && (
            <ul className="mt-3 space-y-1.5">
              {briefing.critical_insights.map((insight, i) => (
                <li
                  key={i}
                  className="text-foreground/80 flex items-start gap-2 text-sm leading-relaxed"
                >
                  <span
                    className="bg-primary mt-2 size-1.5 shrink-0 rounded-full"
                    aria-hidden
                  />
                  {insight}
                </li>
              ))}
            </ul>
          )}
          <Link
            href="/executive-briefing"
            className="text-primary mt-3 inline-flex items-center gap-1 text-sm font-semibold hover:underline"
          >
            Özetin tamamını gör
            <ArrowRight className="size-4" aria-hidden />
          </Link>
        </div>
      </div>
    </section>
  );
}
