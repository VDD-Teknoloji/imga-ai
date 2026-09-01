"use client";

// Sprint 12 — "Bu ayki önceliğiniz".
//
// C-level için en değerli tek satır: "ne yapmalıyım?" Son SWOT'un en
// yüksek öncelikli tavsiyesini gösterir. Taşındı: eskiden ana
// sayfada hero'nun hemen altındaydı; artık /action-items sayfasının
// en üstünde — kullanıcı zaten "ne yapmalıyım" niyetiyle o sayfaya
// geliyor, aksiyon listesiyle aynı yerde olması daha doğal. Tavsiye
// yoksa hiç render etmez (strateji bloğundaki onboarding CTA'sı o
// boşluğu zaten doldurur).

import { ArrowRight } from "lucide-react";
import Link from "next/link";

import type { ExecutiveSwotSnapshot } from "@/hooks/use-executive-overview";
import { useTranslation } from "@/lib/i18n/use-translation";

interface Props {
  swot: ExecutiveSwotSnapshot | null | undefined;
}

export function PriorityAction({ swot }: Props) {
  const { t } = useTranslation();
  const rec = swot?.top_recommendation;
  if (!rec) return null;

  return (
    <section className="rise-in shadow-soft bg-card ring-foreground/5 rounded-3xl p-6 ring-1 md:p-8">
      <h2 className="text-primary text-sm font-semibold">
        {t("actionItems.priority.title")}
      </h2>
      <p className="text-muted-foreground mt-1 text-sm">
        {t("actionItems.priority.desc")}
      </p>
      <p className="mt-3 text-xl font-semibold leading-snug tracking-tight md:text-2xl">
        {rec.title}
      </p>
      {rec.description && (
        <p className="text-muted-foreground mt-2 max-w-2xl text-sm leading-relaxed md:text-base">
          {rec.description}
        </p>
      )}
      <Link
        href="/strategy?tab=swot"
        className="text-foreground/70 hover:text-foreground mt-4 inline-flex items-center gap-1.5 text-sm font-semibold transition-colors"
      >
        {t("actionItems.priority.cta")}
        <ArrowRight className="size-4" aria-hidden />
      </Link>
    </section>
  );
}
