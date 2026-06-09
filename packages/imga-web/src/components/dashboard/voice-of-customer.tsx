"use client";

// Sprint 10.0 — Müşterinin Sesi.
//
// "Veri değil, bilgi görünsün" ilkesinin taşıyıcısı: yönetici
// rakam yerine müşterisinin gerçek cümlesini okur. Backend en
// etkili 2 negatif + 1 pozitif yorumu seçer (≥40 karakter,
// near-duplicate elenmiş). Büyük alıntı tipografisi + duygu
// renginde sol şerit + kategori chip + göreli zaman.
// Tıklama → /reviews drilldown (aynı kategori + duygu).

import { ArrowRight, Quote } from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import type { ExecutiveQuote } from "@/hooks/use-executive-overview";
import { formatDateTr, relativeTimeTr } from "@/lib/relative-time";

const SENTIMENT_ACCENT: Record<string, string> = {
  NEGATIF: "border-l-red-500",
  POZITIF: "border-l-emerald-500",
  "NÖTR": "border-l-zinc-400",
};

const SENTIMENT_CHIP: Record<string, string> = {
  NEGATIF: "bg-red-50 text-red-700 ring-red-200 dark:bg-red-950/40 dark:text-red-300 dark:ring-red-900",
  POZITIF: "bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:ring-emerald-900",
  "NÖTR": "bg-zinc-100 text-zinc-700 ring-zinc-200 dark:bg-zinc-900 dark:text-zinc-300 dark:ring-zinc-700",
};

const SENTIMENT_TR: Record<string, string> = {
  NEGATIF: "Olumsuz",
  POZITIF: "Olumlu",
  "NÖTR": "Nötr",
};

interface Props {
  quotes: ExecutiveQuote[] | undefined;
  isLoading: boolean;
}

export function VoiceOfCustomer({ quotes, isLoading }: Props) {
  if (isLoading) {
    return (
      <section className="space-y-3">
        <Skeleton className="h-6 w-48" />
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-44 rounded-2xl" />
          ))}
        </div>
      </section>
    );
  }
  if (!quotes || quotes.length === 0) return null;

  return (
    <section aria-label="Müşterinin sesi">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-lg md:text-2xl font-semibold tracking-tight">
          Müşterinin Sesi
        </h2>
        <Link
          href="/reviews"
          className="text-primary inline-flex items-center gap-1 text-sm font-semibold hover:underline"
        >
          Tüm yorumlar
          <ArrowRight className="size-4" aria-hidden />
        </Link>
      </div>
      <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-3">
        {quotes.map((q, idx) => (
          <Link
            key={q.id}
            href={`/reviews?primary_categories=${encodeURIComponent(q.category_code)}&sentiment_labels=${encodeURIComponent(q.sentiment_label)}`}
            style={{ animationDelay: `${idx * 60}ms` }}
            className={`rise-in hover-lift shadow-soft bg-card ring-foreground/5 flex flex-col rounded-2xl border-l-4 p-5 ring-1 ${SENTIMENT_ACCENT[q.sentiment_label] ?? "border-l-zinc-300"}`}
          >
            <Quote
              className="text-muted-foreground/30 size-6 shrink-0"
              aria-hidden
            />
            <p className="mt-2 flex-1 text-sm md:text-base leading-relaxed text-foreground/90 [overflow-wrap:anywhere]">
              &ldquo;{q.text}&rdquo;
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
              <span
                className={`inline-flex items-center rounded-full px-2 py-0.5 font-semibold ring-1 ${SENTIMENT_CHIP[q.sentiment_label] ?? ""}`}
              >
                {SENTIMENT_TR[q.sentiment_label] ?? q.sentiment_label}
              </span>
              <span className="bg-muted text-muted-foreground inline-flex items-center rounded-full px-2 py-0.5 font-medium">
                {q.category_label}
              </span>
              <span
                className="text-muted-foreground ml-auto"
                title={formatDateTr(q.analyzed_at)}
              >
                {relativeTimeTr(q.analyzed_at)}
              </span>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
