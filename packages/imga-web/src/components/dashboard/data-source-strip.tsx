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
//
// F (2026-09-02, home-liveliness) — düz metin satırı, ikonlu kaynak
// çipleri + orantılı mini çubuklara dönüştü (ürün sahibi: "çok metin
// ağırlıklı, canlılık istiyorum"). Toplam + dönem sol küme olarak
// kalır, kaynaklar sağda ayrı bir küme — flex-wrap ile masaüstünde tek
// satır, dar ekranda doğal biçimde sarar (satır zorlaması yok).

import { HelpCircle } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { useMounted } from "@/hooks/use-count-up";
import { useReviewSummary } from "@/hooks/use-review-summary";
import { useTranslation } from "@/lib/i18n/use-translation";
import { SOURCE_ICONS, sourceIconIndex } from "@/lib/source-icons";

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

  const topSources = sources.slice(0, 4);

  return (
    <div
      aria-label={aria}
      className="rise-in text-muted-foreground flex flex-wrap items-center gap-x-5 gap-y-2 text-sm"
    >
      <span className="flex shrink-0 items-center gap-x-2">
        <span className="text-foreground font-medium">
          {t("dashboard.dataStrip.total", { n: total.toLocaleString(locale) })}
        </span>
        <span aria-hidden className="text-muted-foreground/50">
          ·
        </span>
        <span>{period}</span>
      </span>
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1.5">
        {topSources.map((s) => (
          <SourceChip key={s.value} value={s.value} count={s.count} total={total} locale={locale} />
        ))}
        {rest > 0 && (
          <SourceChip
            value=""
            label={t("dashboard.dataStrip.unspecified", { n: rest.toLocaleString(locale) })}
            hideCount
            count={rest}
            total={total}
            locale={locale}
          />
        )}
      </div>
    </div>
  );
}

/** Kaynak çipi — ikon + etiket + sayı + toplam içindeki payı gösteren
 *  minik orantılı çubuk (SatisfactionSegment'teki mount-tetikli CSS
 *  transition deseni, ölçek küçültülmüş). Renk kasıtlı olarak nötr
 *  (görev talimatı: "muted colours") — kategori ikonlarının aksine
 *  burada renk kodlaması değil, yalnızca oran taşınıyor. */
function SourceChip({
  value,
  label,
  hideCount = false,
  count,
  total,
  locale,
}: {
  value: string;
  /** "Belirtilmemiş N" gibi zaten biçimlenmiş özel bir etiket varsa
   *  sourceLabel() atlanır. */
  label?: string;
  /** label kendi sayısını zaten taşıyorsa ("Belirtilmemiş 42") ayrı
   *  "(42)" eki tekrar basılmasın diye. */
  hideCount?: boolean;
  count: number;
  total: number;
  locale: string;
}) {
  // Satır içi tablo indekslemesi (fonksiyon çağrısının SONUCU değil) —
  // bkz. lib/source-icons.ts / lib/category-icons.ts dosya üstü notu
  // (react-hooks/static-components).
  const iconIdx = sourceIconIndex(value);
  const Icon = iconIdx === -1 ? HelpCircle : SOURCE_ICONS[iconIdx]!;
  const mounted = useMounted();
  const share = total > 0 ? Math.min(100, (count / total) * 100) : 0;
  return (
    <span className="inline-flex items-center gap-1.5">
      <Icon className="text-muted-foreground/70 size-3.5 shrink-0" aria-hidden />
      <span className="text-foreground/80">{label ?? sourceLabel(value)}</span>
      {!hideCount && <span className="tabular-nums">({count.toLocaleString(locale)})</span>}
      <span className="bg-muted relative h-1 w-6 shrink-0 overflow-hidden rounded-full" aria-hidden>
        <span
          className="bg-muted-foreground/50 absolute inset-y-0 left-0 rounded-full transition-[width] duration-700 [transition-timing-function:var(--motion-ease)]"
          style={{ width: mounted ? `${share}%` : "0%" }}
        />
      </span>
    </span>
  );
}
