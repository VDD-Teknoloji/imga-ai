// Sprint 13 — deneyim tipi (Dijital / Operasyonel) türetimi.
//
// Eski cx prototipinin "Experience Breakdown" kartlarının (F9) yeni
// mimarideki karşılığı. Analiz kararı (2026-05-03 eski-sistem-analizi,
// Kart F9): deneyim tipi primary category ile ortogonal değil —
// ayrı kolon yerine kategoriden türetilir.
//
//   dijital      : uygulama / site / online ödeme akışı sorunları
//   operasyonel  : fiziksel süreçler (kargo, iade, ürün, mağaza…)
//
// Tenant'a özel (custom) kategoriler eski prototiple aynı varsayılana
// düşer: operasyonel. 'belirsiz' hiçbir kovaya girmez.

export type ExperienceType = "dijital" | "operasyonel";

const DIGITAL_CODES: ReadonlySet<string> = new Set([
  "teknik_destek",
  "faturalama",
]);

export function experienceOf(categoryCode: string): ExperienceType | null {
  if (categoryCode === "belirsiz") return null;
  return DIGITAL_CODES.has(categoryCode) ? "dijital" : "operasyonel";
}
