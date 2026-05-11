"use client";

import { useQueryClient } from "@tanstack/react-query";
import { usePathname, useRouter } from "next/navigation";
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
 *
 * Sprint 9.4 hotfix — public routes ALSO mount this provider (it
 * lives in the root layout, above the (authenticated) group). Before
 * this fix, /invite/[token] from a fresh browser ran initialize() →
 * /auth/me → 401 → api-client refresh attempt → tryRefresh fails →
 * onSessionExpired fires → /login?expired=1 redirect. The invitee
 * never got to see the accept form. PUBLIC_PATHS short-circuits the
 * bootstrap on routes that legitimately don't require a session.
 */
const PUBLIC_PATHS: ReadonlyArray<string> = [
  "/login",
  "/invite", // /invite/[token]
  // Forward-compat allowlist — these routes don't exist today but
  // would land outside the (authenticated) group when they do, so
  // keep them gated here too rather than rediscover the bug.
  "/signup",
  "/forgot-password",
  "/reset-password",
];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`),
  );
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const initialize = useAuthStore((s) => s.initialize);
  const router = useRouter();
  const queryClient = useQueryClient();
  const pathname = usePathname();

  // Register the QueryClient handle BEFORE initialize() runs so any
  // refetch the initialize path triggers (none today, but defensive)
  // sees a wired store. Same reason for the session-expired hook.
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
    // Sprint 9.4 hotfix — skip /auth/me on public routes; flip the
    // initialized flag directly so any downstream useEffect that
    // waits on ``isInitialized`` proceeds normally without the
    // round-trip + redirect chain.
    if (isPublicPath(pathname)) {
      useAuthStore.setState({ isInitialized: true });
      return;
    }
    void initialize();
  }, [initialize, router, queryClient, pathname]);

  return <>{children}</>;
}
