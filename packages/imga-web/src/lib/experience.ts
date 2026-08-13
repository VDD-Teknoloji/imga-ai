// Deneyim tipi (Dijital / Operasyonel).
//
// BİRİNCİL KAYNAK ARTIK BACKEND'DİR: sınıflandırma revizyonundan sonra
// her review satırı LLM'in doldurduğu `experience_type` kolonunu taşır.
// UI'da deneyim tipi okunacaksa o alan kullanılır — `effectiveExperience`
// bunu zaten yapar.
//
//   dijital      : uygulama / site / online ödeme akışı sorunları
//   operasyonel  : fiziksel süreçler (kargo, iade, ürün, mağaza…)

export type ExperienceType = "dijital" | "operasyonel";

const DIGITAL_CODES: ReadonlySet<string> = new Set([
  "teknik_destek",
  "faturalama",
]);

// AÇIK YEDEK — YALNIZCA `experience_type` taşımayan satırlar/uçlar için.
// Revizyon öncesi analiz edilmiş eski satırlarda alan null gelir; bu
// eski kategoriden-türetme kuralı onları bir kovaya düşürür. Yeni kod
// bunu doğrudan çağırmasın: `effectiveExperience` üzerinden geçin.
// Tenant'a özel (custom) kategoriler eski prototiple aynı varsayılana
// düşer: operasyonel. 'belirsiz' hiçbir kovaya girmez.
export function experienceOf(categoryCode: string): ExperienceType | null {
  if (categoryCode === "belirsiz") return null;
  return DIGITAL_CODES.has(categoryCode) ? "dijital" : "operasyonel";
}

/** Backend alanını tercih eder, yoksa eski kategori kuralına düşer.
 *  `experienceType` beklenmedik bir string taşırsa (şema kayması) yine
 *  yedeğe düşülür — sessizce geçersiz değer yüzeye çıkmasın. */
export function effectiveExperience(
  experienceType: string | null | undefined,
  categoryCode: string,
): ExperienceType | null {
  if (experienceType === "dijital" || experienceType === "operasyonel") {
    return experienceType;
  }
  return experienceOf(categoryCode);
}
