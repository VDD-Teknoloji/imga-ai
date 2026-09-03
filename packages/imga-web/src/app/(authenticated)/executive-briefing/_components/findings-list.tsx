"use client";

// 2026-09-03 redesign — kritik içgörüler ikonlu tek satır liste.
//
// Eski sürüm `critical_insights`'ı çıplak `<ul className="list-disc">`
// olarak basıyordu — her satır uzun bir cümle, hepsi açık. Yeni sürüm
// her satırı TEK satıra kısaltır (line-clamp-1), tam metin tıklanınca
// açılır (görev talimatı: "detay bir tıklama arkasında"). Veri hiçbir
// duygu/ton alanı taşımıyor — ikon seçimi metindeki artış/azalış
// kelimelerine bakan bir SEZGİ, gerçek bir sınıflandırma değil. Bu
// yüzden ton HER ZAMAN amber/muted kalır (advisor notu: yön ≠ değer;
// "şikayetler arttı" TrendingUp eşleşir ama bu iyi bir haber değildir —
// yeşil/kırmızı boyamak yanlış bilgi verir, ikon farkı yeterli).

import { useState } from "react";
import { CircleAlert, TrendingDown, TrendingUp, type LucideIcon } from "lucide-react";

import { SectionHeading } from "@/components/dashboard/section-heading";
import { useTranslation } from "@/lib/i18n/use-translation";

type TrendTone = "up" | "down" | "flat";

const TREND_ICONS: Readonly<Record<TrendTone, LucideIcon>> = {
  up: TrendingUp,
  down: TrendingDown,
  flat: CircleAlert,
};

const UP_WORDS = ["art", "yüksel", "çoğal", "büyü"];
const DOWN_WORDS = ["azal", "düş", "geril", "küçül"];

/** Salt ikon seçimi için sezgi — bkz. dosya üstü not. */
function trendToneFor(text: string): TrendTone {
  const lower = text.toLocaleLowerCase("tr-TR");
  if (UP_WORDS.some((w) => lower.includes(w))) return "up";
  if (DOWN_WORDS.some((w) => lower.includes(w))) return "down";
  return "flat";
}

function FindingRow({ text, index }: { text: string; index: number }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const Icon = TREND_ICONS[trendToneFor(text)];
  return (
    <li className="rise-in flex items-start gap-2.5" style={{ animationDelay: `${index * 50}ms` }}>
      <span className="mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-400">
        <Icon className="size-3.5" aria-hidden />
      </span>
      <div className="min-w-0">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className={`text-left text-sm leading-relaxed ${expanded ? "" : "line-clamp-1"}`}
        >
          {text}
        </button>
        {!expanded && (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="text-muted-foreground hover:text-foreground block text-xs font-medium transition-colors"
          >
            {t("briefing.findings.showMore")}
          </button>
        )}
        {expanded && (
          <button
            type="button"
            onClick={() => setExpanded(false)}
            className="text-muted-foreground hover:text-foreground mt-0.5 block text-xs font-medium transition-colors"
          >
            {t("briefing.findings.showLess")}
          </button>
        )}
      </div>
    </li>
  );
}

export function FindingsList({ insights }: { insights: string[] }) {
  const { t } = useTranslation();
  // Sessizlik kuralı: hiç içgörü yoksa bölüm hiç çizilmez.
  if (insights.length === 0) return null;
  return (
    <section aria-label={t("briefing.findings.title")}>
      <SectionHeading title={t("briefing.findings.title")} icon={CircleAlert} />
      <ul className="mt-4 space-y-3">
        {insights.map((text, idx) => (
          <FindingRow key={`${text.slice(0, 24)}-${idx}`} text={text} index={idx} />
        ))}
      </ul>
    </section>
  );
}
