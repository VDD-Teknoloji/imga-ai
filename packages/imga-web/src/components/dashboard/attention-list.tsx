"use client";

// Sprint 9.6 redesign — "Bugün dikkat" attention list.
//
// Replaces the SentimentDonut + CategoryChart + CategorySentimentMiniHeatmap
// triplet on the old dashboard. Those rendered raw counts ("90
// negatif, 100 nötr, 1000 pozitif") — exactly the chart shape the
// product owner flagged as "C-level kullanıcılar bunu istemiyor".
//
// Instead: 3 ranked rows reading from sentiment-by-category. Each
// row shows a Turkish-labelled category, its negative-sentiment
// volume, and a click-through that lands on /reviews with the
// right composite filter (primary_categories + sentiment_labels)
// so the executive sees the actual evidence in one click.
//
// "Drill-down on click" is the entire reason this card replaces
// the donut — the donut had no actionable next step. The list does.

import { ArrowRight, Flame } from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import { useSentimentByCategory } from "@/hooks/use-analytics";
import { useTranslation } from "@/lib/i18n/use-translation";

interface AttentionRow {
  code: string;
  label: string;
  negativeCount: number;
  totalCount: number;
}

function compute(
  matrix: number[][] | undefined,
  categories: string[] | undefined,
  categoryLabels: string[] | undefined,
  sentiments: string[] | undefined,
  totals: number[] | undefined,
): AttentionRow[] {
  if (!matrix || !categories || !sentiments || !totals) return [];
  // sentiments order isn't fixed across deployments; find NEGATIF.
  // Backend uppercases Turkish labels for the matrix headers.
  const negIdx = sentiments.findIndex((s) => s.toUpperCase().startsWith("NEGAT"));
  if (negIdx === -1) return [];
  const rows: AttentionRow[] = [];
  for (let i = 0; i < categories.length; i++) {
    const negativeCount = matrix[i]?.[negIdx] ?? 0;
    if (negativeCount === 0) continue;
    rows.push({
      code: categories[i] ?? "",
      label: categoryLabels?.[i] ?? categories[i] ?? "",
      negativeCount,
      totalCount: totals[i] ?? 0,
    });
  }
  rows.sort((a, b) => b.negativeCount - a.negativeCount);
  return rows.slice(0, 5);
}

export function AttentionList() {
  const { t } = useTranslation();
  const query = useSentimentByCategory({}, 10);

  if (query.isLoading) {
    return (
      <section className="bg-card shadow-soft ring-foreground/5 rise-in rounded-2xl p-5 ring-1">
        <SectionHeader />
        <div className="mt-4 space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-12 w-full" />
          ))}
        </div>
      </section>
    );
  }

  const rows = compute(
    query.data?.matrix,
    query.data?.categories,
    query.data?.category_labels_tr,
    query.data?.sentiments,
    query.data?.totals_by_category,
  );

  return (
    <section className="bg-card shadow-soft ring-foreground/5 rise-in rounded-2xl p-5 ring-1">
      <SectionHeader />
      {rows.length === 0 ? (
        <p className="text-muted-foreground mt-4 text-sm leading-relaxed">
          {t("dashboard.attentionList.empty")}
        </p>
      ) : (
        <ul className="mt-4 space-y-1">
          {rows.map((r) => (
            <li key={r.code}>
              <Link
                href={`/reviews?primary_categories=${encodeURIComponent(r.code)}&sentiment_labels=NEGATIF`}
                className="hover:bg-accent/60 group flex items-center gap-3 rounded-xl px-2 py-2.5 transition-colors duration-[var(--motion-duration)]"
              >
                <span
                  className="bg-gradient-to-br from-red-500/20 to-red-500/5 text-red-700 dark:text-red-300 ring-red-500/20 inline-flex size-9 shrink-0 items-center justify-center rounded-xl text-xs font-bold tabular-nums ring-1"
                  aria-hidden
                >
                  {r.negativeCount}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold truncate">{r.label}</p>
                  <p className="text-muted-foreground text-xs truncate">
                    {r.totalCount > 0
                      ? t("dashboard.attentionList.rowTotal", {
                          n: r.totalCount,
                        })
                      : t("dashboard.attentionList.rowNegative", {
                          n: r.negativeCount,
                        })}
                  </p>
                </div>
                <ArrowRight
                  className="text-muted-foreground/50 group-hover:text-primary group-hover:translate-x-0.5 size-4 shrink-0 transition-[color,transform] duration-[var(--motion-duration)]"
                  aria-hidden
                />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function SectionHeader() {
  const { t } = useTranslation();
  return (
    <header className="flex items-start gap-2.5">
      <span className="from-primary/20 to-primary/5 text-primary ring-primary/15 inline-flex size-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br ring-1">
        <Flame className="size-3.5" aria-hidden />
      </span>
      <div className="flex-1 min-w-0">
        <h2 className="text-sm font-semibold">
          {t("dashboard.attentionList.title")}
        </h2>
        <p className="text-muted-foreground text-xs">
          {t("dashboard.attentionList.subtitle")}
        </p>
      </div>
    </header>
  );
}
