"use client";

// Müşteri Yolculuğu Hunisi — yorum yazanların markayla ilişkide
// bulunduğu nokta (migration 0052, review.journey_stage).
//
// Biçim: yatay çubuklar, huni sırasında (lib/journey.ts). Tek ton:
// çubuk uzunluğu = yorum sayısı; içindeki koyu segment = olumsuz pay
// (durum rengi, yalnız duygu için). Rakamlar ve etiketler metin
// tonlarında, renk kimlik taşımaz. Sayılar /analytics/journey-
// distribution'dan gelir; burada hiçbir şey yeniden türetilmez.
//
// Yüzde paydası = aşaması atanmış yorumlar. Atanmamış satırlar paydaya
// girmez; altta "yeniden analizle atanır" notu + (yönetici için) CTA.
// Her satır /reviews'a derin bağlantıdır (journey_stages=<kod> + varsa
// ek daraltma, ör. sources=twitter).

import { ArrowRight, Info } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import type { JourneyDistribution } from "@/hooks/use-journey";
import { useReanalyzeAllReviews } from "@/hooks/use-reanalyze";
import { useRoleFlags } from "@/hooks/use-role-flags";
import { useTranslation } from "@/lib/i18n/use-translation";
import { JOURNEY_STAGES, PRE_PURCHASE_STAGES, journeyLabelKey } from "@/lib/journey";

interface Props {
  data: JourneyDistribution | undefined;
  isLoading: boolean;
  /** Başlık; varsayılan dashboard.journey.title. */
  title?: string;
  /** Başlık altı kısa açıklama (ör. Twitter sayfasında KVKK notu). */
  description?: string;
  /** Satır bağlantılarına eklenen ek /reviews filtreleri (sources, batch_job_id). */
  drilldownParams?: Record<string, string>;
  /** Sıfır veri durumunda bileşeni tamamen gizle (dashboard) ya da boş
   *  metin göster (Twitter sayfası). */
  hideWhenEmpty?: boolean;
}

export function JourneyFunnelCard({
  data,
  isLoading,
  title,
  description,
  drilldownParams,
  hideWhenEmpty = true,
}: Props) {
  const { t, locale } = useTranslation();
  if (isLoading || !data) {
    return <Skeleton className="h-64 w-full rounded-3xl" />;
  }
  const nf = new Intl.NumberFormat(locale === "en" ? "en-US" : "tr-TR");
  const heading = title ?? t("dashboard.journey.title");
  const empty = data.total === 0 && data.atanmamis.total === 0;
  if (empty && hideWhenEmpty) return null;

  const rows = JOURNEY_STAGES.map((code) => {
    const row = data.stages.find((s) => s.stage === code);
    return { code, total: row?.total ?? 0, negatif: row?.negatif ?? 0 };
  });
  const max = Math.max(1, ...rows.map((r) => r.total));
  const pct = (n: number) => (data.total === 0 ? 0 : Math.round((n / data.total) * 1000) / 10);
  const prePurchase = rows
    .filter((r) => PRE_PURCHASE_STAGES.has(r.code))
    .reduce((acc, r) => acc + r.total, 0);
  const churn = rows.find((r) => r.code === "ayrilma")?.total ?? 0;

  const hrefFor = (code: string): string => {
    const params = new URLSearchParams(drilldownParams ?? {});
    params.set("journey_stages", code);
    return `/reviews?${params.toString()}`;
  };

  return (
    <section
      aria-label={heading}
      className="bg-card text-card-foreground rounded-3xl border p-5 shadow-sm md:p-6"
    >
      <header className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h2 className="flex items-center gap-1.5 text-base font-semibold">
            {heading}
            <JourneyInfoTip />
          </h2>
          {description ? (
            <p className="text-muted-foreground max-w-prose text-xs">{description}</p>
          ) : null}
        </div>
        {data.total > 0 ? (
          <dl className="flex gap-5 text-sm">
            <div>
              <dt className="text-muted-foreground text-xs">{t("dashboard.journey.prospects")}</dt>
              <dd className="font-semibold tabular-nums">{pct(prePurchase)}%</dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">{t("dashboard.journey.churnRisk")}</dt>
              <dd className="text-sentiment-negative font-semibold tabular-nums">{pct(churn)}%</dd>
            </div>
          </dl>
        ) : null}
      </header>

      {data.total === 0 ? (
        <p className="text-muted-foreground text-sm">{t("dashboard.journey.empty")}</p>
      ) : (
        <ol className="space-y-2" aria-label={heading}>
          {rows.map((row) => {
            const width = (row.total / max) * 100;
            const negativeWidth = row.total === 0 ? 0 : (row.negatif / row.total) * 100;
            const label = t(journeyLabelKey(row.code));
            const inner = (
              <>
                <span className="w-36 shrink-0 truncate text-sm sm:w-44">{label}</span>
                <span className="bg-muted/60 relative h-6 min-w-0 flex-1 overflow-hidden rounded-l-sm rounded-r-md">
                  {row.total > 0 ? (
                    <span
                      className="bg-primary/70 absolute inset-y-0 left-0 flex overflow-hidden rounded-r-md"
                      style={{ width: `${Math.max(width, 1.5)}%` }}
                      aria-hidden
                    >
                      <span
                        className="bg-sentiment-negative/80 h-full"
                        style={{ width: `${negativeWidth}%` }}
                      />
                    </span>
                  ) : null}
                </span>
                <span className="w-28 shrink-0 text-right text-sm tabular-nums">
                  <span className="font-semibold">{nf.format(row.total)}</span>
                  <span className="text-muted-foreground"> · {pct(row.total)}%</span>
                </span>
                <span className="text-muted-foreground hidden w-24 shrink-0 text-right text-xs tabular-nums md:inline">
                  {row.negatif > 0
                    ? t("dashboard.journey.negativeShare", { count: nf.format(row.negatif) })
                    : ""}
                </span>
              </>
            );
            return (
              <li key={row.code}>
                {row.total > 0 ? (
                  <Link
                    href={hrefFor(row.code)}
                    className="hover:bg-muted/40 group flex items-center gap-3 rounded-md px-1 py-0.5"
                    title={t("dashboard.journey.viewReviews")}
                  >
                    {inner}
                    <ArrowRight
                      className="text-muted-foreground size-3.5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                      aria-hidden
                    />
                  </Link>
                ) : (
                  <div className="text-muted-foreground flex items-center gap-3 px-1 py-0.5">
                    {inner}
                    <span className="size-3.5 shrink-0" aria-hidden />
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      )}

      {data.atanmamis.total > 0 ? (
        <UnassignedNote
          noteText={t("dashboard.journey.unassignedNote", {
            count: nf.format(data.atanmamis.total),
          })}
          href={hrefFor("atanmamis")}
        />
      ) : null}
    </section>
  );
}

function JourneyInfoTip() {
  const { t } = useTranslation();
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger
          render={
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground inline-flex"
              aria-label={t("dashboard.journey.infoAria")}
            />
          }
        >
          <Info className="size-4" aria-hidden />
        </TooltipTrigger>
        <TooltipContent className="max-w-xs text-xs leading-relaxed">
          {t("dashboard.journey.info")}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

/** experience-breakdown-cards.tsx#UnassignedNote ile aynı desen:
 *  yönetici tüm yorumları yeniden analiz edebilir, diğer roller
 *  atanmamış satırları listede açar. */
function UnassignedNote({ noteText, href }: { noteText: string; href: string }) {
  const { t } = useTranslation();
  const { isAdmin } = useRoleFlags();
  const reanalyzeAll = useReanalyzeAllReviews();
  const [confirmOpen, setConfirmOpen] = useState(false);

  function handleConfirm() {
    reanalyzeAll.mutate(undefined, {
      onSuccess: () => {
        toast.success(t("dashboard.experience.reanalyzeQueued"));
        setConfirmOpen(false);
      },
      onError: () => toast.error(t("dashboard.experience.reanalyzeFailed")),
    });
  }

  return (
    <p className="text-muted-foreground mt-3 flex flex-wrap items-center gap-x-1.5 gap-y-1 text-xs">
      <Link href={href} className="underline-offset-4 hover:underline">
        {noteText}
      </Link>
      {isAdmin ? (
        <>
          <Button
            type="button"
            variant="link"
            className="h-auto p-0 text-xs"
            onClick={() => setConfirmOpen(true)}
            disabled={reanalyzeAll.isPending}
          >
            {t("dashboard.experience.reanalyzeCta")}
          </Button>
          <AlertDialog open={confirmOpen} onOpenChange={setConfirmOpen}>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>{t("dashboard.experience.reanalyzeCta")}</AlertDialogTitle>
                <AlertDialogDescription>
                  {t("dashboard.experience.reanalyzeConfirm")}
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel disabled={reanalyzeAll.isPending}>
                  {t("common.cancel")}
                </AlertDialogCancel>
                <AlertDialogAction onClick={handleConfirm} disabled={reanalyzeAll.isPending}>
                  {t("dashboard.experience.reanalyzeCta")}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </>
      ) : null}
    </p>
  );
}
