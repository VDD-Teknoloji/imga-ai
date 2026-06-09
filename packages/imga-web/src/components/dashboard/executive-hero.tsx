"use client";

// Sprint 10.0 — C-level hero: "Müşterileriniz ne söylüyor?"
//
// Tasarım ilkesi: çok net, çok büyük, çok anlaşılır, çok basit.
// Üç dev sayı (Pozitif / Nötr / Negatif) + tek parça oran barı +
// tek cümle Türkçe yorum. Yönetici 5 saniyede cevabını alır:
// müşterilerim ne hissediyor ve en büyük sorun ne.
//
// Veri: useExecutiveOverview (tek round-trip). Yüzde barı CSS
// width transition ile yumuşak açılır; sayılar tabular-nums ile
// hizalı. Boş tenant'ta yükleme CTA'sı gösterilir — demo akışında
// "ilk dosyanı yükle" satış anlatısının ilk adımı.

import { ArrowRight, Upload } from "lucide-react";
import Link from "next/link";

import { Skeleton } from "@/components/ui/skeleton";
import type { ExecutiveOverview } from "@/hooks/use-executive-overview";

interface Props {
  overview: ExecutiveOverview | undefined;
  isLoading: boolean;
}

function narrative(o: ExecutiveOverview): string {
  const { POZITIF, NEGATIF, total } = o.sentiment;
  if (total === 0) return "";
  const posPct = Math.round((POZITIF / total) * 100);
  const negPct = Math.round((NEGATIF / total) * 100);
  const parts: string[] = [];
  if (posPct >= 60) {
    parts.push(`Müşterilerinizin %${posPct}'i memnun.`);
  } else if (negPct >= 50) {
    parts.push(`Müşterilerinizin %${negPct}'i memnun değil — acil ilgi gerekiyor.`);
  } else if (negPct >= 25) {
    parts.push(`Müşterilerinizin %${negPct}'i olumsuz görüş bildirdi.`);
  } else {
    parts.push(`Müşterilerinizin %${posPct}'i memnun, genel görünüm dengeli.`);
  }
  if (o.top_negative_category) {
    parts.push(
      `En büyük şikayet konusu: ${o.top_negative_category.label} ` +
        `(${o.top_negative_category.count.toLocaleString("tr-TR")} yorum).`,
    );
  }
  return parts.join(" ");
}

export function ExecutiveHero({ overview, isLoading }: Props) {
  if (isLoading) return <Skeleton className="h-64 w-full rounded-2xl" />;
  if (!overview) return null;

  const { POZITIF, NEGATIF, total } = overview.sentiment;
  const NOTR = overview.sentiment["NÖTR"];

  if (total === 0) {
    return (
      <section className="rise-in shadow-elevated bg-card ring-foreground/5 rounded-3xl p-10 ring-1 text-center">
        <h2 className="text-2xl md:text-3xl font-semibold tracking-tight">
          Müşterilerinizin sesini dinlemeye başlayın
        </h2>
        <p className="text-muted-foreground mx-auto mt-3 max-w-xl text-sm md:text-base leading-relaxed">
          İlk yorum dosyanızı yükleyin — yapay zeka dakikalar içinde
          duygu analizini, kategorileri ve yönetici özetini hazırlasın.
        </p>
        <Link
          href="/analyze/upload"
          className="bg-gradient-to-br from-primary to-[oklch(0.55_0.22_290)] dark:to-[oklch(0.78_0.18_290)] text-primary-foreground shadow-glow mt-6 inline-flex items-center gap-2 rounded-xl px-6 py-3 text-sm font-semibold transition-transform hover:scale-[1.02]"
        >
          <Upload className="size-4" aria-hidden /> İlk dosyanızı yükleyin
        </Link>
      </section>
    );
  }

  const pct = (n: number) => (total > 0 ? (n / total) * 100 : 0);
  const text = narrative(overview);

  return (
    <section
      className="rise-in shadow-elevated bg-card ring-foreground/5 rounded-3xl p-6 md:p-10 ring-1"
      aria-label="Müşteri duygu özeti"
    >
      <p className="text-muted-foreground text-[11px] font-semibold uppercase tracking-[0.14em]">
        Tüm zamanlar · {total.toLocaleString("tr-TR")} yorum analiz edildi
      </p>
      <h2 className="mt-1 text-2xl md:text-4xl font-semibold tracking-tight">
        Müşterileriniz ne söylüyor?
      </h2>

      {/* Üç dev sayı — tasarım ilkesi: ÇOK BÜYÜK. */}
      <div className="mt-8 grid grid-cols-3 gap-4 md:gap-8">
        <BigStat
          label="Pozitif"
          value={POZITIF}
          colorClass="text-emerald-600 dark:text-emerald-400"
        />
        <BigStat
          label="Nötr"
          value={NOTR}
          colorClass="text-zinc-500 dark:text-zinc-400"
        />
        <BigStat
          label="Negatif"
          value={NEGATIF}
          colorClass="text-red-600 dark:text-red-400"
        />
      </div>

      {/* Tek parça oran barı — segment genişlikleri animate olur. */}
      <div
        className="mt-8 flex h-5 w-full overflow-hidden rounded-full ring-1 ring-border"
        role="img"
        aria-label={`Pozitif %${Math.round(pct(POZITIF))}, Nötr %${Math.round(pct(NOTR))}, Negatif %${Math.round(pct(NEGATIF))}`}
      >
        <div
          className="bg-emerald-500 transition-[width] duration-700 [transition-timing-function:var(--motion-ease)]"
          style={{ width: `${pct(POZITIF)}%` }}
        />
        <div
          className="bg-zinc-300 dark:bg-zinc-600 transition-[width] duration-700 [transition-timing-function:var(--motion-ease)]"
          style={{ width: `${pct(NOTR)}%` }}
        />
        <div
          className="bg-red-500 transition-[width] duration-700 [transition-timing-function:var(--motion-ease)]"
          style={{ width: `${pct(NEGATIF)}%` }}
        />
      </div>

      {/* Tek cümle Türkçe yorum — veri değil bilgi. */}
      {text && (
        <p className="text-foreground/85 mt-6 text-base md:text-xl leading-relaxed max-w-3xl">
          {text}
        </p>
      )}

      {overview.top_negative_category && (
        <Link
          href={`/reviews?primary_categories=${encodeURIComponent(overview.top_negative_category.code)}&sentiment_labels=NEGATİF`}
          className="text-primary mt-3 inline-flex items-center gap-1 text-sm font-semibold hover:underline"
        >
          {overview.top_negative_category.label} yorumlarını incele
          <ArrowRight className="size-4" aria-hidden />
        </Link>
      )}
    </section>
  );
}

function BigStat({
  label,
  value,
  colorClass,
}: {
  label: string;
  value: number;
  colorClass: string;
}) {
  return (
    <div className="text-center md:text-left">
      <p
        className={`text-4xl md:text-6xl font-semibold tabular-nums tracking-tight ${colorClass}`}
        style={{ letterSpacing: "-0.03em" }}
      >
        {value.toLocaleString("tr-TR")}
      </p>
      <p className="text-muted-foreground mt-1 text-xs md:text-sm font-medium uppercase tracking-wider">
        {label}
      </p>
    </div>
  );
}
