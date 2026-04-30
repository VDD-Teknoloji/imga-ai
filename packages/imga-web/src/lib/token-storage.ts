// Browser-localStorage wrapper for the JWT access + refresh pair.
//
// MVP storage choice: localStorage. Open to XSS (any script with DOM
// access can read the token). Sprint 8 will swap to HttpOnly cookies
// — that requires a server-side auth bridge endpoint that the backend
// doesn't ship today.
//
// Every helper is SSR-safe (returns null when window is undefined) so
// the module can be imported from any component.

const ACCESS_TOKEN_KEY = "imga_access_token";
const REFRESH_TOKEN_KEY = "imga_refresh_token";

export const tokenStorage = {
  getAccessToken(): string | null {
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem(ACCESS_TOKEN_KEY);
  },

  getRefreshToken(): string | null {
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem(REFRESH_TOKEN_KEY);
  },

  setTokens(access: string, refresh: string): void {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(ACCESS_TOKEN_KEY, access);
    window.localStorage.setItem(REFRESH_TOKEN_KEY, refresh);
  },

  clear(): void {
    if (typeof window === "undefined") return;
    window.localStorage.removeItem(ACCESS_TOKEN_KEY);
    window.localStorage.removeItem(REFRESH_TOKEN_KEY);
  },
};
