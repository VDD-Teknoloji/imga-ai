// Müşteri yolculuğu aşaması (migration 0052) — yorum başına LLM kararı.
//
// Tek kaynak backend'dir (`imga_core.journey.JOURNEY_STAGES`); buradaki
// liste onunla birebir aynı HUNİ SIRASINDADIR ve her yüzey (dashboard
// hunisi, /reviews filtresi + rozeti, özet paneli, /churn ağaç/harita)
// sırayı buradan alır. Aşama kategoriden ya da duygudan TÜRETİLMEZ —
// frontend hiçbir yedek kural uygulamaz; alan null ise "atanmamış".

export const JOURNEY_STAGES = [
  "kesif",
  "degerlendirme",
  "satin_alma",
  "teslimat",
  "kullanim",
  "destek",
  "sadakat",
  "ayrilma",
] as const;

export type JourneyStage = (typeof JOURNEY_STAGES)[number];

/** URL/filtre sözlüğü: gerçek kodlar + "atanmamis" (journey_stage IS NULL). */
export const JOURNEY_FILTER_VALUES = [...JOURNEY_STAGES, "atanmamis"] as const;
export type JourneyFilterValue = (typeof JOURNEY_FILTER_VALUES)[number];

const STAGE_SET: ReadonlySet<string> = new Set(JOURNEY_STAGES);

export function isJourneyStage(value: string | null | undefined): value is JourneyStage {
  return typeof value === "string" && STAGE_SET.has(value);
}

/** i18n anahtarı — insights.ts `reviews.journey.*` (atanmamis dahil).
 *  Bilinmeyen kod (şema kayması) ham string olarak geri döner. */
export function journeyLabelKey(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "reviews.journey.atanmamis";
  return isJourneyStage(value) || value === "atanmamis" ? `reviews.journey.${value}` : value;
}

/** Satın alma öncesi (henüz müşteri değil) aşamalar — dashboard huni
 *  başlığındaki "potansiyel" payı için. */
export const PRE_PURCHASE_STAGES: ReadonlySet<JourneyStage> = new Set(["kesif", "degerlendirme"]);
