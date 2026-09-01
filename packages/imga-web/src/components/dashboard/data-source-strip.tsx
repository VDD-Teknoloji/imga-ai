"use client";

// Sprint 13.3 (2026-09-01) — veri kaynak seridi. Ürün sahibi talimatı:
// ana sayfa yeniden düzeninde UploadFirst'ün altında, iki kolonlu
// rapor gridinin üstünde, tam genişlikte tek satırlık sakin bir
// özet — büyük bir kart değil. "Kaç yorum, hangi kanallardan, hangi
// dönem" sorusunun tek bakışta cevabı.
//
// Veri kaynağı useReviewSummary (W3, reviews panelinin aynı hook'u) —
// yalnız date_from/date_to ile çağrılır; batch/kaynak/kategori gibi
// diğer filtreler bilerek boş bırakılır (bu şerit sayfanın dönemini
// özetler, alt filtrelerini değil).

import { Skeleton } from "@/components/ui/skeleton";
import { useReviewSummary } from "@/hooks/use-review-summary";
import { useTranslation } from "@/lib/i18n/use-translation";

interface Props {
  dateFrom?: string;
  dateTo?: string;
}

/** summary.sources zaten backend'de foldlanmış (mode() within group) —
 *  burada yalnız "twitter" özel etiketini uygular, başka bir eşleme
 *  icat etmez: ham değer olduğu gibi Title Case'e çevrilir. */
function sourceLabel(value: string): string {
  if (value.trim().toLowerCase() === "twitter") return "X/Twitter";
  return value
    .split(" ")
    .map((word) => (word ? word[0]!.toUpperCase() + word.slice(1).toLowerCase() : word))
    .join(" ");
}

export function DataSourceStrip({ dateFrom, dateTo }: Props) {
  const { t, locale } = useTranslation();
  const dateLocale = locale === "en" ? "en-US" : "tr-TR";
  const summary = useReviewSummary({ date_from: dateFrom, date_to: dateTo });
  const aria = t("dashboard.dataStrip.aria");

  if (summary.isLoading) {
    return (
      <div aria-label={aria} className="rise-in">
        <Skeleton className="h-4 w-72 max-w-full" />
      </div>
    );
  }

  const total = summary.data?.total ?? 0;
  if (summary.isError || !summary.data || total === 0) {
    return (
      <p aria-label={aria} className="rise-in text-muted-foreground text-sm">
        {t("dashboard.dataStrip.empty")}
      </p>
    );
  }

  const { sources, daily } = summary.data;
  const dateFormatter = new Intl.DateTimeFormat(dateLocale, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });

  // "Belirtilmemiş" — sources listesindeki TÜM kanalların toplamı
  // (yalnız ekranda gösterilen ilk 4'ü değil) çıkarılınca kalan fark;
  // backend sources'ı zaten boş/NULL source değerlerini hariç tutarak
  // döndürüyor (dimension_value_present), yani bu fark kaynağı hiç
  // işaretlenmemiş kayıtları temsil eder.
  const sourcesSum = sources.reduce((sum, s) => sum + s.count, 0);
  const rest = total - sourcesSum;

  const period =
    dateFrom && dateTo
      ? t("dashboard.dataStrip.range", {
          from: dateFormatter.format(new Date(dateFrom)),
          to: dateFormatter.format(new Date(dateTo)),
        })
      : daily.length > 0
        ? `${t("dashboard.dataStrip.allTime")} — ${t("dashboard.dataStrip.sinceDate", {
            date: dateFormatter.format(new Date(daily[0]!.date)),
          })}`
        : t("dashboard.dataStrip.allTime");

  const chips: string[] = sources
    .slice(0, 4)
    .map((s) => `${sourceLabel(s.value)} (${s.count.toLocaleString(locale)})`);
  if (rest > 0) {
    chips.push(t("dashboard.dataStrip.unspecified", { n: rest.toLocaleString(locale) }));
  }
  chips.push(period);

  return (
    <div
      aria-label={aria}
      className="rise-in text-muted-foreground flex flex-wrap items-center gap-x-2 gap-y-1 text-sm"
    >
      <span className="text-foreground font-medium">
        {t("dashboard.dataStrip.total", { n: total.toLocaleString(locale) })}
      </span>
      {chips.map((chip, i) => (
        <span key={i} className="flex items-center gap-x-2">
          <span aria-hidden className="text-muted-foreground/50">
            ·
          </span>
          {chip}
        </span>
      ))}
    </div>
  );
}
