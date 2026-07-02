"use client";

// Sprint 8.3.4 — "Bu Ticket'ı Açan Analiz" panel.
//
// Renders a compact preview of the originating review on the ticket
// detail page: trigger pills (override layer Türkçe labels) + a link
// to the full /reviews/[id] page. Skipped entirely when the ticket
// has no review_id (manually-created tickets predate the bridge).

import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { OverrideChip } from "@/components/reviews/override-display";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useReviewDetail } from "@/hooks/use-reviews";
import { useTranslation } from "@/lib/i18n/use-translation";
import {
  type OverrideLayer,
  OVERRIDE_LAYER_LABELS_TR,
} from "@/lib/types";

export function LinkedReviewSection({ reviewId }: { reviewId: string | null }) {
  const { t } = useTranslation();
  const review = useReviewDetail(reviewId);

  if (!reviewId) return null;
  if (review.isLoading) {
    return (
      <section className="bg-card flex flex-col gap-2 rounded-lg border p-4">
        <h2 className="text-sm font-semibold">{t("tickets.linkedReview.title")}</h2>
        <p className="text-muted-foreground text-xs">{t("tickets.common.loading")}</p>
      </section>
    );
  }
  if (review.error || !review.data) return null;

  const hits = review.data.overrides_applied;
  const labels = hits
    .map((h) => OVERRIDE_LAYER_LABELS_TR[h.layer as OverrideLayer] ?? h.layer)
    .slice(0, 4);

  return (
    <section className="bg-card flex flex-col gap-3 rounded-lg border p-4">
      <header className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{t("tickets.linkedReview.title")}</h2>
        <OverrideChip count={hits.length} />
      </header>
      <p className="text-muted-foreground line-clamp-2 text-xs">
        {review.data.text}
      </p>
      {labels.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {labels.map((label, i) => (
            <Badge key={`${label}-${i}`} variant="secondary" className="text-[11px]">
              {label}
            </Badge>
          ))}
        </div>
      )}
      <Button
        variant="outline"
        size="sm"
        className="self-start gap-1"
        render={<Link href={`/reviews/${review.data.id}`} />}
      >
        {t("tickets.linkedReview.viewDetail")}
        <ArrowRight className="size-3.5" aria-hidden />
      </Button>
    </section>
  );
}
