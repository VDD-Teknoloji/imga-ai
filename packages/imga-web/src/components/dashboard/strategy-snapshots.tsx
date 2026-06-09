"use client";

// Sprint 10.0 — Son SWOT + Son OKR kartları.
//
// Yöneticinin "stratejik olarak neredeyiz?" sorusuna ana sayfada
// cevap: son SWOT'un 2 güçlü + 2 zayıf yönü + en yüksek öncelikli
// tavsiyesi; son OKR'nin hedefleri + ölçülebilir anahtar
// sonuçları. Rapor yoksa 1-dakika CTA kartı — "haftalarca süren
// stratejik analiz dakikalara indi" anlatısının kapısı.

import { ArrowRight, Compass, Target } from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import type {
  ExecutiveOkrSnapshot,
  ExecutiveSwotSnapshot,
} from "@/hooks/use-executive-overview";
import { formatDateTr, relativeTimeTr } from "@/lib/relative-time";

// --- SWOT ---------------------------------------------------------------

export function SwotSnapshotCard({
  swot,
  isLoading,
}: {
  swot: ExecutiveSwotSnapshot | null | undefined;
  isLoading: boolean;
}) {
  if (isLoading) return <Skeleton className="h-72 rounded-2xl" />;

  if (!swot) {
    return (
      <EmptyStrategyCard
        Icon={Compass}
        title="SWOT analizinizi 1 dakikada oluşturun"
        description="Yapay zeka tüm yorumlarınızı okur; güçlü ve zayıf yönlerinizi, fırsat ve tehditleri kanıtlarıyla çıkarır."
        cta="SWOT oluştur"
      />
    );
  }

  return (
    <section className="rise-in shadow-soft bg-card ring-foreground/5 flex flex-col rounded-2xl p-5 md:p-6 ring-1">
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="from-primary/15 to-primary/5 text-primary ring-primary/15 flex size-9 items-center justify-center rounded-xl bg-gradient-to-br ring-1">
            <Compass className="size-4" aria-hidden />
          </span>
          <h3 className="text-base md:text-lg font-semibold">Son SWOT Analizi</h3>
        </div>
        <span
          className="text-muted-foreground text-xs"
          title={formatDateTr(swot.created_at)}
        >
          {relativeTimeTr(swot.created_at)}
        </span>
      </header>

      <div className="mt-4 grid flex-1 grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <p className="text-emerald-700 dark:text-emerald-400 text-[11px] font-bold uppercase tracking-[0.12em]">
            Güçlü Yönler
          </p>
          <ul className="mt-2 space-y-2">
            {swot.strengths.map((s, i) => (
              <li key={i} className="flex items-start gap-2 text-sm leading-snug">
                <span className="bg-emerald-500 mt-1.5 size-2 shrink-0 rounded-full" aria-hidden />
                <span className="font-medium">{s.title}</span>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <p className="text-red-700 dark:text-red-400 text-[11px] font-bold uppercase tracking-[0.12em]">
            Zayıf Yönler
          </p>
          <ul className="mt-2 space-y-2">
            {swot.weaknesses.map((w, i) => (
              <li key={i} className="flex items-start gap-2 text-sm leading-snug">
                <span className="bg-red-500 mt-1.5 size-2 shrink-0 rounded-full" aria-hidden />
                <span className="font-medium">{w.title}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {swot.top_recommendation && (
        <div className="bg-primary/8 ring-primary/15 mt-4 rounded-xl p-3.5 ring-1">
          <p className="text-primary text-[10px] font-bold uppercase tracking-[0.12em]">
            Öncelikli Tavsiye
          </p>
          <p className="mt-1 text-sm font-semibold leading-snug">
            {swot.top_recommendation.title}
          </p>
          <p className="text-muted-foreground mt-0.5 line-clamp-2 text-xs leading-relaxed">
            {swot.top_recommendation.description}
          </p>
        </div>
      )}

      <Link
        href="/strategy"
        className="text-primary mt-4 inline-flex items-center gap-1 text-sm font-semibold hover:underline"
      >
        Analizin tamamı
        <ArrowRight className="size-4" aria-hidden />
      </Link>
    </section>
  );
}

// --- OKR ----------------------------------------------------------------

export function OkrSnapshotCard({
  okr,
  isLoading,
}: {
  okr: ExecutiveOkrSnapshot | null | undefined;
  isLoading: boolean;
}) {
  if (isLoading) return <Skeleton className="h-72 rounded-2xl" />;

  if (!okr) {
    return (
      <EmptyStrategyCard
        Icon={Target}
        title="OKR hedeflerinizi 1 dakikada oluşturun"
        description="SWOT analizinizden yola çıkarak önümüzdeki 12 hafta için ölçülebilir hedefler ve anahtar sonuçlar üretilir."
        cta="OKR oluştur"
      />
    );
  }

  return (
    <section className="rise-in shadow-soft bg-card ring-foreground/5 flex flex-col rounded-2xl p-5 md:p-6 ring-1">
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="from-primary/15 to-primary/5 text-primary ring-primary/15 flex size-9 items-center justify-center rounded-xl bg-gradient-to-br ring-1">
            <Target className="size-4" aria-hidden />
          </span>
          <h3 className="text-base md:text-lg font-semibold">Son OKR Hedefleri</h3>
        </div>
        <span
          className="text-muted-foreground text-xs"
          title={formatDateTr(okr.created_at)}
        >
          {relativeTimeTr(okr.created_at)}
        </span>
      </header>

      <div className="mt-4 flex-1 space-y-4">
        {okr.objectives.map((obj, i) => (
          <div key={i}>
            <p className="text-sm md:text-base font-semibold leading-snug">
              {obj.objective}
            </p>
            <ul className="mt-2 space-y-1.5">
              {obj.key_results.map((kr, j) => (
                <li
                  key={j}
                  className="text-muted-foreground flex flex-wrap items-baseline gap-x-2 text-xs md:text-sm leading-relaxed"
                >
                  <span className="text-foreground/80">{kr.text}</span>
                  {kr.baseline && kr.target ? (
                    <span className="text-primary font-semibold tabular-nums whitespace-nowrap">
                      {kr.baseline} → {kr.target}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <Link
        href="/strategy"
        className="text-primary mt-4 inline-flex items-center gap-1 text-sm font-semibold hover:underline"
      >
        Hedeflerin tamamı
        <ArrowRight className="size-4" aria-hidden />
      </Link>
    </section>
  );
}

// --- shared empty CTA ----------------------------------------------------

function EmptyStrategyCard({
  Icon,
  title,
  description,
  cta,
}: {
  Icon: typeof Compass;
  title: string;
  description: string;
  cta: string;
}) {
  return (
    <Link
      href="/strategy"
      className="rise-in hover-lift shadow-soft group flex flex-col items-start justify-center rounded-2xl border border-dashed border-primary/30 bg-primary/4 p-6 md:p-8"
    >
      <span className="from-primary/20 to-primary/5 text-primary ring-primary/20 flex size-11 items-center justify-center rounded-xl bg-gradient-to-br ring-1">
        <Icon className="size-5" aria-hidden />
      </span>
      <p className="mt-4 text-base md:text-lg font-semibold leading-snug">{title}</p>
      <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
        {description}
      </p>
      <span className="text-primary mt-4 inline-flex items-center gap-1 text-sm font-semibold group-hover:underline">
        {cta}
        <ArrowRight className="size-4" aria-hidden />
      </span>
    </Link>
  );
}
