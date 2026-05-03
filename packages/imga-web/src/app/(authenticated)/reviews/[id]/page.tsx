"use client";

import { ArrowRight, ChevronLeft, Loader2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { toast } from "sonner";

import { OverrideStack } from "@/components/reviews/override-display";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useManualPromoteReview, useReviewDetail } from "@/hooks/use-reviews";
import { ApiError } from "@/lib/api-client";
import type { ReviewDecision } from "@/lib/types";

// Map every decision branch to a Türkçe label + the auto-ticket
// rationale so the detail page reads as an audit narrative, not a
// bag of enum values. Reasons mirror the bridge's decision tree in
// imga_api.services.review_service.
const DECISION_LABELS_TR: Record<ReviewDecision, string> = {
  create: "Bilet Açıldı",
  skipped_belirsiz: "Atlandı (Kategori Belirsiz)",
  skipped_mode: "Atlandı (Manuel Mod)",
  skipped_threshold: "Atlandı (Eşik Altı)",
  skipped_dedup: "Atlandı (24s İçinde Mükerrer)",
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
        toast.success("Manuel olarak bilet açıldı.");
        detail.refetch();
      },
      onError: (err) => {
        if (err instanceof ApiError && err.status === 403) {
          toast.error("Bu işlem için yetkin yok.");
          return;
        }
        if (err instanceof ApiError && err.status === 409) {
          toast.error("Bu analiz zaten bir bilete bağlı.");
          return;
        }
        toast.error("Bilet açılamadı.");
      },
    });
  }

  return (
    <main className="mx-auto w-full max-w-3xl space-y-6 px-4 py-8">
      <Link
        href="/reviews"
        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
      >
        <ChevronLeft className="size-4" /> Analizler
      </Link>

      {detail.isLoading && (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> Yükleniyor…
        </div>
      )}

      {detail.error && (
        <p className="text-destructive p-6 text-sm">Analiz bulunamadı veya erişim yok.</p>
      )}

      {detail.data && (
        <div className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Analiz #{detail.data.id.slice(0, 8)}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-muted-foreground text-xs">Tarih</p>
                <p className="text-sm">
                  {new Date(detail.data.analyzed_at).toLocaleString("tr-TR")}
                  {" — "}
                  {detail.data.source_type === "batch" ? "Toplu Yükleme" : "Manuel"}
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
                <p className="text-muted-foreground text-xs">Metin</p>
                <p className="text-sm whitespace-pre-wrap">{detail.data.text}</p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Analiz</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <Stat label="Duygu" value={detail.data.sentiment.label} />
                <Stat label="Skor (final)" value={detail.data.sentiment.final_score.toFixed(2)} />
                <Stat label="Skor (raw, BERT)" value={detail.data.sentiment.raw_score.toFixed(2)} />
                <Stat
                  label="Güven"
                  value={`%${(detail.data.categorization.primary_confidence * 100).toFixed(0)}`}
                />
              </div>
              <div>
                <p className="text-muted-foreground text-xs">Kategori</p>
                <p className="text-sm">{detail.data.categorization.primary}</p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Şirket Perspektifi</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <p className="text-muted-foreground text-xs">BERT kategorisi</p>
                  <p className="text-sm font-medium">{detail.data.categorization.primary}</p>
                </div>
                <div>
                  <p className="text-muted-foreground text-xs">Heuristik perspektif</p>
                  <p className="text-sm font-medium">
                    {detail.data.company_perspective.code === null ? (
                      <span className="text-muted-foreground italic">eşleşme yok</span>
                    ) : detail.data.company_perspective.label_tr === null ? (
                      <span className="text-muted-foreground italic">
                        kaldırılmış kategori (kod:{" "}
                        <span className="font-mono">{detail.data.company_perspective.code}</span>)
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
              <CardTitle className="text-base">Override Katmanları</CardTitle>
            </CardHeader>
            <CardContent>
              <OverrideStack hits={detail.data.overrides_applied} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Karar</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center gap-2">
                <Badge variant="outline">
                  {DECISION_LABELS_TR[detail.data.auto_ticket_decision] ??
                    detail.data.auto_ticket_decision}
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
                    Bağlı bilet:{" "}
                    <span className="font-mono">#{detail.data.ticket_id.slice(0, 8)}</span>
                  </p>
                  <Button size="sm" render={<Link href={`/tickets/${detail.data.ticket_id}`} />}>
                    Bilete Git →
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
                    Bu Analizi Bilete Dönüştür
                  </Button>
                  <span className="text-muted-foreground text-xs">
                    Manuel override — bridge bu karar için bilet açmamıştı.
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
