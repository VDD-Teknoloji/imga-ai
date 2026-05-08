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
        skipAuth: true,
      });
      const me = await apiRequest<MeResponse>("/auth/me");
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
      set({ user: null, activeContext: null, availableTenants: [] });
    }
  },

  switchTenant: async (tenantId) => {
    await apiRequest<unknown>("/auth/switch-tenant", {
      method: "POST",
      body: { tenant_id: tenantId },
    });
    const me = await apiRequest<MeResponse>("/auth/me");
    set({
      user: me.user,
      activeContext: me.active_context,
      availableTenants: me.available_tenants,
    });
  },

  acceptInvitationAsNewUser: async (token, fullName, password) => {
    set({ isLoading: true });
    try {
      await apiRequest<unknown>(
        `/invitations/${encodeURIComponent(token)}/accept`,
        {
          method: "POST",
          body: { full_name: fullName, password },
          skipAuth: true,
        },
      );
      const me = await apiRequest<MeResponse>("/auth/me");
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
