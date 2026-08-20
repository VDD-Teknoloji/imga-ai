// Katılım bandı rozeti — /admin/tenants tablosu (C3/B7 envanteri).
//
// Backend `engagement_band` (bkz. tenant_service.py TenantListRow /
// engagement_service.resolve_band) her kurumun KENDİ bantlarından
// çözülmüş SERBEST METİN etikettir — sabit bir enum değil, süper
// yönetici her kurum için farklı etiketler tanımlayabilir
// (TenantEngagementDialog). Renk deseni confidence-badge.tsx /
// classification-quality-chip.tsx'teki emerald/amber/red 3-tonlu "band"
// yaklaşımının anahtar-kelime tabanlı bir uyarlaması: bilinen Türkçe
// kelimeler (DEFAULT_BANDS sözlüğü: Çok Kötü/Kötü/Orta/Çok İyi) tona
// düşer, tanınmayan özel etiketler settings/engagement sayfasındaki
// nötr `secondary` rozetine düşer — bilgi kaybı yerine zararsız
// varsayılan.

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type EngagementTone = "good" | "watch" | "bad" | "neutral";

const BAD_KEYWORDS = ["kötü", "zayıf", "düşük", "kritik", "riskli", "yetersiz"];
const GOOD_KEYWORDS = ["iyi", "yüksek", "mükemmel", "harika", "güçlü"];
const WATCH_KEYWORDS = ["orta", "ortalama", "normal", "vasat"];

function toneForLabel(label: string): EngagementTone {
  // "İ".toLowerCase() -> "i̇" (nokta birleşik karakter, plain ASCII
  // "i" değil) — .includes() eşleşmesini sessizce kırar. Locale'li
  // katlama (toLocaleLowerCase("tr")) "İyi" -> "iyi" doğru dönüşümü
  // garanti eder.
  const normalized = label.toLocaleLowerCase("tr");
  if (BAD_KEYWORDS.some((k) => normalized.includes(k))) return "bad";
  if (GOOD_KEYWORDS.some((k) => normalized.includes(k))) return "good";
  if (WATCH_KEYWORDS.some((k) => normalized.includes(k))) return "watch";
  return "neutral";
}

const TONE_CLASSES: Record<Exclude<EngagementTone, "neutral">, string> = {
  good: "border-emerald-300 bg-emerald-50 text-emerald-800",
  watch: "border-amber-300 bg-amber-50 text-amber-800",
  bad: "border-red-300 bg-red-50 text-red-800",
};

export function EngagementBandBadge({ band }: { band: string | null | undefined }) {
  if (!band) {
    return <span className="text-muted-foreground text-xs">—</span>;
  }
  const tone = toneForLabel(band);
  if (tone === "neutral") {
    return (
      <Badge variant="secondary" className="text-xs">
        {band}
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className={cn("text-xs", TONE_CLASSES[tone])}>
      {band}
    </Badge>
  );
}
