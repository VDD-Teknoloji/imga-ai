"use client";

// Sprint 12 — En çok şikayet edilen konular (eski "Ana Sorunlar").
//
// Sakinleştirildi: kırmızı glow kutu + dev kırmızı sıra numarası +
// kırmızı gradient bar "korkutucu" bulunuyordu. Yeni hali aydınlık
// ve ölçülü — renk yalnızca pay barında, anlamı taşıyacak kadar.
// Yapı korunuyor: her satır sıra + kategori + plain dildeki ölçek
// cümlesi + temsilî şikayet + drilldown. Negatif yoksa gizlenir.

import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { SectionHeading } from "@/components/dashboard/section-heading";
import { Skeleton } from "@/components/ui/skeleton";
import { useMounted } from "@/hooks/use-count-up";
import type { ExecutiveTopProblem } from "@/hooks/use-executive-overview";

interface Props {
  problems: ExecutiveTopProblem[] | undefined;
  isLoading: boolean;
}

export function TopProblems({ problems, isLoading }: Props) {
  // Pay barları açılışta sıfırdan dolar. Hook early-return'lardan ÖNCE.
  const mounted = useMounted();

  if (isLoading) {
    return (
      <section className="space-y-4">
        <Skeleton className="h-7 w-56" />
        <Skeleton className="h-52 w-full rounded-3xl" />
      </section>
    );
  }
  if (!problems || problems.length === 0) return null;

  const maxShare = Math.max(...problems.map((p) => p.share_pct), 1);

  return (
    <section aria-label="En çok şikayet edilen konular">
      <SectionHeading
        title="En çok şikayet edilen konular"
        description="Müşterileriniz en çok bunlardan şikayetçi"
        action={{ href: "/strategy", label: "Aksiyon planı" }}
      />

      <div className="mt-5 space-y-3">
        {problems.map((p, idx) => (
          <Link
            key={p.code}
            href={`/reviews?primary_categories=${encodeURIComponent(p.code)}&sentiment_labels=NEGATIF`}
            style={{ animationDelay: `${idx * 70}ms` }}
            className="rise-in hover-lift shadow-soft group bg-card ring-foreground/5 flex items-start gap-4 rounded-3xl p-5 ring-1 md:gap-5 md:p-6"
          >
            <span
              className="text-muted-foreground/40 w-8 shrink-0 text-2xl font-semibold tabular-nums leading-none md:w-10 md:text-3xl"
              aria-hidden
            >
              {idx + 1}
            </span>

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <p className="text-lg font-semibold tracking-tight md:text-xl">
                  {p.label}
                </p>
                <p className="text-muted-foreground text-sm tabular-nums">
                  <strong className="text-foreground font-semibold">
                    {p.count.toLocaleString("tr-TR")}
                  </strong>{" "}
                  olumsuz yorum · şikayetlerin %{Math.round(p.share_pct)}&apos;i
                </p>
              </div>

              {/* Pay barı — tek bakışta göreli büyüklük. Ölçülü kırmızı. */}
              <div className="bg-muted mt-3 h-1.5 w-full overflow-hidden rounded-full">
                <div
                  className="h-full rounded-full bg-red-400 transition-[width] duration-700 [transition-timing-function:var(--motion-ease)] dark:bg-red-500"
                  style={{
                    width: mounted ? `${(p.share_pct / maxShare) * 100}%` : "0%",
                  }}
                />
              </div>

              {p.sample_text && (
                <p
                  className="text-muted-foreground mt-3 line-clamp-2 text-sm leading-relaxed [overflow-wrap:anywhere]"
                  title={p.sample_text}
                >
                  &ldquo;{p.sample_text}&rdquo;
                </p>
              )}
            </div>

            <ArrowRight
              className="text-muted-foreground/40 group-hover:text-foreground mt-1 size-5 shrink-0 transition-colors"
              aria-hidden
            />
          </Link>
        ))}
      </div>
    </section>
  );
}
