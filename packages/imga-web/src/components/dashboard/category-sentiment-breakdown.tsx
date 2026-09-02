"use client";

// Sprint 13.2 — sadeleştirme (ürün sahibi: "çok karmaşık, çok daha
// kolay okunabilir olsun"). Eski hali 100%-stacked bar + chevron
// akordeon + alt-kategori drill-down + kök-neden diyaloğu taşıyordu;
// hepsi kaldırıldı. Yeni hali üç saniyede taranabilen düz bir sıralı
// liste: en çok olumsuz payı olan kategori en üstte, her satır tek
// bakışta payı gösteren ince bir yığılmış çubukla birlikte. Detay
// isteyen kullanıcı satıra tıklayıp doğrudan /reviews'a gider (aktif
// tarih aralığı taşınır).
//
// Sprint 13.2.1 — ürün sahibi alt-kategori kırılımının eksikliğini
// fark etti: geri geldi, ama eski karmaşıklık (RootCauseDialog,
// Sparkles/kök-neden butonu, iç içe akordeon) YOK. Her satırın sağında
// tek bir chevron var; açılınca altında ince, hafif bir alt-kategori
// listesi belirir. Satır Link'i ile chevron button'ı KARDEŞ (sibling)
// — bir <a> içine <button> gömülemez, o yüzden ikisi ortak bir flex
// kapsayıcının çocukları, kapsayıcı hover arka planını taşıyor.

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import { useCategoryDrilldown } from "@/hooks/use-analytics";
import {
  CATEGORY_ICON_FALLBACK,
  CATEGORY_ICON_MAP,
  categoryIconFallbackIndex,
  categoryTone,
} from "@/lib/category-icons";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { AnalyticsFilters, SentimentByCategoryResponse } from "@/lib/types";

interface Props {
  data: SentimentByCategoryResponse | undefined;
  isLoading: boolean;
  /** Satır ve "Tümünü gör" bağlantılarına aktif tarih aralığını taşımak,
   *  VE alt-kategori kırılımını (useCategoryDrilldown) beslemek için;
   *  verilmezse chevron hiç gösterilmez (widget salt sıralı liste kalır). */
  filters?: AnalyticsFilters;
}

const MAX_ROWS = 8;
const MAX_SUB_ROWS = 6;

// Backend'in NULL company_perspective_code için kullandığı sentinel
// (analytics_service.py — UNMATCHED_PERSPECTIVE_SENTINEL). /reviews
// filtresi de aynı değeri tanır, bu yüzden alt-satır yine derin
// bağlantı olabiliyor.
const UNMATCHED_CODE = "__unmatched__";

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

/** Satır başındaki küçük ikon rozeti — root-cause-cards.tsx'teki
 *  CategoryIconBadge ile aynı kayıt defterini (lib/category-icons.ts)
 *  kullanır, yalnız daha küçük (satır listesi için sade tutulur). */
function CategoryIconDot({ code }: { code: string }) {
  // Satır içi tablo indekslemesi — bkz. root-cause-cards.tsx'teki aynı
  // WHY yorumu (react-hooks/static-components).
  const Icon = CATEGORY_ICON_MAP[code] ?? CATEGORY_ICON_FALLBACK[categoryIconFallbackIndex(code)]!;
  const tone = categoryTone(code);
  return (
    <span
      className={`inline-flex size-7 shrink-0 items-center justify-center rounded-full ${tone.bg} ${tone.fg}`}
      aria-hidden
    >
      <Icon className="size-3.5" />
    </span>
  );
}

export function CategorySentimentBreakdown({ data, isLoading, filters }: Props) {
  const { t, locale } = useTranslation();
  const numberLocale = locale === "en" ? "en-US" : "tr-TR";
  // Açık alt-kategori kodu — bu geçici (transient) arayüz durumu, URL'e
  // taşınan bir filtre/sıralama DEĞİL: url-state-patterns.md
  // "Component-internal expand/collapse — accordion vb." maddesini
  // açıkça URL dışı bırakıyor. Sayfa yenilendiğinde kapalı başlaması
  // beklenen (ve zararsız) davranış.
  const [expandedCode, setExpandedCode] = useState<string | null>(null);

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
            const isOpen = expandedCode === row.code;
            return (
              <li key={row.code}>
                <div className="hover:bg-muted/50 -mx-2 flex items-center gap-1 rounded-xl px-2 transition-colors">
                  <Link
                    href={reviewsHref({
                      primary_categories: row.code,
                      sentiment_labels: "NEGATIF",
                      date_from: filters?.date_from,
                      date_to: filters?.date_to,
                    })}
                    className="flex min-w-0 flex-1 flex-col gap-2 py-3.5"
                  >
                    <div className="flex items-center justify-between gap-4">
                      <div className="flex min-w-0 items-center gap-2.5">
                        <CategoryIconDot code={row.code} />
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
                  {filters !== undefined && (
                    <button
                      type="button"
                      onClick={() =>
                        setExpandedCode((prev) => (prev === row.code ? null : row.code))
                      }
                      aria-expanded={isOpen}
                      aria-label={
                        isOpen
                          ? t("dashboard.categorySimple.collapse")
                          : t("dashboard.categorySimple.expand")
                      }
                      className="text-muted-foreground hover:text-foreground shrink-0 rounded-lg p-2 transition-colors"
                    >
                      {isOpen ? (
                        <ChevronDown className="size-4" aria-hidden />
                      ) : (
                        <ChevronRight className="size-4" aria-hidden />
                      )}
                    </button>
                  )}
                </div>
                {filters !== undefined && isOpen && (
                  <SubCategoryList
                    filters={filters}
                    primaryCategory={row.code}
                    numberLocale={numberLocale}
                  />
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// --- Alt kategori kırılımı ------------------------------------------
//
// Yalnız açık satır için mount edilir (bkz. yukarısı) — bu yüzden
// kapalıyken hiçbir istek atılmaz; useCategoryDrilldown'ın kendi
// enabled/skip deseni (primaryCategory !== null) burada primaryCategory
// hiçbir zaman null verilmediği için doğal biçimde her zaman "enabled".
function SubCategoryList({
  filters,
  primaryCategory,
  numberLocale,
}: {
  filters: AnalyticsFilters;
  primaryCategory: string;
  numberLocale: string;
}) {
  const { t } = useTranslation();
  const drilldown = useCategoryDrilldown(filters, primaryCategory);

  if (drilldown.isLoading) {
    return (
      <div className="space-y-1.5 px-2 pb-3">
        <Skeleton className="h-4 w-full rounded" />
        <Skeleton className="h-4 w-5/6 rounded" />
      </div>
    );
  }

  const subRows = [...(drilldown.data?.data ?? [])]
    .sort((a, b) => b.negative_share - a.negative_share)
    .slice(0, MAX_SUB_ROWS);

  if (subRows.length === 0) {
    return (
      <p className="text-muted-foreground px-2 pb-3 text-xs">
        {t("dashboard.categorySimple.subEmpty")}
      </p>
    );
  }

  return (
    <ul className="bg-muted/30 -mx-2 mb-3 space-y-0.5 rounded-xl px-2 py-2">
      {subRows.map((sub) => (
        <li key={sub.code}>
          <Link
            href={reviewsHref({
              primary_categories: primaryCategory,
              perspective_codes: sub.code,
              date_from: filters.date_from,
              date_to: filters.date_to,
            })}
            className="hover:bg-muted/60 flex items-center justify-between gap-3 rounded-lg px-2 py-1.5 text-xs transition-colors"
          >
            <span className="text-foreground/80 min-w-0 flex-1 truncate">
              {sub.code === UNMATCHED_CODE ? t("dashboard.categorySimple.unmatched") : sub.label_tr}
            </span>
            <span className="text-muted-foreground shrink-0 tabular-nums">
              {t("dashboard.categorySimple.reviews", {
                n: sub.total.toLocaleString(numberLocale),
              })}
            </span>
            <span className="text-sentiment-negative shrink-0 font-medium tabular-nums">
              {t("dashboard.categorySimple.negShare", { pct: Math.round(sub.negative_share) })}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
