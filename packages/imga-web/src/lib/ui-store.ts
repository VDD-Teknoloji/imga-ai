// Cross-component UI state.
//
// Owns the sidebar collapsed flag (and any future "is the modal X
// open" booleans). Persists the collapsed flag to localStorage so a
// user's preferred sidebar width survives reloads.

import { create } from "zustand";

// Sprint 10.1 — key versiyonlandı (v2): eski key'de kalan "0"
// (açık) tercihi yeni "default kapalı" kararını eziyordu. v2 ile
// herkes bir kez kapalı başlar; kullanıcı açarsa tercihi buradan
// itibaren yeniden öğrenilir.
const SIDEBAR_COLLAPSED_KEY = "imga_sidebar_collapsed_v2";

function persistCollapsed(value: boolean): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, value ? "1" : "0");
}

interface UiState {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  setSidebarCollapsed: (value: boolean) => void;
  /** Mount sonrası localStorage'daki tercihi uygular. Initial state
   *  her zaman ``true`` (kapalı) — server ve client ilk render'ı
   *  aynı olur, hydration mismatch çıkmaz; kayıtlı "açık" tercihi
   *  ilk frame'den sonra animasyonlu genişlemeyle gelir. */
  hydrateSidebar: () => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  // Sprint 10.0/10.1 — default KAPALI. C-level redesign'da dashboard
  // tam genişlikte açılır; sidebar icon-dock olarak başlar.
  sidebarCollapsed: true,
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
