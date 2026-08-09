"use client";

// Sprint 13 — kategori bazlı duygu dağılımı (ürün sahibi görsel
// referansı: yatay yığılmış %100 bar chart — her kategoride
// olumsuz / nötr / olumlu payı). "Ana sayfada mutlaka görünsün."
//
// Renk kutupsal (diverging): kırmızı olumsuz ↔ gri nötr ↔ yeşil
// olumlu; segment sırası SABİT (olumsuz solda) — kimliği renk tek
// başına taşımaz, pozisyon + lejant + yüzde etiketi destekler.
// Segment tıklaması /reviews'a kategori+duygu filtresiyle gider.

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, Sparkles } from "lucide-react";

import { RootCauseDialog } from "@/components/dashboard/root-cause-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useCategoryDrilldown } from "@/hooks/use-analytics";
import type { RootCauseTarget } from "@/hooks/use-root-cause";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { AnalyticsFilters, SentimentByCategoryResponse } from "@/lib/types";

interface Props {
  data: SentimentByCategoryResponse | undefined;
  isLoading: boolean;
  /** Sprint 13.1 — alt kategori kırılımı aynı pencereyi kullanır.
   *  Verilmezse satırlar açılmaz (widget salt-okunur kalır). */
  filters?: AnalyticsFilters;
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

// Alt kategorisi atanmamış yorumların kovası. Backend aynı sentinel'i
// hem drill-down yanıtında hem /reviews perspective_codes filtresinde
// tanır, o yüzden satır doğrudan derin bağlantı olabiliyor.
const UNMATCHED_CODE = "__unmatched__";

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

export function CategorySentimentBreakdown({ data, isLoading, filters }: Props) {
  const { t, locale } = useTranslation();
  // Akordeon durumu URL'de DEĞİL: url-state-patterns.md geçici
  // akordeon durumunu açıkça muaf tutuyor (filtre/sıralama değil).
  const [expanded, setExpanded] = useState<string | null>(null);
  const [rootCause, setRootCause] = useState<{
    target: RootCauseTarget;
    categoryLabel: string;
    perspectiveLabel: string;
  } | null>(null);

  const numberLocale = locale === "en" ? "en-US" : "tr-TR";
  const drilldownEnabled = filters !== undefined;

  if (isLoading || !data) {
    return <Skeleton className="h-80 w-full rounded-3xl" />;
  }

  const rows = toRows(data).filter((r) => r.total > 0);

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
            <li key={row.code}>
              <div className="flex items-center gap-3">
                {drilldownEnabled && (
                  <button
                    type="button"
                    onClick={() => setExpanded((prev) => (prev === row.code ? null : row.code))}
                    aria-expanded={expanded === row.code}
                    aria-label={t("dashboard.categoryBreakdown.expand", {
                      category: row.label,
                    })}
                    className="text-muted-foreground hover:text-foreground shrink-0 transition-colors"
                  >
                    {expanded === row.code ? (
                      <ChevronDown className="size-4" aria-hidden />
                    ) : (
                      <ChevronRight className="size-4" aria-hidden />
                    )}
                  </button>
                )}
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
                    const pctText = (Math.round(pct * 10) / 10).toLocaleString(numberLocale);
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
              </div>
              {drilldownEnabled && expanded === row.code && filters && (
                <DrilldownPanel
                  filters={filters}
                  primaryCategory={row.code}
                  categoryLabel={row.label}
                  numberLocale={numberLocale}
                  onRootCause={(perspectiveCode, perspectiveLabel) =>
                    setRootCause({
                      target: {
                        primary_category: row.code,
                        perspective_code: perspectiveCode,
                        date_from: filters.date_from,
                        date_to: filters.date_to,
                      },
                      categoryLabel: row.label,
                      perspectiveLabel,
                    })
                  }
                />
              )}
            </li>
          ))}
        </ul>
      )}

      <RootCauseDialog
        open={rootCause !== null}
        onClose={() => setRootCause(null)}
        target={rootCause?.target ?? null}
        primaryCategoryLabel={rootCause?.categoryLabel ?? ""}
        perspectiveLabel={rootCause?.perspectiveLabel ?? ""}
      />
    </section>
  );
}

// --- Alt kategori kırılımı (drill-down 2. seviye) --------------------
//
// Sayılar backend'de YALNIZ review kolonlarından hesaplanır, bu yüzden
// her satırın derin bağlantısı /reviews'ta birebir aynı sayıyı verir.

function DrilldownPanel({
  filters,
  primaryCategory,
  categoryLabel,
  numberLocale,
  onRootCause,
}: {
  filters: AnalyticsFilters;
  primaryCategory: string;
  categoryLabel: string;
  numberLocale: string;
  onRootCause: (perspectiveCode: string, perspectiveLabel: string) => void;
}) {
  const { t } = useTranslation();
  const drilldown = useCategoryDrilldown(filters, primaryCategory);

  if (drilldown.isLoading) {
    return <Skeleton className="mt-2 ml-7 h-24 rounded-2xl" />;
  }
  const items = drilldown.data?.data ?? [];
  if (items.length === 0) {
    return (
      <p className="text-muted-foreground mt-2 ml-7 text-xs">
        {t("dashboard.categoryBreakdown.drilldownEmpty")}
      </p>
    );
  }

  return (
    <div className="bg-muted/40 mt-2 ml-7 rounded-2xl p-3">
      <p className="text-muted-foreground mb-2 text-[11px] font-medium tracking-wide uppercase">
        {t("dashboard.categoryBreakdown.drilldownTitle", {
          category: categoryLabel,
        })}
      </p>
      <ul className="space-y-1">
        {items.map((sub) => (
          <li key={sub.code} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            <Link
              href={`/reviews?primary_categories=${encodeURIComponent(primaryCategory)}&perspective_codes=${encodeURIComponent(sub.code)}`}
              className="text-foreground/80 hover:text-foreground min-w-0 flex-1 truncate font-medium transition-colors"
            >
              {sub.code === UNMATCHED_CODE
                ? t("dashboard.categoryBreakdown.unmatched")
                : sub.label_tr}
            </Link>
            <span className="text-muted-foreground shrink-0 tabular-nums">
              {sub.total.toLocaleString(numberLocale)}
            </span>
            <Link
              href={`/reviews?primary_categories=${encodeURIComponent(primaryCategory)}&perspective_codes=${encodeURIComponent(sub.code)}&sentiment_labels=${encodeURIComponent("NEGATIF")}`}
              title={t("dashboard.categoryBreakdown.negativeShare", {
                pct: sub.negative_share.toLocaleString(numberLocale),
              })}
              className="shrink-0 text-red-600 tabular-nums transition-opacity hover:opacity-80 dark:text-red-400"
            >
              {sub.negative_count.toLocaleString(numberLocale)} (%
              {sub.negative_share.toLocaleString(numberLocale)})
            </Link>
            <button
              type="button"
              onClick={() =>
                onRootCause(
                  sub.code,
                  sub.code === UNMATCHED_CODE
                    ? t("dashboard.categoryBreakdown.unmatched")
                    : sub.label_tr,
                )
              }
              className="text-muted-foreground hover:text-foreground inline-flex shrink-0 items-center gap-1 transition-colors"
            >
              <Sparkles className="size-3" aria-hidden />
              {t("dashboard.rootCause.action")}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
