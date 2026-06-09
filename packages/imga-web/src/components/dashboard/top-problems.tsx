"use client";

// Sprint 10.1 — Ana Sorunlar.
//
// Ürün sahibi feedback'i: "Direkt ana sorunlar gözüne çarpsın,
// C-level yöneticiyi harekete geçirsin." Bu blok hero'nun hemen
// altında oturur ve olumsuzluğun KAYNAĞINI sıralar:
//
//   01  İade / Değişim          25 yorum · olumsuzların %30'u
//       ████████████░░░░░░  (pay barı, kırmızı)
//       "İade sürecinde kimse dönüş yapmadı, üç haftadır..."
//
// Her satır: dev sıra numarası + kategori + pay barı + temsilî
// şikayet cümlesi + drilldown. Rakam ve müşteri sesi yan yana —
// yönetici hem ölçeği hem acıyı tek bakışta görür. Satır tıklaması
// /reviews drilldown'una gider; sağ üstte "Aksiyon planı oluştur"
// CTA'sı /strategy'ye götürür.
//
// Negatif yorum yoksa blok kendini gizler (sağlıklı tenant'ta
// kasvet yaratmasın); hero zaten "sağlıklı görünüm" der.

import { ArrowRight, Sparkles, TriangleAlert } from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import { useMounted } from "@/hooks/use-count-up";
import type { ExecutiveTopProblem } from "@/hooks/use-executive-overview";

interface Props {
  problems: ExecutiveTopProblem[] | undefined;
  isLoading: boolean;
}

export function TopProblems({ problems, isLoading }: Props) {
  // Pay barları açılışta sıfırdan dolar (width transition'ı mount
  // sonrası hedefe geçince oynar). Hook, early return'lardan ÖNCE.
  const mounted = useMounted();

  if (isLoading) {
    return (
      <section className="space-y-3">
        <Skeleton className="h-6 w-44" />
        <Skeleton className="h-56 w-full rounded-2xl" />
      </section>
    );
  }
  if (!problems || problems.length === 0) return null;

  const maxShare = Math.max(...problems.map((p) => p.share_pct), 1);

  return (
    <section aria-label="Ana sorunlar">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-red-500/20 to-red-500/5 text-red-600 ring-1 ring-red-500/25 dark:text-red-400">
            <TriangleAlert className="size-4" aria-hidden />
          </span>
          <div>
            <h2 className="text-lg md:text-2xl font-semibold tracking-tight">
              Ana Sorunlar
            </h2>
            <p className="text-muted-foreground text-xs md:text-sm">
              Müşterileriniz en çok bunlardan şikayetçi
            </p>
          </div>
        </div>
        <Link
          href="/strategy"
          className="text-primary inline-flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-semibold ring-1 ring-primary/25 transition-colors hover:bg-primary/5"
        >
          <Sparkles className="size-4" aria-hidden />
          Aksiyon planı oluştur
        </Link>
      </div>

      <div className="mt-4 space-y-3">
        {problems.map((p, idx) => (
          <Link
            key={p.code}
            href={`/reviews?primary_categories=${encodeURIComponent(p.code)}&sentiment_labels=NEGATIF`}
            style={{ animationDelay: `${idx * 70}ms` }}
            className="rise-in hover-lift shadow-soft group bg-card ring-foreground/5 flex items-start gap-4 rounded-2xl p-4 md:p-5 ring-1"
          >
            {/* Dev sıra numarası — göze çarpma noktası. */}
            <span
              className="text-3xl md:text-5xl font-bold tabular-nums leading-none text-red-600/25 dark:text-red-400/25 group-hover:text-red-600/45 dark:group-hover:text-red-400/45 transition-colors shrink-0 w-10 md:w-16"
              style={{ letterSpacing: "-0.04em" }}
              aria-hidden
            >
              {String(idx + 1).padStart(2, "0")}
            </span>

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <p className="text-base md:text-xl font-semibold tracking-tight">
                  {p.label}
                </p>
                <p className="text-muted-foreground text-xs md:text-sm tabular-nums">
                  <strong className="text-foreground">
                    {p.count.toLocaleString("tr-TR")}
                  </strong>{" "}
                  yorum · olumsuzların{" "}
                  <strong className="text-red-600 dark:text-red-400">
                    %{Math.round(p.share_pct)}
                  </strong>
                  &apos;i
                </p>
              </div>

              {/* Pay barı — en büyük sorun tam genişlik, diğerleri
                  ona oranlı. Göreli büyüklük tek bakışta okunur. */}
              <div className="mt-2.5 h-2 w-full overflow-hidden rounded-full bg-red-500/10">
                <div
                  className="h-2 rounded-full bg-gradient-to-r from-red-500 to-red-400 transition-[width] duration-700 [transition-timing-function:var(--motion-ease)]"
                  style={{ width: mounted ? `${(p.share_pct / maxShare) * 100}%` : "0%" }}
                />
              </div>

              {p.sample_text && (
                <p
                  className="text-muted-foreground mt-2.5 line-clamp-2 text-sm italic leading-relaxed [overflow-wrap:anywhere]"
                  title={p.sample_text}
                >
                  &ldquo;{p.sample_text}&rdquo;
                </p>
              )}
            </div>

            <ArrowRight
              className="text-muted-foreground/50 group-hover:text-red-600 dark:group-hover:text-red-400 mt-1 size-5 shrink-0 transition-colors"
              aria-hidden
            />
          </Link>
        ))}
      </div>
    </section>
  );
}
