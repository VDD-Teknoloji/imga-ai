/**
 * Locale-farkında enum etiket haritaları (Sprint 12 i18n).
 *
 * Paylaşılan `Record<enum, string>` etiket haritaları (ticket durum/öncelik, rol,
 * plan vb.) uygulama genelinde `MAP[value]` ile doğrudan kullanılıyor. `localeLabels`
 * bunları, ÇAĞIRANLARI HİÇ DEĞİŞTİRMEDEN, aktif locale'e göre çözen bir Proxy'ye
 * sarar: `MAP[value]` erişimi o anki dilin etiketini döndürür (yoksa tr'ye düşer).
 *
 * Not: bu haritalar Object.keys/entries ile iterasyona girMEZ (yalnız anahtar
 * erişimi) — bu yüzden tek `get` trap'i yeterli. Reaktiflik: kimlikli kullanıcıda
 * locale = kurum dili (yalnız kurum değişince değişir → tüm ağaç yeniden render).
 */

import { useAuthStore } from "@/lib/auth-store";

import { browserLocale, type Locale } from "./config";
import { useLocaleStore } from "./locale-store";

/** O anki aktif locale (hook değil — store getState ile; render sırasında okunur). */
export function currentLocale(): Locale {
  const tenantLang = useAuthStore.getState().activeContext?.language ?? null;
  const preferred = useLocaleStore.getState().preferred;
  return tenantLang ?? preferred ?? browserLocale();
}

export function localeLabels<K extends string>(
  byLocale: Record<Locale, Record<K, string>>,
): Record<K, string> {
  return new Proxy({} as Record<K, string>, {
    get: (_target, prop): string | undefined => {
      if (typeof prop !== "string") return undefined;
      const loc = currentLocale();
      return byLocale[loc][prop as K] ?? byLocale.tr[prop as K];
    },
  });
}
