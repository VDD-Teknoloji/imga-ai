"use client";

import { useEffect } from "react";

import { useAuthStore } from "@/lib/auth-store";

/**
 * Calls auth-store.initialize() once at mount so any persisted
 * access token in localStorage is exchanged for a /auth/me snapshot
 * before the rest of the app reads useAuthStore.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const initialize = useAuthStore((s) => s.initialize);

  useEffect(() => {
    void initialize();
  }, [initialize]);

  return <>{children}</>;
}
