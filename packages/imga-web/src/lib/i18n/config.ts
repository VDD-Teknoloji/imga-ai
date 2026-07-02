/**
 * İmga i18n — dil yapılandırması (Sprint 12).
 *
 * Locale kurum-güdümlüdür: aktif kurumun `language` alanı UI + AI çıktı dilini
 * belirler (URL segmenti YOK). Kurum yokken (login/davet) pre-auth tercihi ya da
 * tarayıcı dili kullanılır. Şimdilik tr + en; yapı N-dile genişletilebilir.
 */

export const LOCALES = ["tr", "en"] as const;
export type Locale = (typeof LOCALES)[number];

export const DEFAULT_LOCALE: Locale = "tr";

export const LOCALE_LABELS: Record<Locale, string> = {
  tr: "Türkçe",
  en: "English",
};

export function isLocale(value: unknown): value is Locale {
  return value === "tr" || value === "en";
}

/** Serbest girdiyi güvenli bir Locale'e indir (bilinmeyen → varsayılan). */
export function normalizeLocale(value: unknown): Locale {
  return isLocale(value) ? value : DEFAULT_LOCALE;
}

/** Tarayıcı diline göre pre-auth varsayılanı (yalnız istemci). */
export function browserLocale(): Locale {
  if (typeof navigator !== "undefined") {
    const lang = navigator.language?.toLowerCase() ?? "";
    if (lang.startsWith("en")) return "en";
    if (lang.startsWith("tr")) return "tr";
  }
  return DEFAULT_LOCALE;
}
