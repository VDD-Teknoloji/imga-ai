// Cross-component UI state.
//
// Owns the sidebar collapsed flag (and any future "is the modal X
// open" booleans). Persists the collapsed flag to localStorage so a
// user's preferred sidebar width survives reloads.

import { create } from "zustand";

const SIDEBAR_COLLAPSED_KEY = "imga_sidebar_collapsed";

function readInitialCollapsed(): boolean {
  // Sprint 10.0 — default KAPALI. C-level redesign'da dashboard
  // tam genişlikte açılır; sidebar icon-dock olarak başlar.
  // Kullanıcı genişletirse tercih localStorage'da yaşamaya devam
  // eder ("0" yazılır ve sonraki ziyarette açık gelir). SSR'da da
  // kapalı varsayıyoruz ki hydration sırasında genişten dara
  // çökme (layout shift) olmasın.
  if (typeof window === "undefined") return true;
  const stored = window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
  return stored === null ? true : stored === "1";
}

function persistCollapsed(value: boolean): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, value ? "1" : "0");
}

interface UiState {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  setSidebarCollapsed: (value: boolean) => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  sidebarCollapsed: readInitialCollapsed(),
  toggleSidebar: () => {
    const next = !get().sidebarCollapsed;
    persistCollapsed(next);
    set({ sidebarCollapsed: next });
  },
  setSidebarCollapsed: (value) => {
    persistCollapsed(value);
    set({ sidebarCollapsed: value });
  },
}));
