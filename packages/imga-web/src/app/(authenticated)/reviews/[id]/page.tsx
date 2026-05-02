"use client";

import { ArrowRight, ChevronLeft, Loader2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useManualPromoteReview, useReviewDetail } from "@/hooks/use-reviews";
import { ApiError } from "@/lib/api-client";
import type { ReviewDecision } from "@/lib/types";

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
        <p className="text-destructive p-6 text-sm">
          Analiz bulunamadı veya erişim yok.
        </p>
      )}

      {detail.data && (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Analiz</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <p className="text-muted-foreground text-xs">Tarih</p>
                <p className="text-sm">
                  {new Date(detail.data.analyzed_at).toLocaleString("tr-TR")}
                  {" — "}
                  {detail.data.source_type === "batch" ? "Toplu Yükleme" : "Manuel"}
                </p>
              </div>

              <div>
                <p className="text-muted-foreground text-xs">Metin</p>
                <p className="whitespace-pre-wrap text-sm">{detail.data.text}</p>
              </div>

              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <Stat label="Duygu" value={detail.data.sentiment.label} />
                <Stat
                  label="Skor (final)"
                  value={detail.data.sentiment.final_score.toFixed(2)}
                />
                <Stat label="Kategori" value={detail.data.categorization.primary} />
                <Stat
                  label="Güven"
                  value={`%${(detail.data.categorization.primary_confidence * 100).toFixed(0)}`}
                />
              </div>

              <div className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">
                Override katmanları detayı ve raw / final skor ayrımı
                Sprint 8.3.4&apos;te eklenecek. Şu an karar:{" "}
                <Badge variant="outline">{detail.data.auto_ticket_decision}</Badge>
              </div>

              {detail.data.ticket_id ? (
                <Button render={<Link href={`/tickets/${detail.data.ticket_id}`} />}>
                  Bağlı Bilete Git →
                </Button>
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
                    Manuel override — sistem güveni eşik altındaydı.
                  </span>
                </div>
              ) : null}
            </CardContent>
          </Card>
        </>
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
