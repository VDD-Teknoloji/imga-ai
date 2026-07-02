"use client";

/**
 * Pre-auth dil tercihi (login/davet/süper-yönetici yüzeyi). Aktif kurum dili
 * VARSA o kazanır (bkz. use-translation.useLocale); bu store yalnız kurum
 * bağlamı yokken kullanılan manuel TR/EN tercihini kalıcı tutar (localStorage).
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

import { normalizeLocale, type Locale } from "./config";

interface LocaleStore {
  preferred: Locale | null;
  setPreferred: (locale: Locale) => void;
}

export const useLocaleStore = create<LocaleStore>()(
  persist(
    (set) => ({
      preferred: null,
      setPreferred: (locale) => set({ preferred: normalizeLocale(locale) }),
    }),
    { name: "imga-locale" },
  ),
);
