"use client";

// Sprint 13.2 — veri kalitesi koçu (A2), ClassificationQualityChip'in
// yerini alır.
//
// Eski sürüm 'belirsiz' KATEGORİ oranına bakıyordu (sınıflandırmanın
// kategoriye düşme başarısı). Bu kart farklı bir sinyale bakar: kalite
// bayraklı (boş/anlamsız/kopya) yorumların GİRDİ kalitesi — kök neden
// analizlerinin isabetini doğrudan etkileyen taraf. useReviewSummary
// zaten /reviews panelinde aynı `quality` nesnesini döndürüyor; burada
// sayfanın dönem filtresiyle (yalnız date_from/date_to — W3 hook'unun
// beklediği tam filtre yüzeyinin geri kalanı bilerek boş bırakılır)
// tekrar çağrılır.
//
// Sprint 13.3 (2026-09-01) - 320px sag raya tasindi; break-words dar
// sutunda tasmayi onler (kurallar/esikler dokunulmadan kalir).

import Link from "next/link";
import { ArrowRight } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { useReviewSummary } from "@/hooks/use-review-summary";
import { useTranslation } from "@/lib/i18n/use-translation";

interface Props {
  dateFrom?: string;
  dateTo?: string;
}

export function DataQualityCoach({ dateFrom, dateTo }: Props) {
  const { t, locale } = useTranslation();
  const numberLocale = locale === "en" ? "en-US" : "tr-TR";
  const summary = useReviewSummary({ date_from: dateFrom, date_to: dateTo });

  if (summary.isLoading) {
    return <Skeleton className="h-24 w-full rounded-3xl" />;
  }
  // Hata da boş de sessizce gizlenir — bu kart bir uyarı değil, ikinci
  // dereceden bir koç; sayfanın geri kalanını bloklamaya değmez.
  if (summary.isError || !summary.data || summary.data.total === 0) {
    return null;
  }

  const { quality, question_count, total } = summary.data;
  // "boş/anlamsız/kopya" — informational ayrı tutulur (o soru sayısını
  // besler, kalite bayrağı değil, ayrı bir müşteri-sinyali).
  const flaggedCount = quality.duplicate + quality.empty + quality.meaningless;
  const flaggedPct = Math.round((flaggedCount / total) * 100);

  // Şikâyet tehdidi (hakem heyeti/dava/CİMER) veri kalitesinden bağımsız
  // bir risk sinyali: kalite iyi olsa da gösterilir, önce bunlara bakılsın.
  const escalationCount = summary.data.content_types?.escalation ?? 0;
  const escalationLine =
    escalationCount > 0 ? (
      <p className="text-sentiment-negative mt-2 text-sm font-medium leading-relaxed">
        {t("dashboard.dataQuality.escalation", {
          n: escalationCount.toLocaleString(numberLocale),
        })}{" "}
        <Link
          href={ctaHref(dateFrom, dateTo, "escalation")}
          className="underline underline-offset-2 hover:opacity-80"
        >
          {t("dashboard.dataQuality.escalationCta")}
        </Link>
      </p>
    ) : null;

  // Sessizlik kuralı: kalite zaten iyiyse (< %5 bayraklı) uyarı tonunda
  // bir kart yerine tek sakin cümle — tablo yok, kırmızı yok.
  if (flaggedPct < 5) {
    return (
      <section
        className="rise-in shadow-soft bg-card ring-foreground/5 break-words rounded-3xl p-5 ring-1"
        aria-label={t("dashboard.dataQuality.aria")}
      >
        <p className="text-muted-foreground text-sm font-medium">
          {t("dashboard.dataQuality.good")}
        </p>
        {escalationLine}
      </section>
    );
  }

  return (
    <section
      className="rise-in shadow-soft bg-card ring-foreground/5 break-words rounded-3xl p-5 ring-1"
      aria-label={t("dashboard.dataQuality.aria")}
    >
      <p className="text-sm font-semibold">
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
      {question_count > 0 && (
        <p className="text-muted-foreground mt-1 text-sm leading-relaxed">
          {t("dashboard.dataQuality.questionCount", {
            n: question_count.toLocaleString(numberLocale),
          })}
        </p>
      )}
      {escalationLine}
      <Link
        href={ctaHref(dateFrom, dateTo)}
        className="text-primary hover:text-primary/80 mt-3 inline-flex items-center gap-1.5 text-sm font-semibold transition-colors"
      >
        {t("dashboard.dataQuality.cta")}
        <ArrowRight className="size-4" aria-hidden />
      </Link>
    </section>
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
