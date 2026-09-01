"use client";

// Sprint 13.2 — sadeleştirme (ürün sahibi: "çok karmaşık, çok daha
// kolay okunabilir olsun"). Eski hali 100%-stacked bar + chevron
// akordeon + alt-kategori drill-down + kök-neden diyaloğu taşıyordu;
// hepsi kaldırıldı. Yeni hali üç saniyede taranabilen düz bir sıralı
// liste: en çok olumsuz payı olan kategori en üstte, her satır tek
// bakışta payı gösteren ince bir yığılmış çubukla birlikte. Detay
// isteyen kullanıcı satıra tıklayıp doğrudan /reviews'a gider (aktif
// tarih aralığı taşınır) — arayüz içi başka bir kademe yok.

import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { AnalyticsFilters, SentimentByCategoryResponse } from "@/lib/types";

interface Props {
  data: SentimentByCategoryResponse | undefined;
  isLoading: boolean;
  /** Satır ve "Tümünü gör" bağlantılarına aktif tarih aralığını taşımak
   *  için; verilmezse bağlantılar yalnız kategori+duygu filtresiyle gider. */
  filters?: AnalyticsFilters;
}

const MAX_ROWS = 8;

interface Row {
  code: string;
  label: string;
  total: number;
  negCount: number;
  neutralCount: number;
  posCount: number;
  negShare: number;
}

/** Backend matrisi (satır=kategori, kolon=sentiments dizi sırası)
 *  satır nesnelerine açılır; negatif payı büyükten küçüğe sıralanır —
 *  "en sorunlu en üstte" tek okuma kuralı. Akordeon kalkınca eski
 *  "belirsiz'i listenin sonuna it" özel durumu de anlamsızlaştı: artık
 *  her kategori aynı kurala göre (negatif payı) sıralanıyor. */
function toRows(data: SentimentByCategoryResponse): Row[] {
  const sentimentIndex = new Map(data.sentiments.map((s, i) => [s, i]));
  const countFor = (matrixRow: number[], sentiment: string): number => {
    const idx = sentimentIndex.get(sentiment);
    return idx === undefined ? 0 : (matrixRow[idx] ?? 0);
  };
  return data.categories
    .map((code, i) => {
      const matrixRow = data.matrix[i] ?? [];
      const total = data.totals_by_category[i] ?? 0;
      const negCount = countFor(matrixRow, "NEGATIF");
      return {
        code,
        label: data.category_labels_tr[i] ?? code,
        total,
        negCount,
        neutralCount: countFor(matrixRow, "NÖTR"),
        posCount: countFor(matrixRow, "POZITIF"),
        negShare: total > 0 ? negCount / total : 0,
      };
    })
    .filter((r) => r.total > 0)
    .sort((a, b) => b.negShare - a.negShare);
}

function reviewsHref(params: Record<string, string | undefined>): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) qs.set(key, value);
  }
  const query = qs.toString();
  return query ? `/reviews?${query}` : "/reviews";
}

export function CategorySentimentBreakdown({ data, isLoading, filters }: Props) {
  const { t, locale } = useTranslation();
  const numberLocale = locale === "en" ? "en-US" : "tr-TR";

  if (isLoading || !data) {
    return <Skeleton className="h-80 w-full rounded-3xl" />;
  }

  const rows = toRows(data).slice(0, MAX_ROWS);

  return (
    <section
      className="shadow-soft bg-card ring-foreground/5 rounded-3xl p-6 ring-1 md:p-7"
      aria-label={t("dashboard.categorySimple.title")}
    >
      <header className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <div>
          <h2 className="text-base font-semibold">{t("dashboard.categorySimple.title")}</h2>
          <p className="text-muted-foreground mt-0.5 text-xs">
            {t("dashboard.categorySimple.subtitle")}
          </p>
        </div>
        <Link
          href={reviewsHref({ date_from: filters?.date_from, date_to: filters?.date_to })}
          className="text-primary shrink-0 text-xs font-medium underline-offset-2 hover:underline"
        >
          {t("dashboard.categorySimple.showAll")} →
        </Link>
      </header>

      {rows.length === 0 ? (
        <p className="text-muted-foreground mt-5 text-sm leading-relaxed">
          {t("dashboard.categorySimple.empty")}
        </p>
      ) : (
        <ul className="divide-border/60 mt-4 divide-y">
          {rows.map((row) => {
            const pct = Math.round(row.negShare * 100);
            return (
              <li key={row.code}>
                <Link
                  href={reviewsHref({
                    primary_categories: row.code,
                    sentiment_labels: "NEGATIF",
                    date_from: filters?.date_from,
                    date_to: filters?.date_to,
                  })}
                  className="hover:bg-muted/50 -mx-2 flex flex-col gap-2 rounded-xl px-2 py-3.5 transition-colors"
                >
                  <div className="flex items-center justify-between gap-4">
                    <div className="min-w-0">
                      <p className="text-foreground truncate text-sm font-medium">
                        {row.label}
                      </p>
                      <p className="text-muted-foreground mt-0.5 text-xs">
                        {t("dashboard.categorySimple.reviews", {
                          n: row.total.toLocaleString(numberLocale),
                        })}
                      </p>
                    </div>
                    <span className="text-sentiment-negative shrink-0 text-sm font-semibold tabular-nums">
                      {t("dashboard.categorySimple.negShare", { pct })}
                    </span>
                  </div>
                  <div className="bg-muted flex h-2 w-full overflow-hidden rounded-full">
                    {row.negCount > 0 && (
                      <div
                        className="bg-sentiment-negative h-full"
                        style={{ width: `${(row.negCount / row.total) * 100}%` }}
                      />
                    )}
                    {row.neutralCount > 0 && (
                      <div
                        className="bg-sentiment-neutral h-full"
                        style={{ width: `${(row.neutralCount / row.total) * 100}%` }}
                      />
                    )}
                    {row.posCount > 0 && (
                      <div
                        className="bg-sentiment-positive h-full"
                        style={{ width: `${(row.posCount / row.total) * 100}%` }}
                      />
                    )}
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
