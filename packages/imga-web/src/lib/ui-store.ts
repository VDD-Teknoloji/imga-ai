// Cross-component UI state.
//
// Owns the sidebar collapsed flag (and any future "is the modal X
// open" booleans). Persists the collapsed flag to localStorage so a
// user's preferred sidebar width survives reloads.

import { create } from "zustand";

// Sprint 12 — key v3: ürün sahibi kararı "sol menü varsayılan AÇIK
// gelsin". Eski v2 key'inde "default kapalı" döneminde kapalı (1)
// kaydedilmiş tercihler yeni açık kararını ezecekti; v3 ile herkes
// bir kez açık başlar, kullanıcı kapatırsa tercihi buradan itibaren
// yeniden öğrenilir.
const SIDEBAR_COLLAPSED_KEY = "imga_sidebar_collapsed_v3";

function persistCollapsed(value: boolean): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, value ? "1" : "0");
}

interface UiState {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  setSidebarCollapsed: (value: boolean) => void;
  /** Mount sonrası localStorage'daki tercihi uygular. Initial state
   *  her zaman ``false`` (açık) — server ve client ilk render'ı
   *  aynı olur, hydration mismatch çıkmaz; kayıtlı "kapalı" tercihi
   *  ilk frame'den sonra animasyonlu daralmayla gelir. */
  hydrateSidebar: () => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  // Sprint 12 — default AÇIK. Ürün sahibi: "soldaki menü varsayılan
  // açık gelsin." Yöneticiler nereye gidebileceklerini ilk bakışta
  // görsün; kapatmak isteyen tek tıkla icon-dock'a indirir.
  sidebarCollapsed: false,
  toggleSidebar: () => {
    const next = !get().sidebarCollapsed;
    persistCollapsed(next);
    set({ sidebarCollapsed: next });
  },
  setSidebarCollapsed: (value) => {
    persistCollapsed(value);
    set({ sidebarCollapsed: value });
  },
  hydrateSidebar: () => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    if (stored !== null) {
      set({ sidebarCollapsed: stored === "1" });
    }
  },
}));
