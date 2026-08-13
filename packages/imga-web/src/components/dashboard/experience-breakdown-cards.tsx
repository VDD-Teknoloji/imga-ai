"use client";

// Deneyim Dağılımı kartları (ürün sahibi görsel referansı: legacy
// prototipin "Experience Breakdown" bölümü — iki büyük renkli kart,
// dev yüzde + tıkla-filtrele).
//
// Dijital (mavi) / Operasyonel (turuncu): klasik CVD-güvenli çift.
// Sayılar /analytics/experience-distribution'dan gelir; kovalama
// backend'de review.experience_type üzerinden yapılır (null satırlar
// için eski kategori yedeği de orada uygulanır). Burada hiçbir şey
// yeniden türetilmez.
//
// Yüzde paydası = dijital + operasyonel. Kovaya düşemeyen satırlar
// (atanmamis) paydaya girmez; altta ayrı bir not olarak görünür.

import { ArrowRight, Info, Monitor, Package } from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useCategories } from "@/hooks/use-categories";
import type { ExperienceDistribution } from "@/hooks/use-experience";
import { experienceOf, type ExperienceType } from "@/lib/experience";
import { useTranslation } from "@/lib/i18n/use-translation";

interface Props {
  data: ExperienceDistribution | undefined;
  isLoading: boolean;
}

export function ExperienceBreakdownCards({ data, isLoading }: Props) {
  const { t, locale } = useTranslation();
  // Derin bağlantı filtresi için kategori kodları. Kartın SAYISI değil,
  // yalnız hedef URL'i besler — /reviews'ta henüz experience_type
  // filtresi yok, en yakın karşılık eski kategori eşlemesi.
  const categories = useCategories();
  if (isLoading || !data) {
    return <Skeleton className="h-44 w-full rounded-3xl" />;
  }

  const total = data.dijital.total + data.operasyonel.total;
  if (total === 0 && data.atanmamis.total === 0) return null;

  const codesFor = (kind: ExperienceType): string[] =>
    (categories.data ?? [])
      .filter((c) => experienceOf(c.code) === kind)
      .map((c) => c.code);

  const nf = new Intl.NumberFormat(locale === "en" ? "en-US" : "tr-TR");
  const pct = (n: number) => (total === 0 ? 0 : Math.round((n / total) * 1000) / 10);
  const hrefFor = (kind: ExperienceType): string => {
    const codes = codesFor(kind);
    return codes.length === 0
      ? "/reviews"
      : `/reviews?primary_categories=${encodeURIComponent(codes.join(","))}`;
  };

  return (
    <section aria-label={t("dashboard.experience.title")}>
      <header className="mb-3 flex items-center gap-1.5">
        <h2 className="text-base font-semibold">
          {t("dashboard.experience.title")}
        </h2>
        <ExperienceInfoTip />
      </header>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <ExperienceCard
          label={t("dashboard.experience.digital")}
          icon={<Monitor className="size-5" aria-hidden />}
          pct={pct(data.dijital.total)}
          count={nf.format(data.dijital.total)}
          countLabel={t("dashboard.experience.reviews")}
          negativeLabel={t("dashboard.experience.negativeShare", {
            count: nf.format(data.dijital.negatif),
          })}
          filterLabel={t("dashboard.experience.viewReviews")}
          href={hrefFor("dijital")}
          className="from-blue-600 to-blue-500"
          disabled={data.dijital.total === 0}
        />
        <ExperienceCard
          label={t("dashboard.experience.operational")}
          icon={<Package className="size-5" aria-hidden />}
          pct={pct(data.operasyonel.total)}
          count={nf.format(data.operasyonel.total)}
          countLabel={t("dashboard.experience.reviews")}
          negativeLabel={t("dashboard.experience.negativeShare", {
            count: nf.format(data.operasyonel.negatif),
          })}
          filterLabel={t("dashboard.experience.viewReviews")}
          href={hrefFor("operasyonel")}
          className="from-orange-600 to-orange-500"
          disabled={data.operasyonel.total === 0}
        />
      </div>
      {data.atanmamis.total > 0 && (
        <p className="text-muted-foreground mt-2.5 text-xs">
          {t("dashboard.experience.unassignedNote", {
            count: nf.format(data.atanmamis.total),
          })}
        </p>
      )}
    </section>
  );
}

function ExperienceCard({
  label,
  icon,
  pct,
  count,
  countLabel,
  negativeLabel,
  filterLabel,
  href,
  className,
  disabled,
}: {
  label: string;
  icon: React.ReactNode;
  pct: number;
  count: string;
  countLabel: string;
  negativeLabel: string;
  filterLabel: string;
  href: string;
  className: string;
  disabled: boolean;
}) {
  const { locale } = useTranslation();
  const pctText = pct.toLocaleString(locale === "en" ? "en-US" : "tr-TR");
  const body = (
    <div
      className={`shadow-soft flex h-full flex-col justify-between rounded-3xl bg-gradient-to-br p-6 text-white ${className}`}
    >
      <div className="flex items-center gap-2.5 text-sm font-semibold text-white/90">
        <span className="flex size-9 items-center justify-center rounded-xl bg-white/15">
          {icon}
        </span>
        {label}
      </div>
      <div className="mt-5 flex items-end justify-between gap-4">
        <div>
          <span className="text-5xl font-semibold tabular-nums tracking-tight md:text-6xl">
            %{pctText}
          </span>
          <p className="mt-1 text-sm text-white/80 tabular-nums">
            {count} {countLabel}
          </p>
          <p className="mt-0.5 text-xs text-white/70 tabular-nums">
            {negativeLabel}
          </p>
        </div>
        {!disabled && (
          <span className="inline-flex items-center gap-1.5 rounded-xl bg-white/15 px-3.5 py-2 text-xs font-semibold backdrop-blur transition-colors group-hover:bg-white/25">
            {filterLabel}
            <ArrowRight className="size-3.5" aria-hidden />
          </span>
        )}
      </div>
    </div>
  );
  if (disabled) return body;
  return (
    <Link href={href} className="group block h-full">
      {body}
    </Link>
  );
}

function ExperienceInfoTip() {
  const { t } = useTranslation();
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger
          aria-label={t("dashboard.experience.infoAria")}
          className="text-muted-foreground/70 hover:text-foreground inline-flex cursor-help items-center transition-colors"
        >
          <Info className="size-3.5" aria-hidden />
        </TooltipTrigger>
        <TooltipContent className="max-w-72 leading-relaxed">
          {t("dashboard.experience.info")}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
