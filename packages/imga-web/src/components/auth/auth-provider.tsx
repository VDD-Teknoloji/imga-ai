"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { setOnSessionExpired } from "@/lib/api-client";
import { setAuthQueryClient, useAuthStore } from "@/lib/auth-store";

/**
 * Calls auth-store.initialize() once at mount so the HttpOnly auth
 * cookie (if any) is exchanged for a /auth/me snapshot before the
 * rest of the app reads useAuthStore.
 *
 * Sprint 9.1 hotfix — also wires two cross-module hooks the api-client
 * + auth-store can't take directly:
 *   1. ``setOnSessionExpired`` — fired when /auth/refresh fails so the
 *      app clears state AND redirects to /login?expired=1 instead of
 *      stranding the user on an empty page that just keeps 401-ing.
 *   2. ``setAuthQueryClient`` — gives the auth store a handle to the
 *      TanStack QueryClient so a tenant switch (or invite-accept) can
 *      clear all cached query data; without this, /reviews / /insights
 *      / etc. would render the previous tenant's data until the user
 *      hard-reloaded.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const initialize = useAuthStore((s) => s.initialize);
  const router = useRouter();
  const queryClient = useQueryClient();

  // Register the QueryClient handle BEFORE initialize() runs so any
  // refetch the initialize path triggers (none today, but defensive)
  // sees a wired store. Same reason for the session-expired hook.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    setAuthQueryClient(queryClient);
    setOnSessionExpired(() => {
      // Wipe in-memory auth state so ProtectedRoute's redirect path
      // doesn't briefly render dashboard chrome with stale user data.
      useAuthStore.getState().handleSessionExpired();
      // Keep query cache clean for the next user's session.
      queryClient.clear();
      router.replace("/login?expired=1");
    });
    void initialize();
  }, [initialize, router, queryClient]);
  /* eslint-enable react-hooks/set-state-in-effect */

  return <>{children}</>;
}
