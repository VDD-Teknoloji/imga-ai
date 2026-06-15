"use client";

// Sprint 12 — "Bu ayki önceliğiniz".
//
// C-level için en değerli tek satır: "ne yapmalıyım?" Son SWOT'un
// en yüksek öncelikli tavsiyesini hero'nun hemen altında sakin bir
// çağrı olarak gösterir — yönetici durumu (hero) okur, sonra tek
// bir net adım görür. Tavsiye yoksa hiç render etmez (strateji
// bloğundaki onboarding CTA'sı o boşluğu zaten doldurur).

import { ArrowRight } from "lucide-react";
import Link from "next/link";

import type { ExecutiveSwotSnapshot } from "@/hooks/use-executive-overview";

interface Props {
  swot: ExecutiveSwotSnapshot | null | undefined;
}

export function PriorityAction({ swot }: Props) {
  const rec = swot?.top_recommendation;
  if (!rec) return null;

  return (
    <Link
      href="/strategy"
      className="rise-in hover-lift shadow-soft group bg-card ring-foreground/5 block rounded-3xl p-6 ring-1 md:p-8"
      style={{ animationDelay: "60ms" }}
    >
      <p className="text-primary text-sm font-semibold">Bu ayki önceliğiniz</p>
      <p className="mt-2 text-xl font-semibold leading-snug tracking-tight md:text-2xl">
        {rec.title}
      </p>
      {rec.description && (
        <p className="text-muted-foreground mt-2 max-w-2xl text-sm leading-relaxed md:text-base">
          {rec.description}
        </p>
      )}
      <span className="text-foreground/70 group-hover:text-foreground mt-4 inline-flex items-center gap-1.5 text-sm font-semibold transition-colors">
        Aksiyon planının tamamını gör
        <ArrowRight className="size-4" aria-hidden />
      </span>
    </Link>
  );
}
