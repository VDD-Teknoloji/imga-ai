"use client";

// Sprint 13 — NPS segment dağılımı kartı (ürün sahibi görsel
// referansı: legacy prototipin "NPS Distribution (Management View)"
// tablosu). Destekçi / Pasif / Kötüleyen sayıları + oranları ve
// büyük NPS skoru — yönetici tek bakışta okur. Renk kutupsal:
// yeşil destekçi, gri pasif (nötr orta nokta), kırmızı kötüleyen;
// kimlik renk-tek-başına değil — her satırda etiket + sayı var.

import { Info } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { NPSSummary } from "@/lib/types";

interface Props {
  data: NPSSummary | undefined;
  isLoading: boolean;
}

interface SegmentRow {
  labelKey: string;
  count: number;
  barClass: string;
  dotClass: string;
}

export function NpsBreakdownCard({ data, isLoading }: Props) {
  const { t, locale } = useTranslation();
  if (isLoading || !data) {
    return <Skeleton className="h-56 w-full rounded-3xl" />;
  }

  const nf = new Intl.NumberFormat(locale === "en" ? "en-US" : "tr-TR");
  const total = data.total_count;

  const rows: SegmentRow[] = [
    {
      labelKey: "dashboard.npsCard.promoters",
      count: data.promoter_count,
      barClass: "bg-emerald-500",
      dotClass: "bg-emerald-500",
    },
    {
      labelKey: "dashboard.npsCard.passives",
      count: data.passive_count,
      barClass: "bg-zinc-300 dark:bg-zinc-600",
      dotClass: "bg-zinc-300 dark:bg-zinc-600",
    },
    {
      labelKey: "dashboard.npsCard.detractors",
      count: data.detractor_count,
      barClass: "bg-red-500",
      dotClass: "bg-red-500",
    },
  ];

  return (
    <section
      className="shadow-soft bg-card ring-foreground/5 rounded-3xl p-6 ring-1 md:p-7"
      aria-label={t("dashboard.npsCard.title")}
    >
      <header className="flex items-start justify-between gap-4">
        <div>
          <h2 className="inline-flex items-center gap-1.5 text-base font-semibold">
            {t("dashboard.npsCard.title")}
            <NpsInfoTip />
          </h2>
          {total > 0 && (
            <p className="text-muted-foreground mt-0.5 text-xs">
              {t("dashboard.npsCard.coverage", {
                pct: Math.round(data.coverage_percent),
              })}
            </p>
          )}
        </div>
        {data.score !== null && (
          <div className="text-right">
            <span className="text-4xl font-semibold tabular-nums tracking-tight">
              {data.score > 0 ? "+" : ""}
              {Math.round(data.score)}
            </span>
            <p className="text-muted-foreground text-xs font-medium">
              {t("dashboard.npsCard.scoreLabel")}
            </p>
          </div>
        )}
      </header>

      {total === 0 ? (
        <p className="text-muted-foreground mt-5 text-sm leading-relaxed">
          {t("dashboard.npsCard.empty")}
        </p>
      ) : (
        <ul className="mt-5 space-y-3">
          {rows.map((row) => {
            const pct = total > 0 ? (row.count / total) * 100 : 0;
            const pctText = (Math.round(pct * 10) / 10).toLocaleString(
              locale === "en" ? "en-US" : "tr-TR",
            );
            return (
              <li key={row.labelKey} className="flex items-center gap-3">
                <span
                  className={`size-2.5 shrink-0 rounded-full ${row.dotClass}`}
                  aria-hidden
                />
                <span className="text-foreground/80 w-28 shrink-0 truncate text-sm font-medium">
                  {t(row.labelKey)}
                </span>
                <div className="bg-muted h-2 min-w-0 flex-1 overflow-hidden rounded-full">
                  <div
                    className={`h-full rounded-full ${row.barClass}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="text-muted-foreground w-24 shrink-0 text-right text-sm tabular-nums">
                  {nf.format(row.count)}{" "}
                  <span className="text-muted-foreground/70">%{pctText}</span>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function NpsInfoTip() {
  const { t } = useTranslation();
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger
          aria-label={t("dashboard.npsCard.infoAria")}
          className="text-muted-foreground/70 hover:text-foreground inline-flex cursor-help items-center transition-colors"
        >
          <Info className="size-3.5" aria-hidden />
        </TooltipTrigger>
        <TooltipContent className="max-w-72 leading-relaxed">
          {t("dashboard.npsCard.info")}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
