// Thin fetch wrapper.
//
// Three jobs:
//   1. Prefix paths with NEXT_PUBLIC_API_URL.
//   2. Attach the bearer token from tokenStorage on every request,
//      unless skipAuth is set.
//   3. On 401 from a non-/auth/refresh request, try one rotation
//      and replay. If refresh also 401s, clear tokens and propagate
//      the original 401 — caller decides whether to redirect.
//
// We deliberately don't auto-redirect on 401 from this module —
// that's the auth store / ProtectedRoute's job. Keeps the wrapper
// stateless and easier to reason about.

import { tokenStorage } from "./token-storage";
import type { TokenPair } from "./types";

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
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  if (!options.skipAuth) {
    const token = tokenStorage.getAccessToken();
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
  }

  const response = await fetch(`${API_BASE}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
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

async function tryRefresh(): Promise<boolean> {
  const refreshToken = tokenStorage.getRefreshToken();
  if (!refreshToken) return false;

  try {
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });

    if (!response.ok) {
      tokenStorage.clear();
      return false;
    }

    const tokens = (await response.json()) as TokenPair;
    tokenStorage.setTokens(tokens.access_token, tokens.refresh_token);
    return true;
  } catch {
    tokenStorage.clear();
    return false;
  }
}
