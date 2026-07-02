"use client";

// Sprint 8.3.4 dashboard widget — top-5 categories × sentiment heatmap.
// Reuses the shared <Heatmap> component but caps at 5 rows so the
// dashboard variant fits below a 30-day trend chart without
// dominating the viewport.

import { useRouter } from "next/navigation";

import { Heatmap } from "@/components/charts/heatmap";
import { Skeleton } from "@/components/ui/skeleton";
import { useSentimentByCategory } from "@/hooks/use-analytics";
import { useTranslation } from "@/lib/i18n/use-translation";

export function CategorySentimentMiniHeatmap() {
  const { t } = useTranslation();
  const router = useRouter();
  const matrix = useSentimentByCategory({}, 5);

  return (
    <section className="bg-card rounded-lg border p-5">
      <header className="mb-4 flex items-baseline justify-between">
        <h2 className="text-base font-semibold tracking-tight">
          {t("dashboard.categoryHeatmap.title")}
        </h2>
        <p className="text-muted-foreground text-xs">
          {t("dashboard.common.top5Categories")}
        </p>
      </header>
      {matrix.isLoading ? (
        <Skeleton className="h-[220px]" />
      ) : matrix.isError ? (
        <p className="text-destructive py-12 text-center text-sm">
          {t("dashboard.common.loadFailed")}
        </p>
      ) : !matrix.data || matrix.data.categories.length === 0 ? (
        <p className="text-muted-foreground py-12 text-center text-sm">
          {t("dashboard.common.noData")}
        </p>
      ) : (
        <Heatmap
          rows={matrix.data.category_labels_tr}
          cols={matrix.data.sentiments}
          matrix={matrix.data.matrix}
          rowTotals={matrix.data.totals_by_category}
          colTotals={matrix.data.totals_by_sentiment}
          colorScale="blue"
          height={220}
          tooltip={(value, rowLabel, colLabel) =>
            t("dashboard.categoryHeatmap.tooltip", {
              row: rowLabel,
              col: colLabel,
              value,
            })
          }
          onCellClick={(i, j) => {
            const cat = matrix.data?.categories[i];
            const sent = matrix.data?.sentiments[j];
            if (!cat || !sent) return;
            // Sprint 9.0.5-B F — was ?category=… which the
            // /reviews filter parser doesn't read; the page reads
            // ?primary_categories=… (comma-separated). The drill-
            // down was silently landing on an unfiltered list.
            router.push(
              `/reviews?sentiment_labels=${encodeURIComponent(sent)}&primary_categories=${encodeURIComponent(cat)}`,
            );
          }}
        />
      )}
    </section>
  );
}
