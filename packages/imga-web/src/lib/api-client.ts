// Thin fetch wrapper.
//
// Sprint 9.0.6 B: auth pivoted from localStorage Bearer tokens to
// HttpOnly cookies. Every fetch sends ``credentials: "include"`` so
// the browser ships the ``imga_access`` / ``imga_refresh`` cookies
// the server set on /auth/login. The wrapper no longer reads or
// writes any token — JS can't see HttpOnly cookies, which is the
// whole point (XSS that lands in the page can't exfiltrate them).
//
// Three jobs:
//   1. Prefix paths with NEXT_PUBLIC_API_URL.
//   2. Send credentials so the cookie rides along.
//   3. On 401 from a non-auth-bootstrap request, try one rotation
//      (the new pair lands as cookies on the response) and replay.
//      If refresh also 401s, propagate — caller decides whether to
//      redirect.
//
// We deliberately don't auto-redirect on 401 from this module —
// that's the auth store / ProtectedRoute's job.

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    public readonly body?: unknown,
    public readonly requestId?: string,
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

// Sprint 9.1 I — auth-bootstrap paths must NOT trigger the 401-retry
// loop, otherwise a wrong-password /auth/login or an invalid
// invitation accept would round-trip through /auth/refresh and replay
// itself. The replay is harmless when there's no session cookie (the
// refresh fails with 401 and we propagate) but it doubles the network
// and makes the failure UX feel sluggish.
const AUTH_BOOTSTRAP_PATHS: ReadonlySet<string> = new Set([
  "/auth/login",
  "/auth/refresh",
]);

function isAuthBootstrap(path: string): boolean {
  if (AUTH_BOOTSTRAP_PATHS.has(path)) return true;
  // /invitations/{token}/accept and /accept-existing are unauthenticated
  // bootstrap paths. The exact-token segment varies, so prefix-match.
  return path.startsWith("/invitations/");
}

export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const isFormData =
    typeof FormData !== "undefined" && options.body instanceof FormData;
  const headers: Record<string, string> = {};
  // FormData lets the browser set Content-Type with the multipart
  // boundary; setting it manually breaks parsing. JSON is the default.
  if (!isFormData) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method: options.method ?? "GET",
    headers,
    // Always ``include``. Sprint 9.0.6 cookie hotfix — the earlier
    // ``options.skipAuth ? "omit" : "include"`` form silently
    // disregarded Set-Cookie on /auth/login responses. The skipAuth
    // flag was removed in 9.1 I; auth-bootstrap paths are now
    // identified by URL (see isAuthBootstrap above).
    credentials: "include",
    body:
      options.body === undefined
        ? undefined
        : isFormData
        ? (options.body as FormData)
        : JSON.stringify(options.body),
    signal: options.signal,
  });

  if (response.ok) {
    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  }

  // 401 → try one refresh, replay original request once.
  if (response.status === 401 && !isAuthBootstrap(path)) {
    const refreshed = await tryRefresh();
    if (refreshed) {
      return apiRequest<T>(path, options);
    }
  }

  let detail = `HTTP ${response.status}`;
  let body: unknown;
  try {
    body = await response.json();
    if (typeof body === "object" && body !== null && "detail" in body) {
      const candidate = (body as { detail: unknown }).detail;
      if (typeof candidate === "string") detail = candidate;
    }
  } catch {
    // non-JSON error body; keep the default detail string.
  }

  // Sprint 9.1 C — surface the server's request_id so support tickets
  // can pinpoint the exact log entry. Header is canonical (set by
  // request-id middleware); body field is a back-up for clients that
  // can't read response headers.
  const headerRequestId = response.headers.get("X-Request-ID") ?? undefined;
  const bodyRequestId =
    typeof body === "object" && body !== null && "request_id" in body
      ? (body as { request_id: unknown }).request_id
      : undefined;
  const requestId =
    headerRequestId ??
    (typeof bodyRequestId === "string" ? bodyRequestId : undefined);

  throw new ApiError(response.status, detail, body, requestId);
}

// Sprint 9.0.6 A — module-level singleton so concurrent 401s coalesce
// into a single /auth/refresh call. Without this, an N-pane dashboard
// firing simultaneous 401s would race N rotations against the same
// (single-use) refresh token; the second arrival hits chain-reuse
// detection on the backend and the entire family is revoked, which
// looks like a random forced logout to the user. The first 401 starts
// the rotation; everyone else awaits the same Promise. The slot is
// cleared only after the call settles, so a *later* 401 (after a
// fresh access token expires) starts its own rotation.
let inFlightRefresh: Promise<boolean> | null = null;

// Sprint 9.1 hotfix — when /auth/refresh fails the user is fully
// signed out (refresh cookie missing / expired / chain-reuse-revoked
// by the backend). The api-client can't import the auth-store +
// next/navigation (those would pull React/router into a leaf
// utility), so we expose a setter for the AuthProvider to register a
// callback. The callback gets fired exactly once per "stuck" refresh,
// debounced via ``inFlightRefresh`` so a burst of 401s from the same
// expired session triggers a single redirect (not N).
type SessionExpiredHandler = () => void;
let onSessionExpired: SessionExpiredHandler | null = null;

/** Register a callback fired when /auth/refresh fails irrecoverably.
 *  Called by AuthProvider once at mount; the callback should clear
 *  in-memory auth state AND navigate to /login. */
export function setOnSessionExpired(handler: SessionExpiredHandler): void {
  onSessionExpired = handler;
}

async function tryRefresh(): Promise<boolean> {
  if (inFlightRefresh) {
    return inFlightRefresh;
  }
  inFlightRefresh = (async () => {
    try {
      // Empty body — the refresh token rides on the HttpOnly cookie
      // and the server reads it via ``request.cookies``. Server
      // rotates and writes the new pair as cookies on the response.
      const response = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (!response.ok) {
        return false;
      }
      // Body is still emitted for Bearer-style integrations; we don't
      // need it (cookies were just rewritten) but drain the stream.
      await response.json().catch(() => null);
      return true;
    } catch {
      return false;
    }
  })();
  try {
    const ok = await inFlightRefresh;
    if (!ok && onSessionExpired) {
      // Sprint 9.1 hotfix — refresh failed; the session is dead.
      // Notify the AuthProvider so it can clear state + redirect.
      // Wrapped in try/catch so a buggy handler doesn't smother the
      // ``return false`` the caller expects.
      try {
        onSessionExpired();
      } catch {
        // swallow — the original 401 propagation is what matters
      }
    }
    return ok;
  } finally {
    inFlightRefresh = null;
  }
}

/** Test-only — clears the in-flight refresh slot between cases. */
export function _resetRefreshMutexForTests(): void {
  inFlightRefresh = null;
  onSessionExpired = null;
}

/**
 * Sprint 9.1 C — turn an unknown thrown value into a user-facing
 * string. For ApiError we surface the server's detail; if a 5xx
 * carried a request_id we append a "(destek kodu: …)" suffix so the
 * user can quote it on a support ticket and the log line can be
 * found by `grep req=<id>`.
 */
export function formatApiErrorMessage(
  err: unknown,
  fallback = "Bir hata oluştu, lütfen tekrar deneyin.",
): string {
  if (err instanceof ApiError) {
    if (err.status >= 500 && err.requestId) {
      return `${err.detail} (destek kodu: ${err.requestId})`;
    }
    return err.detail || fallback;
  }
  if (err instanceof Error) {
    return err.message || fallback;
  }
  return fallback;
}
