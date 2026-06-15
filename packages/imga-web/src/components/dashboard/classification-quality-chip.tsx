"use client";

// Sprint 9.9 / 12 — sınıflandırma kalite sinyali (sakin sürüm).
//
// 'belirsiz' oranı yükselince operatöre AYNI dashboard'da görünür
// uyarı verir. Sakinleştirildi: gradient kutular + sparkle ikon
// kaldırıldı; aydınlık kart + tek renkli durum noktası. Sessizlik
// kazanımı korunur: oran düşükse hiç render etmez.
//
//   * ≤ %15 → "iyi" (genelde sessiz)
//   * %15 < oran ≤ %30 → "iyileştirilebilir"
//   * %30 < oran → "düşük"
//   Tıklanınca /insights?tab=category — hangi kategoriler kayıp.

import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import { useCategoryDistribution } from "@/hooks/use-analytics";

type QualityBand = "good" | "watch" | "low";

interface BandVisual {
  band: QualityBand;
  dotClass: string;
  labelClass: string;
  label: string;
}

function bandFor(ratio: number): BandVisual {
  if (ratio <= 0.15) {
    return {
      band: "good",
      dotClass: "bg-emerald-500",
      labelClass: "text-emerald-700 dark:text-emerald-400",
      label: "İyi",
    };
  }
  if (ratio <= 0.3) {
    return {
      band: "watch",
      dotClass: "bg-amber-500",
      labelClass: "text-amber-700 dark:text-amber-400",
      label: "İyileştirilebilir",
    };
  }
  return {
    band: "low",
    dotClass: "bg-red-500",
    labelClass: "text-red-700 dark:text-red-400",
    label: "Düşük",
  };
}

function copyFor(
  ratio: number,
  belirsizCount: number,
  totalCount: number,
): { headline: string; hint: string } {
  const pct = Math.round(ratio * 100);
  if (ratio <= 0.15) {
    return {
      headline: `Sınıflandırma kalitesi: %${100 - pct} eşleşme`,
      hint: "Yorumların çoğu doğru kategoriye düştü.",
    };
  }
  if (ratio <= 0.3) {
    return {
      headline: `${belirsizCount.toLocaleString("tr-TR")} yorum 'belirsiz' (%${pct})`,
      hint:
        "Çok kısa veya bağlamsız yorumlar genellikle 'belirsiz'e düşer. " +
        "Özel kategori eklemek oranı iyileştirir.",
    };
  }
  return {
    headline: `${belirsizCount.toLocaleString("tr-TR")} yorum 'belirsiz' (%${pct})`,
    hint:
      "Belirsiz oranı yüksek. Ayarlar / Kategoriler menüsünden özel " +
      `kategoriler ekleyerek ${totalCount.toLocaleString("tr-TR")} yorumun daha büyük kısmını doğru sınıflandırabilirsiniz.`,
  };
}

export function ClassificationQualityChip() {
  const dist = useCategoryDistribution({}, 50);

  if (dist.isLoading) {
    return <Skeleton className="h-20 w-full rounded-3xl" />;
  }
  if (dist.isError || !dist.data || dist.data.total === 0) {
    return null;
  }

  const belirsizRow = dist.data.data.find((r) => r.category === "belirsiz");
  const belirsizCount = belirsizRow?.count ?? 0;
  const total = dist.data.total;
  const ratio = total > 0 ? belirsizCount / total : 0;

  // İyi banttayken ve belirsiz neredeyse yoksa sessizleş.
  if (ratio <= 0.05) {
    return null;
  }

  const visual = bandFor(ratio);
  const text = copyFor(ratio, belirsizCount, total);

  return (
    <Link
      href="/insights?tab=category"
      className="rise-in hover-lift shadow-soft group bg-card ring-foreground/5 flex items-start gap-3.5 rounded-3xl p-5 ring-1"
      aria-label="Sınıflandırma kalite uyarısı"
    >
      <span
        className={`mt-1.5 size-2.5 shrink-0 rounded-full ${visual.dotClass}`}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm font-semibold">{text.headline}</p>
          <span className={`text-xs font-semibold ${visual.labelClass}`}>
            {visual.label}
          </span>
        </div>
        <p className="text-muted-foreground mt-1 text-sm leading-relaxed">
          {text.hint}
        </p>
      </div>
      <ArrowRight
        className="text-muted-foreground/40 group-hover:text-foreground mt-0.5 size-4 shrink-0 transition-colors"
        aria-hidden
      />
    </Link>
  );
}
