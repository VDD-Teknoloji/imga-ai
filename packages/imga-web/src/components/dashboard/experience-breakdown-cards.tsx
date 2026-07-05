"use client";

// Sprint 13 — Deneyim Dağılımı kartları (ürün sahibi görsel
// referansı: legacy prototipin "Experience Breakdown" bölümü —
// iki büyük renkli kart, dev yüzde + tıkla-filtrele).
//
// Dijital (mavi) / Operasyonel (turuncu): klasik CVD-güvenli çift.
// Yüzde, seçili dönemdeki sınıflandırılmış ('belirsiz' hariç)
// yorumların deneyim tipine dağılımı; kart tıklaması /reviews'u o
// deneyimin kategorileriyle filtreli açar.

import { ArrowRight, Info, Monitor, Package } from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { experienceOf, type ExperienceType } from "@/lib/experience";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { CategoryDistResponse } from "@/lib/types";

interface Props {
  data: CategoryDistResponse | undefined;
  isLoading: boolean;
}

interface Bucket {
  count: number;
  codes: string[];
}

function bucketize(data: CategoryDistResponse): Record<ExperienceType, Bucket> {
  const buckets: Record<ExperienceType, Bucket> = {
    dijital: { count: 0, codes: [] },
    operasyonel: { count: 0, codes: [] },
  };
  for (const row of data.data) {
    const kind = experienceOf(row.category);
    if (kind === null) continue;
    buckets[kind].count += row.count;
    buckets[kind].codes.push(row.category);
  }
  return buckets;
}

export function ExperienceBreakdownCards({ data, isLoading }: Props) {
  const { t, locale } = useTranslation();
  if (isLoading || !data) {
    return <Skeleton className="h-44 w-full rounded-3xl" />;
  }

  const buckets = bucketize(data);
  const total = buckets.dijital.count + buckets.operasyonel.count;
  if (total === 0) return null;

  const nf = new Intl.NumberFormat(locale === "en" ? "en-US" : "tr-TR");
  const pct = (n: number) => Math.round((n / total) * 1000) / 10;

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
          pct={pct(buckets.dijital.count)}
          count={nf.format(buckets.dijital.count)}
          countLabel={t("dashboard.experience.reviews")}
          filterLabel={t("dashboard.experience.viewReviews")}
          href={`/reviews?primary_categories=${encodeURIComponent(buckets.dijital.codes.join(","))}`}
          className="from-blue-600 to-blue-500"
          disabled={buckets.dijital.count === 0}
        />
        <ExperienceCard
          label={t("dashboard.experience.operational")}
          icon={<Package className="size-5" aria-hidden />}
          pct={pct(buckets.operasyonel.count)}
          count={nf.format(buckets.operasyonel.count)}
          countLabel={t("dashboard.experience.reviews")}
          filterLabel={t("dashboard.experience.viewReviews")}
          href={`/reviews?primary_categories=${encodeURIComponent(buckets.operasyonel.codes.join(","))}`}
          className="from-orange-600 to-orange-500"
          disabled={buckets.operasyonel.count === 0}
        />
      </div>
    </section>
  );
}

function ExperienceCard({
  label,
  icon,
  pct,
  count,
  countLabel,
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
