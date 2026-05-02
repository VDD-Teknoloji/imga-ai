"use client";

import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useInfiniteReviews } from "@/hooks/use-reviews";
import type { ReviewListFilters, ReviewSourceType } from "@/lib/types";
import { cn } from "@/lib/utils";

const SOURCE_LABELS: Record<ReviewSourceType, string> = {
  manual: "Manuel",
  batch: "Toplu",
  api: "API",
};

/**
 * Sprint 8.3.1 — minimal reviews list. Filter bar (sentiment, source,
 * has_ticket, batch_job_id from query string), table, infinite scroll.
 * Override count chip is rendered but not clickable yet — that polish
 * lands in Sprint 8.3.4.
 */
export default function ReviewsPage() {
  const searchParams = useSearchParams();

  const filters = useMemo<ReviewListFilters>(() => {
    const sentimentRaw = searchParams.get("sentiment_labels");
    const sourceRaw = searchParams.get("source_types");
    const sourceTypes = sourceRaw
      ? (sourceRaw.split(",").filter(Boolean) as ReviewSourceType[])
      : undefined;
    return {
      sentiment_labels: sentimentRaw?.split(",").filter(Boolean),
      source_types: sourceTypes,
      has_ticket: searchParams.has("has_ticket")
        ? searchParams.get("has_ticket") === "true"
        : undefined,
      batch_job_id: searchParams.get("batch_job_id") ?? undefined,
      search: searchParams.get("search") ?? undefined,
    };
  }, [searchParams]);

  const reviews = useInfiniteReviews(filters, 50);
  const items = reviews.data?.pages.flatMap((p) => p.items) ?? [];
  const total = reviews.data?.pages[0]?.total ?? 0;

  return (
    <main className="mx-auto w-full max-w-6xl space-y-6 px-4 py-8">
      <header className="space-y-2">
        <h1 className="text-2xl font-semibold">Analizler</h1>
        <p className="text-muted-foreground text-sm">
          {filters.batch_job_id ? (
            <>Belirli bir batch&apos;in analizleri gösteriliyor.</>
          ) : (
            <>Tenant&apos;ın analiz arşivi — manuel ve toplu giriş bir arada.</>
          )}{" "}
          {total > 0 && <span>Toplam {total} kayıt.</span>}
        </p>
      </header>

      <FilterPills filters={filters} />

      {reviews.isLoading ? (
        <div className="flex items-center gap-2 p-6 text-sm">
          <Loader2 className="size-4 animate-spin" /> Yükleniyor…
        </div>
      ) : items.length === 0 ? (
        <p className="text-muted-foreground p-6 text-sm">
          Bu filtrelerle eşleşen analiz yok.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Tarih</TableHead>
              <TableHead>Metin</TableHead>
              <TableHead>Duygu</TableHead>
              <TableHead className="hidden md:table-cell">Kategori</TableHead>
              <TableHead className="hidden text-center md:table-cell">OV</TableHead>
              <TableHead className="hidden md:table-cell">Bilet</TableHead>
              <TableHead className="hidden md:table-cell">Kaynak</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((r) => (
              <TableRow key={r.id} className="cursor-pointer">
                <TableCell className="text-muted-foreground text-xs">
                  {new Date(r.analyzed_at).toLocaleString("tr-TR")}
                </TableCell>
                <TableCell className="max-w-md">
                  <Link href={`/reviews/${r.id}`} className="hover:underline">
                    <span className="line-clamp-2 text-sm">{r.text}</span>
                  </Link>
                </TableCell>
                <TableCell>
                  <SentimentBadge label={r.sentiment_label} score={r.sentiment_score} />
                </TableCell>
                <TableCell className="hidden text-sm md:table-cell">
                  {r.primary_category}
                </TableCell>
                <TableCell className="hidden text-center md:table-cell">
                  {/* Override count chip — Sprint 8.3.4 makes it clickable. */}
                  <span className="text-muted-foreground text-xs">—</span>
                </TableCell>
                <TableCell className="hidden md:table-cell">
                  {r.ticket_id ? (
                    <Button
                      variant="link"
                      className="h-auto p-0"
                      render={<Link href={`/tickets/${r.ticket_id}`} />}
                    >
                      Görüntüle
                    </Button>
                  ) : (
                    <span className="text-muted-foreground text-xs">—</span>
                  )}
                </TableCell>
                <TableCell className="hidden text-sm md:table-cell">
                  {SOURCE_LABELS[r.source_type]}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {reviews.hasNextPage && (
        <div className="flex justify-center">
          <Button
            variant="outline"
            onClick={() => reviews.fetchNextPage()}
            disabled={reviews.isFetchingNextPage}
          >
            {reviews.isFetchingNextPage ? "Yükleniyor…" : "Daha fazla göster"}
          </Button>
        </div>
      )}
    </main>
  );
}

function FilterPills({ filters }: { filters: ReviewListFilters }) {
  const pills: { label: string; href: string }[] = [];
  if (filters.batch_job_id) {
    pills.push({
      label: `Batch: ${filters.batch_job_id.slice(0, 8)}…`,
      href: "/reviews",
    });
  }
  if (filters.sentiment_labels?.length) {
    pills.push({
      label: `Duygu: ${filters.sentiment_labels.join(", ")}`,
      href: "/reviews",
    });
  }
  if (filters.source_types?.length) {
    pills.push({
      label: `Kaynak: ${filters.source_types.map((t) => SOURCE_LABELS[t]).join(", ")}`,
      href: "/reviews",
    });
  }
  if (pills.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {pills.map((p) => (
        <Link
          key={p.label}
          href={p.href}
          className="bg-muted hover:bg-muted/80 inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs"
        >
          {p.label} <span aria-hidden>×</span>
        </Link>
      ))}
    </div>
  );
}

function SentimentBadge({ label, score }: { label: string; score: number }) {
  const tone = label === "NEGATIF" ? "danger" : label === "POZITIF" ? "success" : "default";
  return (
    <div className="flex flex-col items-start gap-0.5">
      <Badge
        className={cn(
          tone === "danger" && "bg-red-100 text-red-700",
          tone === "success" && "bg-emerald-100 text-emerald-700",
        )}
      >
        {label}
      </Badge>
      <span className="text-muted-foreground text-xs">{score.toFixed(2)}</span>
    </div>
  );
}
