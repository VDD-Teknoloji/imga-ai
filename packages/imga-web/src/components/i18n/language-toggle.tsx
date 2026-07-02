"use client";

/**
 * TR / EN dil düğmesi (segmented). Manuel pre-auth tercihini ayarlar.
 * Not: kullanıcı bir kuruma girdiğinde aktif kurumun dili kazanır (kurum-güdümlü);
 * bu düğme esas olarak login/davet gibi kurum-öncesi yüzeyler içindir.
 */

import { LOCALES } from "@/lib/i18n/config";
import { useLocaleStore } from "@/lib/i18n/locale-store";
import { useLocale, useTranslation } from "@/lib/i18n/use-translation";

export function LanguageToggle({ className = "" }: { className?: string }) {
  const active = useLocale();
  const setPreferred = useLocaleStore((s) => s.setPreferred);
  const { t } = useTranslation();

  return (
    <div
      role="group"
      aria-label={t("locale.switchTitle")}
      className={`inline-flex overflow-hidden rounded-md border border-slate-300 text-xs font-medium ${className}`}
    >
      {LOCALES.map((locale) => {
        const isActive = locale === active;
        return (
          <button
            key={locale}
            type="button"
            onClick={() => setPreferred(locale)}
            aria-pressed={isActive}
            className={`px-2.5 py-1 transition-colors ${
              isActive
                ? "bg-slate-800 text-white"
                : "bg-white text-slate-600 hover:bg-slate-100"
            }`}
          >
            {locale.toUpperCase()}
          </button>
        );
      })}
    </div>
  );
}
