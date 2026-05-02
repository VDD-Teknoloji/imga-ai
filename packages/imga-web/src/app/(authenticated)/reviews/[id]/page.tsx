"use client";

import { ChevronLeft, Loader2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useReviewDetail } from "@/hooks/use-reviews";

/**
 * Sprint 8.3.1 placeholder — full layout (override layer cards,
 * raw vs final score split, linked-ticket section) lands in 8.3.4.
 */
export default function ReviewDetailPage() {
  const params = useParams<{ id: string }>();
  const reviewId = params?.id ?? null;
  const detail = useReviewDetail(reviewId);

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

              {detail.data.ticket_id && (
                <Button render={<Link href={`/tickets/${detail.data.ticket_id}`} />}>
                  Bağlı Bilete Git →
                </Button>
              )}
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
