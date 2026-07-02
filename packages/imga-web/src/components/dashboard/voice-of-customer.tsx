"use client";

// Sprint 12 — Müşterinin Sesi.
//
// "Veri değil, bilgi" ilkesinin taşıyıcısı: yönetici rakam yerine
// müşterisinin gerçek cümlesini okur. Backend en etkili 2 negatif +
// 1 pozitif yorumu seçer (≥40 karakter, near-duplicate elenmiş).
// Sakinleştirildi: büyük alıntı tipografisi, duygu renginde ince
// sol şerit, tek sade duygu rozeti. Tıklama → /reviews drilldown.

import Link from "next/link";

import { SectionHeading } from "@/components/dashboard/section-heading";
import { Skeleton } from "@/components/ui/skeleton";
import type { ExecutiveQuote } from "@/hooks/use-executive-overview";
import { useTranslation } from "@/lib/i18n/use-translation";
import { formatDateTr, relativeTimeTr } from "@/lib/relative-time";

const SENTIMENT_ACCENT: Record<string, string> = {
  NEGATIF: "border-l-red-400",
  POZITIF: "border-l-emerald-400",
  "NÖTR": "border-l-zinc-300",
};

const SENTIMENT_CHIP: Record<string, string> = {
  NEGATIF: "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300",
  POZITIF:
    "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300",
  "NÖTR": "bg-zinc-100 text-zinc-600 dark:bg-zinc-900 dark:text-zinc-300",
};

const SENTIMENT_LABEL_KEYS: Record<string, string> = {
  NEGATIF: "dashboard.voiceOfCustomer.sentiment.negative",
  POZITIF: "dashboard.voiceOfCustomer.sentiment.positive",
  "NÖTR": "dashboard.voiceOfCustomer.sentiment.neutral",
};

interface Props {
  quotes: ExecutiveQuote[] | undefined;
  isLoading: boolean;
}

export function VoiceOfCustomer({ quotes, isLoading }: Props) {
  const { t } = useTranslation();
  if (isLoading) {
    return (
      <section className="space-y-4">
        <Skeleton className="h-7 w-48" />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-44 rounded-3xl" />
          ))}
        </div>
      </section>
    );
  }
  if (!quotes || quotes.length === 0) return null;

  return (
    <section aria-label={t("dashboard.voiceOfCustomer.aria")}>
      <SectionHeading
        title={t("dashboard.voiceOfCustomer.title")}
        description={t("dashboard.voiceOfCustomer.description")}
        action={{ href: "/reviews", label: t("dashboard.voiceOfCustomer.action") }}
      />
      <div className="mt-5 grid grid-cols-1 gap-4 md:grid-cols-3">
        {quotes.map((q, idx) => {
          const sentimentKey = SENTIMENT_LABEL_KEYS[q.sentiment_label];
          return (
          <Link
            key={q.id}
            href={`/reviews?primary_categories=${encodeURIComponent(q.category_code)}&sentiment_labels=${encodeURIComponent(q.sentiment_label)}`}
            style={{ animationDelay: `${idx * 60}ms` }}
            className={`rise-in hover-lift shadow-soft bg-card ring-foreground/5 flex flex-col rounded-3xl border-l-2 p-5 ring-1 md:p-6 ${SENTIMENT_ACCENT[q.sentiment_label] ?? "border-l-zinc-300"}`}
          >
            <p className="text-foreground/90 flex-1 text-base leading-relaxed [overflow-wrap:anywhere] md:text-lg">
              &ldquo;{q.text}&rdquo;
            </p>
            <div className="mt-5 flex flex-wrap items-center gap-2 text-xs">
              <span
                className={`inline-flex items-center rounded-full px-2.5 py-1 font-semibold ${SENTIMENT_CHIP[q.sentiment_label] ?? ""}`}
              >
                {sentimentKey ? t(sentimentKey) : q.sentiment_label}
              </span>
              <span className="text-muted-foreground font-medium">
                {q.category_label}
              </span>
              <span
                className="text-muted-foreground/70 ml-auto"
                title={formatDateTr(q.analyzed_at)}
              >
                {relativeTimeTr(q.analyzed_at)}
              </span>
            </div>
          </Link>
          );
        })}
      </div>
    </section>
  );
}
