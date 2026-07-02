"use client";

// Sprint 12 — Son SWOT + Son OKR kartları (sakin sürüm).
//
// Yöneticinin "stratejik olarak neredeyiz?" sorusuna ana sayfada
// kısa cevap. Sakinleştirildi: gradient ikon kutuları kaldırıldı,
// daha çok boşluk, daha az satır. SWOT'un öncelikli tavsiyesi artık
// hero altındaki "Bu ayki önceliğiniz" çağrısında — burada
// tekrarlanmaz; bu kart güçlü/zayıf özetini verir. Detay /strategy.

import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import type {
  ExecutiveOkrSnapshot,
  ExecutiveSwotSnapshot,
} from "@/hooks/use-executive-overview";
import { useTranslation } from "@/lib/i18n/use-translation";
import { formatDateTr, relativeTimeTr } from "@/lib/relative-time";

// --- SWOT ---------------------------------------------------------------

export function SwotSnapshotCard({
  swot,
  isLoading,
}: {
  swot: ExecutiveSwotSnapshot | null | undefined;
  isLoading: boolean;
}) {
  const { t } = useTranslation();
  if (isLoading) return <Skeleton className="h-64 rounded-3xl" />;

  if (!swot) {
    return (
      <EmptyStrategyCard
        title={t("dashboard.strategySnapshots.swot.emptyTitle")}
        description={t("dashboard.strategySnapshots.swot.emptyDesc")}
        cta={t("dashboard.strategySnapshots.swot.emptyCta")}
      />
    );
  }

  return (
    <section className="rise-in shadow-soft bg-card ring-foreground/5 flex flex-col rounded-3xl p-6 ring-1 md:p-7">
      <header className="flex items-baseline justify-between gap-3">
        <h3 className="text-lg font-semibold tracking-tight">
          {t("dashboard.strategySnapshots.swot.title")}
        </h3>
        <span
          className="text-muted-foreground/70 text-xs"
          title={formatDateTr(swot.created_at)}
        >
          {relativeTimeTr(swot.created_at)}
        </span>
      </header>

      <div className="mt-5 grid flex-1 grid-cols-1 gap-5 sm:grid-cols-2">
        <SwotColumn
          label={t("dashboard.strategySnapshots.swot.strengths")}
          dotClass="bg-emerald-500"
          items={swot.strengths.map((s) => s.title)}
        />
        <SwotColumn
          label={t("dashboard.strategySnapshots.swot.weaknesses")}
          dotClass="bg-red-400"
          items={swot.weaknesses.map((w) => w.title)}
        />
      </div>

      <Link
        href="/strategy"
        className="text-foreground/70 hover:text-foreground mt-6 inline-flex items-center gap-1.5 text-sm font-semibold transition-colors"
      >
        {t("dashboard.strategySnapshots.swot.seeFull")}
        <ArrowRight className="size-4" aria-hidden />
      </Link>
    </section>
  );
}

function SwotColumn({
  label,
  dotClass,
  items,
}: {
  label: string;
  dotClass: string;
  items: string[];
}) {
  return (
    <div>
      <p className="text-muted-foreground text-xs font-semibold">{label}</p>
      <ul className="mt-2.5 space-y-2.5">
        {items.map((title, i) => (
          <li key={i} className="flex items-start gap-2.5 text-sm leading-snug">
            <span
              className={`mt-1.5 size-1.5 shrink-0 rounded-full ${dotClass}`}
              aria-hidden
            />
            <span className="font-medium">{title}</span>
          </li>
        ))}
      </ul>
    </div>
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
  const { t } = useTranslation();
  if (isLoading) return <Skeleton className="h-64 rounded-3xl" />;

  if (!okr) {
    return (
      <EmptyStrategyCard
        title={t("dashboard.strategySnapshots.okr.emptyTitle")}
        description={t("dashboard.strategySnapshots.okr.emptyDesc")}
        cta={t("dashboard.strategySnapshots.okr.emptyCta")}
      />
    );
  }

  return (
    <section className="rise-in shadow-soft bg-card ring-foreground/5 flex flex-col rounded-3xl p-6 ring-1 md:p-7">
      <header className="flex items-baseline justify-between gap-3">
        <h3 className="text-lg font-semibold tracking-tight">
          {t("dashboard.strategySnapshots.okr.title")}
        </h3>
        <span
          className="text-muted-foreground/70 text-xs"
          title={formatDateTr(okr.created_at)}
        >
          {relativeTimeTr(okr.created_at)}
        </span>
      </header>

      <div className="mt-5 flex-1 space-y-5">
        {okr.objectives.map((obj, i) => (
          <div key={i}>
            <p className="text-base font-semibold leading-snug">
              {obj.objective}
            </p>
            <ul className="mt-2.5 space-y-2">
              {obj.key_results.map((kr, j) => (
                <li
                  key={j}
                  className="text-muted-foreground flex flex-wrap items-baseline gap-x-2 text-sm leading-relaxed"
                >
                  <span className="text-foreground/80">{kr.text}</span>
                  {kr.baseline && kr.target ? (
                    <span className="text-foreground font-semibold tabular-nums whitespace-nowrap">
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
        className="text-foreground/70 hover:text-foreground mt-6 inline-flex items-center gap-1.5 text-sm font-semibold transition-colors"
      >
        {t("dashboard.strategySnapshots.okr.seeFull")}
        <ArrowRight className="size-4" aria-hidden />
      </Link>
    </section>
  );
}

// --- shared empty CTA ----------------------------------------------------

function EmptyStrategyCard({
  title,
  description,
  cta,
}: {
  title: string;
  description: string;
  cta: string;
}) {
  return (
    <Link
      href="/strategy"
      className="rise-in hover-lift shadow-soft group ring-foreground/10 flex flex-col items-start justify-center rounded-3xl border border-dashed p-6 md:p-8"
    >
      <p className="text-lg font-semibold leading-snug">{title}</p>
      <p className="text-muted-foreground mt-2 text-sm leading-relaxed">
        {description}
      </p>
      <span className="text-foreground/70 group-hover:text-foreground mt-4 inline-flex items-center gap-1.5 text-sm font-semibold transition-colors">
        {cta}
        <ArrowRight className="size-4" aria-hidden />
      </span>
    </Link>
  );
}
