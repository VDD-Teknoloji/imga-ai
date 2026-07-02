"use client";

/**
 * `<html lang>` özniteliğini aktif locale'e göre günceller. Root layout server
 * component olduğu için `lang` statik ("tr"); bu küçük client bileşeni mount +
 * locale değişiminde `document.documentElement.lang`'ı senkronlar (erişilebilirlik
 * + tarayıcı çeviri ipuçları için doğru dil). Görsel çıktı üretmez.
 */

import { useEffect } from "react";

import { useLocale } from "@/lib/i18n/use-translation";

export function LocaleHtmlLang() {
  const locale = useLocale();
  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.lang = locale;
    }
  }, [locale]);
  return null;
}
