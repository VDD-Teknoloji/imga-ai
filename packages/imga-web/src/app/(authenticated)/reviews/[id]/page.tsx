"use client";

import { ArrowRight, ChevronLeft, ExternalLink, Loader2, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { toast } from "sonner";

import { CorrectReviewDialog } from "@/components/reviews/correct-review-dialog";
import { OverrideStack } from "@/components/reviews/override-display";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogHeader,
  AlertDialogFooter,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useCategories } from "@/hooks/use-categories";
import { useReanalyzeReview } from "@/hooks/use-reanalyze";
import { useRoleFlags } from "@/hooks/use-role-flags";
import { useManualPromoteReview, useReviewDetail, type ReviewFacts } from "@/hooks/use-reviews";
import { ApiError } from "@/lib/api-client";
import { effectiveExperience, type ExperienceType } from "@/lib/experience";
import { useTranslation } from "@/lib/i18n/use-translation";
import { NPS_CATEGORY_LABELS, type ReviewDecision } from "@/lib/types";
import { formatDurationMinutes } from "@/lib/number-format";
import { sentimentScoreBucket } from "@/lib/sentiment-score";
import { sourceLinkLabelKey } from "@/lib/source-link";

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
  skipped_quality: "reviews.decision.skippedQuality",
  // NOT (2026-08-18, WS5): backend'in yeni skipped_quality dalı
  // (migration 0042) bilinçli olarak yok — bkz. lib/types.ts
  // ReviewDecision NOT'u (analyze/page.tsx exhaustive map çakışması).
};

const PROMOTABLE_DECISIONS: ReadonlySet<ReviewDecision> = new Set([
  "skipped_mode",
  "skipped_threshold",
  "skipped_belirsiz",
]);

// reviews/page.tsx ile aynı harita — ham POZITIF/NEGATIF/NÖTR enum'u
// yerine locale'e uygun etiket.
const SENTIMENT_LABEL_KEYS: Record<string, string> = {
  NEGATIF: "reviews.sentiment.negatif",
  POZITIF: "reviews.sentiment.pozitif",
  "NÖTR": "reviews.sentiment.notr",
};

// 2026-09-01 — Twitter bağlantısı: source_meta'daki bilinen sayaç
// anahtarları, gösterim sırası + etiket eşlemesiyle. source_meta açık
// bir Record olduğu için burada listelenmeyen anahtarlar (ileride
// eklenebilir) sessizce yok sayılır — bilinmeyen bir alanın rastgele
// bir etiketle gösterilmesindense.
const ENGAGEMENT_FIELDS: ReadonlyArray<{ key: string; labelKey: string }> = [
  { key: "like_count", labelKey: "reviews.detail.engagement.like" },
  { key: "retweet_count", labelKey: "reviews.detail.engagement.retweet" },
  { key: "reply_count", labelKey: "reviews.detail.engagement.reply" },
  { key: "view_count", labelKey: "reviews.detail.engagement.view" },
];

/**
 * Sprint 8.3.1 placeholder — full layout (override layer cards,
 * raw vs final score split, linked-ticket section) lands in 8.3.4.
 *
 * useSearchParams gereği Suspense sarmalayıcı zorunlu —
 * docs/agent-rules/url-state-patterns.md.
 */
export default function ReviewDetailPage() {
  return (
    <Suspense fallback={<ReviewDetailSkeleton />}>
      <ReviewDetailInner />
    </Suspense>
  );
}

function ReviewDetailSkeleton() {
  const { t } = useTranslation();
  return (
    <main className="mx-auto w-full max-w-3xl space-y-6 px-4 py-8">
      <div className="flex items-center gap-2 p-6 text-sm">
        <Loader2 className="size-4 animate-spin" /> {t("common.loading")}
      </div>
    </main>
  );
}

function ReviewDetailInner() {
  const { t } = useTranslation();
  const params = useParams<{ id: string }>();
  // Liste sayfasından taşınan filtre query-string'i — "Listeye dön"
  // aynı filtrelerle geri döner (bare /reviews filtreleri sıfırlıyordu).
  const searchParams = useSearchParams();
  const listQs = searchParams.toString();
  const backHref = listQs ? `/reviews?${listQs}` : "/reviews";
  const reviewId = params?.id ?? null;
  const detail = useReviewDetail(reviewId);
  const promote = useManualPromoteReview();
  const reanalyze = useReanalyzeReview();
  const [reanalyzeOpen, setReanalyzeOpen] = useState(false);
  const { isAdmin } = useRoleFlags();
  const categories = useCategories();
  const categoryLabelFor = (code: string): string =>
    categories.data?.find((c) => c.code === code)?.label_tr ?? code;
  // Deneyim tipi backend alanından okunur; eski satırlarda alan yok,
  // effectiveExperience kategori yedeğine düşer, o da boşsa "—".
  const experienceLabel = (kind: ExperienceType | null): string =>
    kind === null ? "—" : t(`reviews.experience.${kind}`);

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
          // 409 ayrımı: zaten bağlı / yapılandırılmamış kategori
          // (UAT HATA-03 FE).
          toast.error(
            err.detail.includes("not configured")
              ? t("reviews.detail.categoryNotConfigured")
              : t("reviews.detail.alreadyLinked"),
          );
          return;
        }
        toast.error(t("reviews.detail.promoteError"));
      },
    });
  }

  function handleReanalyzeConfirm() {
    if (!detail.data) return;
    reanalyze.mutate(detail.data.id, {
      onSuccess: () => {
        toast.success(t("reviews.detail.reanalyzeQueued"));
        setReanalyzeOpen(false);
        detail.refetch();
      },
      onError: (err) => {
        if (err instanceof ApiError && err.status === 409) {
          // 409 — insan düzeltmesi var ya da metin boş (aday değil).
          toast.error(t("reviews.detail.reanalyzeNotCandidate"));
          return;
        }
        if (err instanceof ApiError && err.status === 403) {
          toast.error(t("reviews.detail.reanalyzeNoPermission"));
          return;
        }
        toast.error(t("reviews.detail.reanalyzeFailed"));
      },
    });
  }

  return (
    <main className="mx-auto w-full max-w-3xl space-y-6 px-4 py-8">
      <Link
        href={backHref}
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
                  {new Date(detail.data.review_date).toLocaleString("tr-TR")}
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
                <p className="text-muted-foreground mt-1 text-xs">
                  {t("reviews.detail.analyzedAt")}:{" "}
                  {new Date(detail.data.analyzed_at).toLocaleString("tr-TR")}
                </p>
                {detail.data.source_url && (
                  <a
                    href={detail.data.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="border-border hover:bg-muted mt-2 inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition-colors"
                  >
                    <ExternalLink className="size-3.5" aria-hidden />
                    {t(sourceLinkLabelKey(detail.data.source_url))}
                  </a>
                )}
                <EngagementChips sourceMeta={detail.data.source_meta} />
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
              <div className="flex items-center gap-2">
                {/* F2 (2026-09-01) — satır bazlı yeniden analiz. Uç
                    _TenantAdmin'e kapalı (maliyetli iş), bu yüzden düğme
                    de yalnız yöneticide görünür — analist görüp 403
                    yememeli. Backend 409 = aday değil (insan düzeltmesi
                    var ya da metin boş). */}
                {isAdmin && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="gap-2"
                    onClick={() => setReanalyzeOpen(true)}
                    disabled={reanalyze.isPending}
                  >
                    {reanalyze.isPending ? (
                      <Loader2 className="size-4 animate-spin" aria-hidden />
                    ) : (
                      <RefreshCw className="size-4" aria-hidden />
                    )}
                    {t("reviews.detail.reanalyze")}
                  </Button>
                )}
                {/* Sprint 11.0 — düzeltme-geri-besleme girişi. Yanlış
                    karar buradan düzeltilir; sistem benzer yorumlarda
                    düzeltmeyi örnek alır. */}
                <CorrectReviewDialog
                  reviewId={detail.data.id}
                  currentSentiment={detail.data.sentiment.label}
                  currentCategory={detail.data.categorization.primary}
                  currentScore={detail.data.sentiment.final_score}
                  currentExperienceType={detail.data.experience_type ?? null}
                  currentPerspectiveCode={detail.data.company_perspective.code}
                />
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Stat
                  label={t("reviews.detail.sentiment")}
                  value={
                    SENTIMENT_LABEL_KEYS[detail.data.sentiment.label]
                      ? t(SENTIMENT_LABEL_KEYS[detail.data.sentiment.label]!)
                      : detail.data.sentiment.label
                  }
                />
                <Stat
                  label={t("reviews.detail.scoreFinal")}
                  value={detail.data.sentiment.final_score.toFixed(2)}
                  sublabel={t(
                    `reviews.scoreLabel.${sentimentScoreBucket(detail.data.sentiment.final_score)}`,
                  )}
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
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <p className="text-muted-foreground text-xs">
                    {t("reviews.detail.category")}
                  </p>
                  <p className="text-sm">
                    {categoryLabelFor(detail.data.categorization.primary)}
                  </p>
                </div>
                <div>
                  <p className="text-muted-foreground text-xs">
                    {t("reviews.detail.experience")}
                  </p>
                  <p className="text-sm">
                    {experienceLabel(
                      effectiveExperience(
                        detail.data.experience_type,
                        detail.data.categorization.primary,
                      ),
                    )}
                  </p>
                </div>
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
              {detail.data.nps_score !== null && (
                <div>
                  <p className="text-muted-foreground text-xs">NPS</p>
                  <p className="text-sm">
                    {detail.data.nps_score} /10{" "}
                    {detail.data.nps_category && (
                      <Badge variant="outline" className="ml-1">
                        {NPS_CATEGORY_LABELS[detail.data.nps_category]}
                      </Badge>
                    )}
                  </p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* 2026-08-21 (Operasyonel analitik) — facts null/absent iken
              kart hiç gösterilmiyor (backend paralel yazılıyor; alan
              deploy öncesi yanıtta hiç yer almayabilir). */}
          {detail.data.facts != null && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  {t("reviews.detail.operationalInfo")}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <OperationalFactsGrid facts={detail.data.facts} t={t} />
              </CardContent>
            </Card>
          )}

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

          <AlertDialog open={reanalyzeOpen} onOpenChange={setReanalyzeOpen}>
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>{t("reviews.detail.reanalyze")}</AlertDialogTitle>
                <AlertDialogDescription>
                  {t("reviews.detail.reanalyzeConfirm")}
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel disabled={reanalyze.isPending}>
                  {t("common.cancel")}
                </AlertDialogCancel>
                <AlertDialogAction
                  onClick={handleReanalyzeConfirm}
                  disabled={reanalyze.isPending}
                >
                  {t("reviews.detail.reanalyze")}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      )}
    </main>
  );
}

// 2026-09-01 — Twitter etkileşim rozetleri. source_meta yoksa (null/
// undefined) veya ENGAGEMENT_FIELDS'teki 4 anahtardan hiçbiri gelmediyse
// hiçbir şey render etmiyor — gövde boş "· ·" satırı bırakmasın diye.
// Gelen değer 0 olsa bile anahtar VARSA gösterilir (yalnız EKSİK anahtar
// atlanır); "Beğeni 0" görmek "hiç veri yok" demekten farklı bir sinyal.
function EngagementChips({
  sourceMeta,
}: {
  sourceMeta: Record<string, number> | null | undefined;
}) {
  const { t } = useTranslation();
  if (!sourceMeta) return null;
  const chips = ENGAGEMENT_FIELDS.filter(
    ({ key }) => sourceMeta[key] !== undefined,
  ).map(
    ({ key, labelKey }) => `${t(labelKey)} ${sourceMeta[key]!.toLocaleString("tr-TR")}`,
  );
  if (chips.length === 0) return null;
  return <p className="text-muted-foreground mt-2 text-xs">{chips.join(" · ")}</p>;
}

function Stat({
  label,
  value,
  sublabel,
}: {
  label: string;
  value: string;
  /** Sayısal değerin altında gösterilen küçük, soluk etiket — örn.
   *  skor kovası ("Çok olumlu"). */
  sublabel?: string;
}) {
  return (
    <div className="bg-muted/30 rounded-md border p-3">
      <p className="text-muted-foreground text-xs">{label}</p>
      <p className="text-lg font-semibold">{value}</p>
      {sublabel && <p className="text-muted-foreground text-xs">{sublabel}</p>}
    </div>
  );
}

// --- 2026-08-21 (Operasyonel analitik) — "Operasyonel Bilgiler" kartı ---

type Translate = (key: string, vars?: Record<string, string | number>) => string;

function slaStatusLabel(
  status: "within" | "violated" | null,
  t: Translate,
): string | null {
  if (status === "within") return t("reviews.detail.facts.slaWithin");
  if (status === "violated") return t("reviews.detail.facts.slaViolated");
  return null;
}

/** facts'ın 13 alanını label/value satırlarına çevirir; null alanlar
 *  ATLANIR (görev kuralı — "null alanlar atlanır"). */
function buildFactRows(
  facts: ReviewFacts,
  t: Translate,
): Array<{ key: string; label: string; value: string }> {
  const rows: Array<{ key: string; label: string; value: string }> = [];

  const slaResolution = slaStatusLabel(facts.sla_resolution_status, t);
  if (slaResolution !== null) {
    rows.push({
      key: "slaResolution",
      label: t("reviews.detail.facts.slaResolutionStatus"),
      value: slaResolution,
    });
  }
  const slaFirstResponse = slaStatusLabel(facts.sla_first_response_status, t);
  if (slaFirstResponse !== null) {
    rows.push({
      key: "slaFirstResponse",
      label: t("reviews.detail.facts.slaFirstResponseStatus"),
      value: slaFirstResponse,
    });
  }
  if (facts.resolution_time_minutes !== null) {
    rows.push({
      key: "resolutionTime",
      label: t("reviews.detail.facts.resolutionTime"),
      value: formatDurationMinutes(facts.resolution_time_minutes),
    });
  }
  if (facts.first_response_time_minutes !== null) {
    rows.push({
      key: "firstResponseTime",
      label: t("reviews.detail.facts.firstResponseTime"),
      value: formatDurationMinutes(facts.first_response_time_minutes),
    });
  }
  if (facts.csat_score !== null) {
    rows.push({
      key: "csat",
      label: t("reviews.detail.facts.csat"),
      value: facts.csat_raw ? `${facts.csat_score}/5 (${facts.csat_raw})` : `${facts.csat_score}/5`,
    });
  } else if (facts.csat_raw !== null) {
    rows.push({
      key: "csatRaw",
      label: t("reviews.detail.facts.csat"),
      value: facts.csat_raw,
    });
  }
  if (facts.agent_interactions !== null) {
    rows.push({
      key: "agentInteractions",
      label: t("reviews.detail.facts.agentInteractions"),
      value: String(facts.agent_interactions),
    });
  }
  if (facts.customer_interactions !== null) {
    rows.push({
      key: "customerInteractions",
      label: t("reviews.detail.facts.customerInteractions"),
      value: String(facts.customer_interactions),
    });
  }
  if (facts.compensation_status !== null) {
    rows.push({
      key: "compensationStatus",
      label: t("reviews.detail.facts.compensationStatus"),
      value: facts.compensation_status,
    });
  }
  if (facts.freight_cost !== null) {
    rows.push({
      key: "freightCost",
      label: t("reviews.detail.facts.freightCost"),
      value: facts.freight_cost.toLocaleString("tr-TR"),
    });
  }
  if (facts.goods_cost !== null) {
    rows.push({
      key: "goodsCost",
      label: t("reviews.detail.facts.goodsCost"),
      value: facts.goods_cost.toLocaleString("tr-TR"),
    });
  }
  if (facts.refund_reason !== null) {
    rows.push({
      key: "refundReason",
      label: t("reviews.detail.facts.refundReason"),
      value: facts.refund_reason,
    });
  }
  if (facts.delivery_status !== null) {
    rows.push({
      key: "deliveryStatus",
      label: t("reviews.detail.facts.deliveryStatus"),
      value: facts.delivery_status,
    });
  }
  if (facts.delivery_detail !== null) {
    rows.push({
      key: "deliveryDetail",
      label: t("reviews.detail.facts.deliveryDetail"),
      value: facts.delivery_detail,
    });
  }
  return rows;
}

function OperationalFactsGrid({ facts, t }: { facts: ReviewFacts; t: Translate }) {
  const rows = buildFactRows(facts, t);
  if (rows.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("insights.state.noData")}</p>;
  }
  return (
    <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {rows.map((row) => (
        <div key={row.key}>
          <dt className="text-muted-foreground text-xs">{row.label}</dt>
          <dd className="text-sm">{row.value}</dd>
        </div>
      ))}
    </dl>
  );
}
