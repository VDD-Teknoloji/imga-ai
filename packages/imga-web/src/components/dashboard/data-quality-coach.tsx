"use client";

// Sprint 13.2 — veri kalitesi koçu (A2), ClassificationQualityChip'in
// yerini alır.
//
// Eski sürüm 'belirsiz' KATEGORİ oranına bakıyordu (sınıflandırmanın
// kategoriye düşme başarısı). Bu kart farklı bir sinyale bakar: kalite
// bayraklı (boş/anlamsız/kopya) yorumların GİRDİ kalitesi — kök neden
// analizlerinin isabetini doğrudan etkileyen taraf.
//
// F1 (2026-09-02) — özet sorgusu page.tsx'te çağrılıyor ve prop olarak
// akıyor (FailingProcessesCard aynı veriyi kullanır; tek sorgu).
//
// 2026-09-02 (ürün sahibi) — tek kart üç ayrı karta bölündü, alt alta:
//   1. Şikâyet tehdidi (resmî şikâyet / dava) — EN ÜSTTE, risk sinyali
//   2. Veri kalitesi (boş/anlamsız/kopya oranı)
//   3. Soru sayısı (müşterilerin ne sorduğu)
// Sıfır olan sinyal kendi kartını hiç açmaz (sessizlik kuralı). Üç kart
// tek bileşenden fragment olarak döner; sağ rayın space-y aralığı
// doğrudan çocuklara uygulandığı için ayrı kartlar gibi dizilir.

import Link from "next/link";
import { ArrowRight, MessageCircleQuestion, Scale, ShieldAlert, ShieldCheck } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import type { ReviewSummaryResponse } from "@/hooks/use-review-summary";
import { useTranslation } from "@/lib/i18n/use-translation";

interface Props {
  summary: ReviewSummaryResponse | undefined;
  isLoading: boolean;
  isError: boolean;
  dateFrom?: string;
  dateTo?: string;
}

const CARD_CLASS =
  "rise-in shadow-soft bg-card ring-foreground/5 rounded-3xl p-5 break-words ring-1";

export function DataQualityCoach({ summary, isLoading, isError, dateFrom, dateTo }: Props) {
  const { t, locale } = useTranslation();
  const numberLocale = locale === "en" ? "en-US" : "tr-TR";

  if (isLoading) {
    return <Skeleton className="h-24 w-full rounded-3xl" />;
  }
  // Hata da boş de sessizce gizlenir — bu kartlar bir uyarı değil, ikinci
  // dereceden bir koç; sayfanın geri kalanını bloklamaya değmez.
  if (isError || !summary || summary.total === 0) {
    return null;
  }

  const { quality, question_count, total } = summary;
  // "boş/anlamsız/kopya" — informational ayrı tutulur (o soru sayısını
  // besler, kalite bayrağı değil, ayrı bir müşteri-sinyali).
  const flaggedCount = quality.duplicate + quality.empty + quality.meaningless;
  const flaggedPct = Math.round((flaggedCount / total) * 100);
  const escalationCount = summary.content_types?.escalation ?? 0;

  return (
    <>
      {escalationCount > 0 && (
        <section
          className={`${CARD_CLASS} ring-sentiment-negative/30`}
          aria-label={t("dashboard.dataQuality.escalationAria")}
        >
          <p className="text-sentiment-negative flex items-start gap-1.5 text-sm leading-relaxed font-medium">
            <Scale className="mt-0.5 size-4 shrink-0" aria-hidden />
            <span>
              {t("dashboard.dataQuality.escalation", {
                n: escalationCount.toLocaleString(numberLocale),
              })}
            </span>
          </p>
          <Link
            href={ctaHref(dateFrom, dateTo, "escalation")}
            className="text-sentiment-negative mt-3 inline-flex items-center gap-1.5 text-sm font-semibold hover:opacity-80"
          >
            {t("dashboard.dataQuality.escalationCta")}
            <ArrowRight className="size-4" aria-hidden />
          </Link>
        </section>
      )}

      {flaggedPct < 5 ? (
        // Sessizlik kuralı: kalite zaten iyiyse (< %5 bayraklı) uyarı tonunda
        // bir kart yerine tek sakin cümle — tablo yok, kırmızı yok.
        <section className={CARD_CLASS} aria-label={t("dashboard.dataQuality.aria")}>
          <p className="text-muted-foreground flex items-center gap-1.5 text-sm font-medium">
            <ShieldCheck
              className="size-4 shrink-0 text-emerald-600 dark:text-emerald-400"
              aria-hidden
            />
            {t("dashboard.dataQuality.good")}
          </p>
        </section>
      ) : (
        <section className={CARD_CLASS} aria-label={t("dashboard.dataQuality.aria")}>
          <p className="flex items-center gap-1.5 text-sm font-semibold">
            <ShieldAlert
              className="size-4 shrink-0 text-amber-600 dark:text-amber-400"
              aria-hidden
            />
            {t("dashboard.dataQuality.flaggedShare", {
              pct: flaggedPct,
              count: flaggedCount.toLocaleString(numberLocale),
            })}
          </p>
          <p className="text-muted-foreground mt-1 text-sm leading-relaxed">
            {t("dashboard.dataQuality.hint")}
          </p>
          <p className="text-muted-foreground mt-1 text-sm leading-relaxed">
            {t("dashboard.dataQuality.excluded")}
          </p>
          <Link
            href={ctaHref(dateFrom, dateTo)}
            className="text-primary hover:text-primary/80 mt-3 inline-flex items-center gap-1.5 text-sm font-semibold transition-colors"
          >
            {t("dashboard.dataQuality.cta")}
            <ArrowRight className="size-4" aria-hidden />
          </Link>
        </section>
      )}

      {question_count > 0 && (
        <section className={CARD_CLASS} aria-label={t("dashboard.dataQuality.questionsAria")}>
          <p className="flex items-center gap-1.5 text-sm font-semibold">
            <MessageCircleQuestion className="text-primary size-4 shrink-0" aria-hidden />
            {t("dashboard.dataQuality.questionCount", {
              n: question_count.toLocaleString(numberLocale),
            })}
          </p>
          <Link
            href={ctaHref(dateFrom, dateTo, "question")}
            className="text-primary hover:text-primary/80 mt-3 inline-flex items-center gap-1.5 text-sm font-semibold transition-colors"
          >
            {t("dashboard.dataQuality.questionsCta")}
            <ArrowRight className="size-4" aria-hidden />
          </Link>
        </section>
      )}
    </>
  );
}

/** RootCauseCards'ın evidenceHref'iyle aynı desen: sayfanın aktif dönemi
 *  varsa (date_from/date_to) /reviews'e taşınır. */
function ctaHref(
  dateFrom: string | undefined,
  dateTo: string | undefined,
  contentType?: string,
): string {
  const params = new URLSearchParams();
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  if (contentType) params.set("content_types", contentType);
  const qs = params.toString();
  return qs ? `/reviews?${qs}` : "/reviews";
}
