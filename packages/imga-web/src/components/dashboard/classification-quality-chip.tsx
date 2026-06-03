"use client";

// Sprint 9.9 — Madde 1 (UML feedback): "Bu kadar fazla belirsiz yorum
// olmamalı". Test ekranında kategori dağılımı 'belirsiz' satırı 3262
// yorumla en üstte gelmişti. Bunun gerçek çözümü LLM prompt revize
// + kategori lexicon genişletme (ayrı sprint) ama operatöre AYNI
// DASHBOARD'DA görsel sinyal vermek, sorunu fark etmesini sağlar.
//
// Bu chip:
//   * Belirsiz / toplam oran ≤ %15 → mavi "iyi" → sessiz
//   * %15 < oran ≤ %30 → sarı "iyileştirilebilir"
//   * %30 < oran → kırmızı "düşük"
//   + Tıklandığında /insights?tab=category sayfasına gider, operatör
//     hangi kategorilerin "kaybolduğunu" görür.

import { AlertTriangle, ArrowRight, CheckCircle2, Sparkles } from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import { useCategoryDistribution } from "@/hooks/use-analytics";

type QualityBand = "good" | "watch" | "low";

interface BandVisual {
  band: QualityBand;
  container: string;
  iconWrap: string;
  text: string;
  label: string;
  Icon: typeof AlertTriangle;
}

function bandFor(ratio: number): BandVisual {
  if (ratio <= 0.15) {
    return {
      band: "good",
      container:
        "border-emerald-200/70 bg-gradient-to-br from-emerald-50/80 to-card dark:from-emerald-950/25 dark:to-card",
      iconWrap:
        "from-emerald-500/20 to-emerald-500/5 ring-emerald-500/25 text-emerald-700 dark:text-emerald-300",
      text: "text-emerald-800 dark:text-emerald-300",
      label: "İyi",
      Icon: CheckCircle2,
    };
  }
  if (ratio <= 0.3) {
    return {
      band: "watch",
      container:
        "border-amber-200/70 bg-gradient-to-br from-amber-50/80 to-card dark:from-amber-950/25 dark:to-card",
      iconWrap:
        "from-amber-500/20 to-amber-500/5 ring-amber-500/25 text-amber-700 dark:text-amber-300",
      text: "text-amber-800 dark:text-amber-300",
      label: "İyileştirilebilir",
      Icon: Sparkles,
    };
  }
  return {
    band: "low",
    container:
      "border-red-200/70 bg-gradient-to-br from-red-50/80 to-card dark:from-red-950/25 dark:to-card",
    iconWrap:
      "from-red-500/20 to-red-500/5 ring-red-500/25 text-red-700 dark:text-red-300",
    text: "text-red-800 dark:text-red-300",
    label: "Düşük",
    Icon: AlertTriangle,
  };
}

function copyFor(ratio: number, belirsizCount: number, totalCount: number): {
  headline: string;
  hint: string;
} {
  const pct = Math.round(ratio * 100);
  if (ratio <= 0.15) {
    return {
      headline: `Sınıflandırma kalitesi: %${100 - pct} eşleşme`,
      hint: "Yorumların çoğu doğru kategoriye düştü.",
    };
  }
  if (ratio <= 0.3) {
    return {
      headline: `${belirsizCount.toLocaleString(
        "tr-TR",
      )} yorum 'belirsiz' (%${pct})`,
      hint:
        "Çok kısa veya bağlamsız yorumlar genellikle 'belirsiz'e düşer. " +
        "Özel kategori eklemek oranı iyileştirir.",
    };
  }
  return {
    headline: `${belirsizCount.toLocaleString(
      "tr-TR",
    )} yorum 'belirsiz' (%${pct})`,
    hint:
      "Belirsiz oranı yüksek. /Ayarlar/Kategoriler menüsünden özel " +
      `kategoriler ekleyerek ${totalCount.toLocaleString(
        "tr-TR",
      )} yorumun daha büyük kısmını doğru sınıflandırabilirsiniz.`,
  };
}

export function ClassificationQualityChip() {
  const dist = useCategoryDistribution({}, 50);

  if (dist.isLoading) {
    return <Skeleton className="h-20 w-full rounded-2xl" />;
  }
  // Sessizlik kazanımı: veri yoksa veya henüz analizlenmiş yorum
  // yoksa chip rendering yapmıyoruz — boş bir uyarı kart kasvet
  // yaratır.
  if (dist.isError || !dist.data || dist.data.total === 0) {
    return null;
  }

  const belirsizRow = dist.data.data.find((r) => r.category === "belirsiz");
  const belirsizCount = belirsizRow?.count ?? 0;
  const total = dist.data.total;
  const ratio = total > 0 ? belirsizCount / total : 0;

  // İyi banttayken ve belirsiz hiç yoksa chip'i de sessizleştir —
  // dashboard'a gereksiz yer kaplamasın.
  if (ratio <= 0.05) {
    return null;
  }

  const visual = bandFor(ratio);
  const text = copyFor(ratio, belirsizCount, total);

  return (
    <Link
      href="/insights?tab=category"
      className={`rise-in shadow-soft hover:shadow-elevated group flex items-center gap-4 rounded-2xl border p-4 transition-shadow ${visual.container}`}
      aria-label="Sınıflandırma kalite uyarısı"
    >
      <span
        className={`flex size-10 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ring-1 ${visual.iconWrap}`}
      >
        <visual.Icon className="size-5" aria-hidden />
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <p className="text-sm font-semibold">{text.headline}</p>
          <span
            className={`text-[10px] font-semibold uppercase tracking-[0.14em] ${visual.text}`}
          >
            {visual.label}
          </span>
        </div>
        <p className="text-muted-foreground mt-1 text-xs leading-relaxed">
          {text.hint}
        </p>
      </div>
      <ArrowRight
        className="text-muted-foreground/60 group-hover:text-foreground size-4 shrink-0 transition-colors"
        aria-hidden
      />
    </Link>
  );
}
