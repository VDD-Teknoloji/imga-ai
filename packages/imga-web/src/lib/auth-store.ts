// Zustand store for the authentication state.
//
// Owns: current user, active tenant context, list of tenants the
// user can switch to, and the four flow methods (login, logout,
// switchTenant, initialize). Tokens themselves live in tokenStorage
// (localStorage); the store keeps only the decoded /me snapshot.
//
// initialize() is called once at mount by AuthProvider — it tries
// /auth/me with the persisted access token, populates the store on
// success, or quietly clears tokens on 401.

import { create } from "zustand";

import { ApiError, apiRequest } from "./api-client";
import { tokenStorage } from "./token-storage";
import type { ActiveContext, MeResponse, TenantSummary, TokenPair, UserSummary } from "./types";

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
   * POST /invitations/{token}/accept with full_name + password,
   * stores the returned token pair, and populates user / context
   * via /auth/me. Mirrors `login()` semantics so the caller can
   * redirect to "/" right after.
   */
  acceptInvitationAsNewUser: (
    token: string,
    fullName: string,
    password: string,
  ) => Promise<void>;
  /**
   * Already-logged-in user accepts an invitation for a different
   * tenant. POST /invitations/{token}/accept-existing with the
   * password (re-auth). The token pair the backend re-issues
   * carries the same active_tenant_id/role; the new tenant lands
   * in /auth/me's available_tenants without a logout cycle.
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
      const tokens = await apiRequest<TokenPair>("/auth/login", {
        method: "POST",
        body: { email, password },
        skipAuth: true,
      });
      tokenStorage.setTokens(tokens.access_token, tokens.refresh_token);

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
    const refreshToken = tokenStorage.getRefreshToken();
    try {
      if (refreshToken) {
        await apiRequest<void>("/auth/logout", {
          method: "POST",
          body: { refresh_token: refreshToken },
        });
      }
    } catch {
      // logout is idempotent on the backend; failing here just means
      // the token was already revoked. We still clear local state.
    } finally {
      tokenStorage.clear();
      set({ user: null, activeContext: null, availableTenants: [] });
    }
  },

  switchTenant: async (tenantId) => {
    const tokens = await apiRequest<TokenPair>("/auth/switch-tenant", {
      method: "POST",
      body: { tenant_id: tenantId },
    });
    tokenStorage.setTokens(tokens.access_token, tokens.refresh_token);

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
      const tokens = await apiRequest<TokenPair>(
        `/invitations/${encodeURIComponent(token)}/accept`,
        {
          method: "POST",
          body: { full_name: fullName, password },
          skipAuth: true,
        },
      );
      tokenStorage.setTokens(tokens.access_token, tokens.refresh_token);

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
    // Caller is already authenticated (bearer is attached by the
    // api-client). The backend re-issues a token pair preserving the
    // current active tenant context; the new tenant just appears in
    // available_tenants on the next /auth/me read.
    const tokens = await apiRequest<TokenPair>(
      `/invitations/${encodeURIComponent(token)}/accept-existing`,
      {
        method: "POST",
        body: { password },
      },
    );
    tokenStorage.setTokens(tokens.access_token, tokens.refresh_token);

    const me = await apiRequest<MeResponse>("/auth/me");
    set({
      user: me.user,
      activeContext: me.active_context,
      availableTenants: me.available_tenants,
    });
  },

  initialize: async () => {
    const token = tokenStorage.getAccessToken();
    if (!token) {
      set({ isInitialized: true });
      return;
    }

    try {
      const me = await apiRequest<MeResponse>("/auth/me");
      set({
        user: me.user,
        activeContext: me.active_context,
        availableTenants: me.available_tenants,
        isInitialized: true,
      });
    } catch (err) {
      // 401 here means refresh has already failed too; clear tokens
      // and let ProtectedRoute redirect to /login.
      if (err instanceof ApiError && err.status === 401) {
        tokenStorage.clear();
      }
      set({ isInitialized: true });
    }
  },
}));
