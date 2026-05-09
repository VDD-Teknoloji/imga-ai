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
//   3. On 401 from a non-/auth/refresh request, try one rotation
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
  ) {
    super(detail);
    this.name = "ApiError";
  }
}

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
  skipAuth?: boolean;
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
    // Always ``include``. Sprint 9.0.6 cookie hotfix — the original
    // ``options.skipAuth ? "omit" : "include"`` form bit us in
    // production: ``credentials: "omit"`` not only skips outbound
    // cookies but also makes the browser disregard ``Set-Cookie`` on
    // the response. /auth/login + invitation accept (the three
    // skipAuth callers) were exactly the responses that needed to
    // *land* the cookies, so login looked like it succeeded but no
    // session was stored. The skipAuth flag stays for type
    // compatibility with existing callers; its effect is now no-op
    // since Sprint 9.0.6 B removed the Bearer header path it gated.
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
  if (response.status === 401 && !options.skipAuth && path !== "/auth/refresh") {
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

  throw new ApiError(response.status, detail, body);
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
    return await inFlightRefresh;
  } finally {
    inFlightRefresh = null;
  }
}

/** Test-only — clears the in-flight refresh slot between cases. */
export function _resetRefreshMutexForTests(): void {
  inFlightRefresh = null;
}
