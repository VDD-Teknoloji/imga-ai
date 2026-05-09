// Zustand store for the authentication state.
//
// Sprint 9.0.6 B — auth state of record is the HttpOnly cookie pair
// (``imga_access`` + ``imga_refresh``) the API sets on /auth/login.
// JS can't read those cookies, so the store no longer caches tokens
// at all — it only holds the decoded /me snapshot. Every cross-tab
// behaviour falls out of the cookie: another tab logs in, the cookie
// updates, this tab's next API call rides the new session.
//
// initialize() unconditionally hits /auth/me — if the cookie is
// present and valid the user / context populate; on 401 we leave the
// store empty and let ProtectedRoute redirect.
//
// Sprint 9.1 hotfix — switching tenants used to leave React Query's
// caches intact, so /reviews etc. rendered the previous tenant's data
// until the user hard-reloaded. The store now holds a handle to the
// app's QueryClient (registered by AuthProvider once at mount) and
// clears it on every tenant transition. ``handleSessionExpired`` is
// the dual: clear state when the api-client tells us the refresh
// chain is dead.

import type { QueryClient } from "@tanstack/react-query";
import { create } from "zustand";

import { ApiError, apiRequest } from "./api-client";
import type {
  ActiveContext,
  MeResponse,
  TenantSummary,
  UserSummary,
} from "./types";

interface AuthState {
  user: UserSummary | null;
  activeContext: ActiveContext | null;
  availableTenants: TenantSummary[];
  isLoading: boolean;
  isInitialized: boolean;

  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  switchTenant: (tenantId: string) => Promise<void>;
  initialize: () => Promise<void>;
  /**
   * Sprint 9.1 hotfix — called by the api-client when /auth/refresh
   * fails. Clears the in-memory snapshot so ProtectedRoute redirects
   * to /login on the next render; the navigation itself is the
   * AuthProvider's job (it has access to next/navigation).
   */
  handleSessionExpired: () => void;
  /**
   * Public invite-accept flow for a brand-new user. Hits
   * POST /invitations/{token}/accept with full_name + password.
   * The backend sets the auth cookies on the response; the store
   * then reads /auth/me to populate user / context. Mirrors `login()`
   * semantics so the caller can redirect to "/" right after.
   */
  acceptInvitationAsNewUser: (
    token: string,
    fullName: string,
    password: string,
  ) => Promise<void>;
  /**
   * Already-logged-in user accepts an invitation for a different
   * tenant. POST /invitations/{token}/accept-existing with the
   * password (re-auth). The token pair the backend re-issues lands
   * as fresh cookies; the new tenant appears in available_tenants on
   * the next /auth/me read.
   */
  joinTenantViaInvitation: (token: string, password: string) => Promise<void>;
}

// Sprint 9.1 hotfix — module-level QueryClient handle. AuthProvider
// registers it once at mount via ``setAuthQueryClient``; the store
// uses it to clear cached queries on tenant transitions and on
// session-expired sign-out. We don't import the client directly
// because the store loads outside the React tree (zustand vanilla)
// and the QueryClient is React-context-bound — the setter pattern
// keeps the dependency one-way.
let queryClientHandle: QueryClient | null = null;

export function setAuthQueryClient(client: QueryClient | null): void {
  queryClientHandle = client;
}

function clearTenantScopedQueries(): void {
  if (queryClientHandle === null) return;
  // Sprint 9.1 hotfix — ``clear()`` wipes every cache entry. Most
  // queries are tenant-scoped (reviews, insights, briefings, action
  // items, ...); the few that aren't (auth/me itself, sentiment
  // helpers) refetch on the next render anyway. Per-key invalidation
  // would need every hook to opt in; ``clear()`` is the
  // forget-nothing default that survives a future hook landing
  // without remembering to add itself to an allow-list.
  queryClientHandle.clear();
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  activeContext: null,
  availableTenants: [],
  isLoading: false,
  isInitialized: false,

  login: async (email, password) => {
    set({ isLoading: true });
    try {
      // Server sets the auth cookies on the response; the JSON body is
      // still emitted for Bearer-style integrations but we don't read it.
      await apiRequest<unknown>("/auth/login", {
        method: "POST",
        body: { email, password },
      });
      const me = await apiRequest<MeResponse>("/auth/me");
      // Sprint 9.1 hotfix — paranoia clear so a previous user's cache
      // (logged-out tab, fresh login on the same browser) can't leak
      // into the new session's first paint.
      clearTenantScopedQueries();
      set({
        user: me.user,
        activeContext: me.active_context,
        availableTenants: me.available_tenants,
        isInitialized: true,
      });
    } finally {
      set({ isLoading: false });
    }
  },

  logout: async () => {
    try {
      // Empty body — the refresh token rides on the cookie. The server
      // revokes the family AND clears both cookies on the response.
      await apiRequest<void>("/auth/logout", {
        method: "POST",
        body: {},
      });
    } catch {
      // logout is idempotent on the backend; failing here just means
      // the cookie was already missing or revoked. We still clear UI
      // state below.
    } finally {
      clearTenantScopedQueries();
      set({ user: null, activeContext: null, availableTenants: [] });
    }
  },

  switchTenant: async (tenantId) => {
    await apiRequest<unknown>("/auth/switch-tenant", {
      method: "POST",
      body: { tenant_id: tenantId },
    });
    const me = await apiRequest<MeResponse>("/auth/me");
    // Sprint 9.1 hotfix — wipe the old tenant's cache BEFORE the
    // store update so the next render's queries see ``no data, fetch``
    // rather than ``stale data, refetch in background``. The latter
    // briefly flashes the previous tenant's rows.
    clearTenantScopedQueries();
    set({
      user: me.user,
      activeContext: me.active_context,
      availableTenants: me.available_tenants,
    });
  },

  handleSessionExpired: () => {
    // Sprint 9.1 hotfix — wipe local snapshot. The AuthProvider also
    // calls queryClient.clear() and pushes the router; this method
    // owns the auth-state slice only.
    set({ user: null, activeContext: null, availableTenants: [] });
  },

  acceptInvitationAsNewUser: async (token, fullName, password) => {
    set({ isLoading: true });
    try {
      await apiRequest<unknown>(
        `/invitations/${encodeURIComponent(token)}/accept`,
        {
          method: "POST",
          body: { full_name: fullName, password },
        },
      );
      const me = await apiRequest<MeResponse>("/auth/me");
      clearTenantScopedQueries();
      set({
        user: me.user,
        activeContext: me.active_context,
        availableTenants: me.available_tenants,
        isInitialized: true,
      });
    } finally {
      set({ isLoading: false });
    }
  },

  joinTenantViaInvitation: async (token, password) => {
    // Caller is already authenticated (cookie rides credentials:include).
    // The backend re-issues a token pair preserving the current active
    // tenant context; the new tenant appears in available_tenants on
    // the next /auth/me read.
    await apiRequest<unknown>(
      `/invitations/${encodeURIComponent(token)}/accept-existing`,
      {
        method: "POST",
        body: { password },
      },
    );
    const me = await apiRequest<MeResponse>("/auth/me");
    clearTenantScopedQueries();
    set({
      user: me.user,
      activeContext: me.active_context,
      availableTenants: me.available_tenants,
    });
  },

  initialize: async () => {
    try {
      const me = await apiRequest<MeResponse>("/auth/me");
      set({
        user: me.user,
        activeContext: me.active_context,
        availableTenants: me.available_tenants,
        isInitialized: true,
      });
    } catch (err) {
      // 401 means there's no valid session cookie (or refresh failed
      // too). Mark initialized so ProtectedRoute can redirect to login.
      if (err instanceof ApiError && err.status === 401) {
        set({ isInitialized: true });
        return;
      }
      // Network / 5xx — still flip to initialized; the page can show
      // its own error banner instead of spinning forever.
      set({ isInitialized: true });
    }
  },
}));
