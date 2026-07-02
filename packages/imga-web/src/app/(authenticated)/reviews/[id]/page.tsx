"use client";

import { ArrowRight, ChevronLeft, Loader2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { toast } from "sonner";

import { CorrectReviewDialog } from "@/components/reviews/correct-review-dialog";
import { OverrideStack } from "@/components/reviews/override-display";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useManualPromoteReview, useReviewDetail } from "@/hooks/use-reviews";
import { ApiError } from "@/lib/api-client";
import { useTranslation } from "@/lib/i18n/use-translation";
import type { ReviewDecision } from "@/lib/types";

// Map every decision branch to an i18n key + the auto-ticket rationale so
// the detail page reads as an audit narrative, not a bag of enum values.
// Reasons mirror the bridge's decision tree in
// imga_api.services.review_service.
const DECISION_LABEL_KEYS: Record<ReviewDecision, string> = {
  create: "reviews.decision.create",
  skipped_belirsiz: "reviews.decision.skippedBelirsiz",
  skipped_mode: "reviews.decision.skippedMode",
  skipped_threshold: "reviews.decision.skippedThreshold",
  skipped_dedup: "reviews.decision.skippedDedup",
};

const PROMOTABLE_DECISIONS: ReadonlySet<ReviewDecision> = new Set([
  "skipped_mode",
  "skipped_threshold",
  "skipped_belirsiz",
]);

/**
 * Sprint 8.3.1 placeholder — full layout (override layer cards,
 * raw vs final score split, linked-ticket section) lands in 8.3.4.
 */
export default function ReviewDetailPage() {
  const { t } = useTranslation();
  const params = useParams<{ id: string }>();
  const reviewId = params?.id ?? null;
  const detail = useReviewDetail(reviewId);
  const promote = useManualPromoteReview();

  const canPromote =
    detail.data != null &&
    detail.data.ticket_id == null &&
    PROMOTABLE_DECISIONS.has(detail.data.auto_ticket_decision);

  function handlePromote() {
    if (!detail.data) return;
    promote.mutate(detail.data.id, {
      onSuccess: () => {
        toast.success(t("reviews.detail.promoteSuccess"));
        detail.refetch();
      },
      onError: (err) => {
        if (err instanceof ApiError && err.status === 403) {
          toast.error(t("reviews.detail.noPermission"));
          return;
        }
        if (err instanceof ApiError && err.status === 409) {
          toast.error(t("reviews.detail.alreadyLinked"));
          return;
        }
        toast.error(t("reviews.detail.promoteError"));
      },
    });
  }

  return (
    <main className="mx-auto w-full max-w-3xl space-y-6 px-4 py-8">
      <Link
        href="/reviews"
        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
      >
        <ChevronLeft className="size-4" /> {t("reviews.detail.backToList")}
      </Link>

      {detail.isLoading && (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> {t("common.loading")}
        </div>
      )}

      {detail.error && (
        <p className="text-destructive p-6 text-sm">
          {t("reviews.detail.notFound")}
        </p>
      )}

      {detail.data && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>
                {t("reviews.detail.analysisNo", {
                  id: detail.data.id.slice(0, 8),
                })}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-muted-foreground text-xs">
                  {t("reviews.detail.date")}
                </p>
                <p className="text-sm">
                  {new Date(detail.data.analyzed_at).toLocaleString("tr-TR")}
                  {" — "}
                  {detail.data.source_type === "batch"
                    ? t("reviews.detail.batchUpload")
                    : t("reviews.source.manual")}
                  {detail.data.batch_job_id && (
                    <>
                      {" "}
                      (Batch:{" "}
                      <span className="font-mono">{detail.data.batch_job_id.slice(0, 8)}</span>)
                    </>
                  )}
                </p>
              </div>

              <div>
                <p className="text-muted-foreground text-xs">
                  {t("reviews.detail.text")}
                </p>
                <p className="text-sm whitespace-pre-wrap">{detail.data.text}</p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between gap-3 space-y-0">
              <CardTitle className="text-base">
                {t("reviews.detail.analysis")}
              </CardTitle>
              {/* Sprint 11.0 — düzeltme-geri-besleme girişi. Yanlış
                  karar buradan düzeltilir; sistem benzer yorumlarda
                  düzeltmeyi örnek alır. */}
              <CorrectReviewDialog
                reviewId={detail.data.id}
                currentSentiment={detail.data.sentiment.label}
                currentCategory={detail.data.categorization.primary}
              />
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Stat
                  label={t("reviews.detail.sentiment")}
                  value={detail.data.sentiment.label}
                />
                <Stat
                  label={t("reviews.detail.scoreFinal")}
                  value={detail.data.sentiment.final_score.toFixed(2)}
                />
                <Stat
                  label={t("reviews.detail.scoreRaw")}
                  value={detail.data.sentiment.raw_score.toFixed(2)}
                />
                <Stat
                  label={t("reviews.detail.confidence")}
                  value={t("reviews.detail.percentValue", {
                    value: (
                      detail.data.categorization.primary_confidence * 100
                    ).toFixed(0),
                  })}
                />
              </div>
              <div>
                <p className="text-muted-foreground text-xs">
                  {t("reviews.detail.category")}
                </p>
                <p className="text-sm">{detail.data.categorization.primary}</p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                {t("reviews.detail.companyPerspective")}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <p className="text-muted-foreground text-xs">
                    {t("reviews.detail.bertCategory")}
                  </p>
                  <p className="text-sm font-medium">{detail.data.categorization.primary}</p>
                </div>
                <div>
                  <p className="text-muted-foreground text-xs">
                    {t("reviews.detail.heuristicPerspective")}
                  </p>
                  <p className="text-sm font-medium">
                    {detail.data.company_perspective.code === null ? (
                      <span className="text-muted-foreground italic">
                        {t("reviews.detail.noMatch")}
                      </span>
                    ) : detail.data.company_perspective.label_tr === null ? (
                      <span className="text-muted-foreground italic">
                        {t("reviews.detail.removedCategoryPre")}{" "}
                        <span className="font-mono">{detail.data.company_perspective.code}</span>
                        {t("reviews.detail.removedCategoryPost")}
                      </span>
                    ) : (
                      detail.data.company_perspective.label_tr
                    )}
                  </p>
                </div>
              </div>
              {detail.data.nps_score !== null && (
                <div>
                  <p className="text-muted-foreground text-xs">NPS</p>
                  <p className="text-sm">
                    {detail.data.nps_score} /10{" "}
                    {detail.data.nps_category && (
                      <Badge variant="outline" className="ml-1">
                        {detail.data.nps_category === "promoter"
                          ? "Promoter"
                          : detail.data.nps_category === "passive"
                            ? "Passive"
                            : "Detractor"}
                      </Badge>
                    )}
                  </p>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                {t("reviews.detail.ruleLayers")}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <OverrideStack hits={detail.data.overrides_applied} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                {t("reviews.detail.decision")}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center gap-2">
                <Badge variant="outline">
                  {DECISION_LABEL_KEYS[detail.data.auto_ticket_decision]
                    ? t(DECISION_LABEL_KEYS[detail.data.auto_ticket_decision])
                    : detail.data.auto_ticket_decision}
                </Badge>
                {detail.data.auto_ticket_decision_reason && (
                  <span className="text-muted-foreground font-mono text-xs">
                    {detail.data.auto_ticket_decision_reason}
                  </span>
                )}
              </div>

              {detail.data.ticket_id ? (
                <div className="bg-muted/30 flex items-center justify-between rounded-md border p-3">
                  <p className="text-sm">
                    {t("reviews.detail.linkedTicket")}{" "}
                    <span className="font-mono">#{detail.data.ticket_id.slice(0, 8)}</span>
                  </p>
                  <Button size="sm" render={<Link href={`/tickets/${detail.data.ticket_id}`} />}>
                    {t("reviews.detail.goToTicket")}
                  </Button>
                </div>
              ) : canPromote ? (
                <div className="flex flex-wrap items-center gap-3">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={handlePromote}
                    disabled={promote.isPending}
                    className="gap-2"
                  >
                    {promote.isPending ? (
                      <Loader2 className="size-4 animate-spin" aria-hidden />
                    ) : (
                      <ArrowRight className="size-4" aria-hidden />
                    )}
                    {t("reviews.detail.promoteButton")}
                  </Button>
                  <span className="text-muted-foreground text-xs">
                    {t("reviews.detail.promoteHint")}
                  </span>
                </div>
              ) : null}
            </CardContent>
          </Card>
        </div>
      )}
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-muted/30 rounded-md border p-3">
      <p className="text-muted-foreground text-xs">{label}</p>
      <p className="text-lg font-semibold">{value}</p>
    </div>
  );
}
