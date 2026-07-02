"use client";

/**
 * İmga i18n çeviri hook'u.
 *
 * Locale önceliği (kurum-güdümlü):
 *   1. Aktif kurumun dili (auth-store.activeContext.language) — KAZANIR.
 *   2. Pre-auth manuel tercih (locale-store.preferred).
 *   3. Tarayıcı dili (browserLocale).
 *
 * Tenant değişince activeContext.language değişir → UI dili otomatik döner.
 */

import { useAuthStore } from "@/lib/auth-store";

import { browserLocale, DEFAULT_LOCALE, type Locale } from "./config";
import { dictionaries, type MessageKey } from "./dictionaries";
import { useLocaleStore } from "./locale-store";

export function useLocale(): Locale {
  const tenantLang = useAuthStore((s) => s.activeContext?.language ?? null);
  const preferred = useLocaleStore((s) => s.preferred);
  return tenantLang ?? preferred ?? browserLocale();
}

export function useTranslation(): {
  t: (key: MessageKey, vars?: Record<string, string | number>) => string;
  locale: Locale;
} {
  const locale = useLocale();

  const t = (
    key: MessageKey,
    vars?: Record<string, string | number>,
  ): string => {
    let value =
      dictionaries[locale][key] ?? dictionaries[DEFAULT_LOCALE][key] ?? key;
    if (vars) {
      for (const [name, replacement] of Object.entries(vars)) {
        value = value.split(`{${name}}`).join(String(replacement));
      }
    }
    return value;
  };

  return { t, locale };
}
