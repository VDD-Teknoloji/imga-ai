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
  const query = useSentimentByCategory({}, 10);

  if (query.isLoading) {
    return (
      <section className="bg-card rounded-xl border p-4">
        <SectionHeader />
        <div className="mt-3 space-y-2">
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
    <section className="bg-card rounded-xl border p-4">
      <SectionHeader />
      {rows.length === 0 ? (
        <p className="text-muted-foreground mt-3 text-sm">
          Negatif sinyal yok — son dönemde dikkat çeken bir kategori
          bulunmadı.
        </p>
      ) : (
        <ul className="mt-3 space-y-1.5">
          {rows.map((r) => (
            <li key={r.code}>
              <Link
                href={`/reviews?primary_categories=${encodeURIComponent(r.code)}&sentiment_labels=NEGATİF`}
                className="hover:bg-accent group flex items-center gap-3 rounded-lg px-2 py-2 transition-colors"
              >
                <span
                  className="bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-300 inline-flex size-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold tabular-nums"
                  aria-hidden
                >
                  {r.negativeCount}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">{r.label}</p>
                  <p className="text-muted-foreground text-xs">
                    {r.totalCount > 0
                      ? `toplam ${r.totalCount} yorum içinde`
                      : `${r.negativeCount} negatif yorum`}
                  </p>
                </div>
                <ArrowRight
                  className="text-muted-foreground group-hover:text-foreground size-4 shrink-0 transition-colors"
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
  return (
    <header className="flex items-center gap-2">
      <Flame className="text-primary size-4" aria-hidden />
      <h2 className="text-sm font-semibold">Bugün dikkat</h2>
      <span className="text-muted-foreground text-xs">
        en çok negatif yorum alan kategoriler
      </span>
    </header>
  );
}
