// KVKK (2026-09-02) — kanıt alıntıları için görüntüleme-anı emniyet ağı.
//
// Asıl maske sunucuda: prompt kişi adlarını "[ad]" yazar, api tarafındaki
// services/pii_mask.py e-posta/telefon/TCKN/IBAN'ı yakalar ve kalıcı
// payload'a öyle yazar. Bu dosya (1) maske öncesi üretilmiş eski
// analizlerin alıntılarında hâlâ duran e-posta/telefon/IBAN'ı ekranda
// gizler, (2) sabit Türkçe yer tutucuları arayüz diline çevirir. Ad
// tespiti burada YOK — regex ile ad yakalamak alıntıyı bozar; eski
// analizler yeniden üretimle temizlenir.

import type { Locale } from "@/lib/i18n/config";

const EMAIL_RE = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g;
const TR_PHONE_RE =
  /(?<!\d)(?:\+\s?90|00\s?90|0)[\s.-]?\(?[1-9]\d{2}\)?[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}(?!\d)/g;
const INTL_PHONE_RE =
  /(?<![\w+])\+\d{1,3}[\s.-]?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{2,4}(?:[\s.-]?\d{2,4})?(?!\d)/g;
const IBAN_RE = /\bTR\d{2}(?:[\s-]?\d{4}){5}[\s-]?\d{2}\b/gi;

export const PII_PLACEHOLDER_RE = /\[(?:ad|e-posta|telefon|kimlik no|iban|adres)\]/g;

const PLACEHOLDER_EN: Record<string, string> = {
  "[ad]": "[name]",
  "[e-posta]": "[email]",
  "[telefon]": "[phone]",
  "[kimlik no]": "[id number]",
  "[iban]": "[iban]",
  "[adres]": "[address]",
};

export function maskPii(text: string): string {
  return text
    .replace(EMAIL_RE, "[e-posta]")
    .replace(IBAN_RE, "[iban]")
    .replace(TR_PHONE_RE, "[telefon]")
    .replace(INTL_PHONE_RE, "[telefon]");
}

export function localizePlaceholders(text: string, locale: Locale): string {
  if (locale === "tr") return text;
  return text.replace(PII_PLACEHOLDER_RE, (m) => PLACEHOLDER_EN[m] ?? m);
}

/** Alıntıdan arama terimi: yer tutucular aramada eşleşmez, bu yüzden en
 *  uzun yer-tutucusuz parçanın ilk kelimeleri kullanılır. */
export function searchableQuoteFragment(quote: string, maxWords = 7): string {
  const head = quote.split(/\.{3}|…/)[0] ?? quote;
  const segments = head
    .split(PII_PLACEHOLDER_RE)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
  const longest = segments.sort((a, b) => b.length - a.length)[0] ?? head;
  return longest.split(/\s+/).filter(Boolean).slice(0, maxWords).join(" ");
}
