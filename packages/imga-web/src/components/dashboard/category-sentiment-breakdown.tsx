"use client";

// Sprint 13 — kategori bazlı duygu dağılımı (ürün sahibi görsel
// referansı: yatay yığılmış %100 bar chart — her kategoride
// olumsuz / nötr / olumlu payı). "Ana sayfada mutlaka görünsün."
//
// Renk kutupsal (diverging): kırmızı olumsuz ↔ gri nötr ↔ yeşil
// olumlu; segment sırası SABİT (olumsuz solda) — kimliği renk tek
// başına taşımaz, pozisyon + lejant + yüzde etiketi destekler.
// Segment tıklaması /reviews'a kategori+duygu filtresiyle gider.

import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { SentimentByCategoryResponse } from "@/lib/types";

interface Props {
  data: SentimentByCategoryResponse | undefined;
  isLoading: boolean;
}

interface Segment {
  sentiment: "NEGATIF" | "NÖTR" | "POZITIF";
  legendKey: string;
  barClass: string;
  labelClass: string;
  dotClass: string;
}

// Etiket taşıyan mark'lar 600 tonunda (beyaz etiket kontrastı);
// nötr orta nokta açık gri + koyu mürekkep etiket.
const SEGMENTS: readonly Segment[] = [
  {
    sentiment: "NEGATIF",
    legendKey: "dashboard.executiveHero.legend.negative",
    barClass: "bg-red-600 dark:bg-red-500",
    labelClass: "text-white",
    dotClass: "bg-red-600 dark:bg-red-500",
  },
  {
    sentiment: "NÖTR",
    legendKey: "dashboard.executiveHero.legend.neutral",
    barClass: "bg-zinc-200 dark:bg-zinc-600",
    labelClass: "text-zinc-700 dark:text-zinc-100",
    dotClass: "bg-zinc-300 dark:bg-zinc-600",
  },
  {
    sentiment: "POZITIF",
    legendKey: "dashboard.executiveHero.legend.positive",
    barClass: "bg-emerald-600 dark:bg-emerald-500",
    labelClass: "text-white",
    dotClass: "bg-emerald-600 dark:bg-emerald-500",
  },
];

// Yüzde etiketi bu genişliğin altındaki segmente sığmaz — gizlenir;
// değer yine hover tooltip'inde (title) durur.
const LABEL_MIN_PCT = 12;

interface Row {
  code: string;
  label: string;
  total: number;
  counts: Record<Segment["sentiment"], number>;
}

/** Backend matrisi (satır=kategori, kolon=sentiments dizi sırası)
 *  satır nesnelerine açılır. Sıralama "en sorunlu en üstte":
 *  negatif payı azalan (referans yönetim görünümüyle aynı okuma) —
 *  seçim zaten hacim bazlı top-N olduğu için cılız kategoriler
 *  sahte sinyal üretemez. 'belirsiz' listenin sonuna itilir
 *  (insights heatmap'iyle aynı ilke — sınıflandırılamayan yorum
 *  ana sinyali bastırmasın). */
function toRows(data: SentimentByCategoryResponse): Row[] {
  const sentimentIndex = new Map(data.sentiments.map((s, i) => [s, i]));
  const rows: Row[] = data.categories.map((code, i) => {
    const matrixRow = data.matrix[i] ?? [];
    const countFor = (s: Segment["sentiment"]): number => {
      const idx = sentimentIndex.get(s);
      return idx === undefined ? 0 : (matrixRow[idx] ?? 0);
    };
    return {
      code,
      label: data.category_labels_tr[i] ?? code,
      total: data.totals_by_category[i] ?? 0,
      counts: {
        NEGATIF: countFor("NEGATIF"),
        "NÖTR": countFor("NÖTR"),
        POZITIF: countFor("POZITIF"),
      },
    };
  });
  const negShare = (r: Row) => (r.total > 0 ? r.counts.NEGATIF / r.total : 0);
  return [
    ...rows
      .filter((r) => r.code !== "belirsiz")
      .sort((a, b) => negShare(b) - negShare(a)),
    ...rows.filter((r) => r.code === "belirsiz"),
  ];
}

export function CategorySentimentBreakdown({ data, isLoading }: Props) {
  const { t, locale } = useTranslation();
  if (isLoading || !data) {
    return <Skeleton className="h-80 w-full rounded-3xl" />;
  }

  const rows = toRows(data).filter((r) => r.total > 0);
  const numberLocale = locale === "en" ? "en-US" : "tr-TR";

  return (
    <section
      className="shadow-soft bg-card ring-foreground/5 rounded-3xl p-6 ring-1 md:p-7"
      aria-label={t("dashboard.categoryBreakdown.title")}
    >
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <div>
          <h2 className="text-base font-semibold">
            {t("dashboard.categoryBreakdown.title")}
          </h2>
          <p className="text-muted-foreground mt-0.5 text-xs">
            {t("dashboard.categoryBreakdown.subtitle")}
          </p>
        </div>
        <div className="text-muted-foreground flex items-center gap-4 text-xs">
          {SEGMENTS.map((seg) => (
            <span key={seg.sentiment} className="inline-flex items-center gap-1.5">
              <span
                className={`size-2.5 rounded-full ${seg.dotClass}`}
                aria-hidden
              />
              {t(seg.legendKey)}
            </span>
          ))}
        </div>
      </header>

      {rows.length === 0 ? (
        <p className="text-muted-foreground mt-5 text-sm leading-relaxed">
          {t("dashboard.categoryBreakdown.empty")}
        </p>
      ) : (
        <ul className="mt-5 space-y-2.5">
          {rows.map((row) => (
            <li key={row.code} className="flex items-center gap-3">
              <Link
                href={`/reviews?primary_categories=${encodeURIComponent(row.code)}`}
                title={`${row.label} — ${row.total.toLocaleString(numberLocale)}`}
                className="text-foreground/80 hover:text-foreground w-40 shrink-0 truncate text-right text-xs font-medium transition-colors md:w-48 md:text-sm"
              >
                {row.label}
              </Link>
              <div className="flex h-6 min-w-0 flex-1 gap-[2px] overflow-hidden rounded-md">
                {SEGMENTS.map((seg) => {
                  const count = row.counts[seg.sentiment];
                  if (count === 0) return null;
                  const pct = (count / row.total) * 100;
                  const pctText = (Math.round(pct * 10) / 10).toLocaleString(
                    numberLocale,
                  );
                  return (
                    <Link
                      key={seg.sentiment}
                      href={`/reviews?primary_categories=${encodeURIComponent(row.code)}&sentiment_labels=${encodeURIComponent(seg.sentiment)}`}
                      title={`${row.label} — ${t(seg.legendKey)}: ${count.toLocaleString(numberLocale)} (%${pctText})`}
                      style={{ width: `${pct}%` }}
                      className={`flex items-center overflow-hidden transition-opacity hover:opacity-85 ${seg.barClass} ${
                        seg.sentiment === "NEGATIF"
                          ? "justify-start pl-1.5"
                          : "justify-end pr-1.5"
                      }`}
                    >
                      {pct >= LABEL_MIN_PCT && (
                        <span
                          className={`text-[10px] font-semibold tabular-nums ${seg.labelClass}`}
                        >
                          %{pctText}
                        </span>
                      )}
                    </Link>
                  );
                })}
              </div>
              <span
                className="text-muted-foreground w-12 shrink-0 text-right text-xs tabular-nums"
                title={t("dashboard.categoryBreakdown.rowTotal", {
                  n: row.total.toLocaleString(numberLocale),
                })}
              >
                {row.total.toLocaleString(numberLocale)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
