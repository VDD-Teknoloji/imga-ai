import { expect, test } from "@playwright/test";

/**
 * Sprint 9.0.6 C — auth surface rate limits.
 *
 * The backend caps /auth/login at 5/min/IP and 10/min/username.
 * After the cap is hit the response is 429 with Retry-After: 60.
 * We exercise the per-IP cap because it's the lowest threshold and
 * the most demo-visible failure mode (form submission silently
 * stops working under credential-stuffing attempts).
 *
 * The test runs serial: the rate limiter is in-memory and the buckets
 * are global to the API process. A parallel run would interfere.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";

test.describe.configure({ mode: "serial" });

test.describe("rate-limit", () => {
  test("/auth/login per-IP cap returns 429 after 5 wrong attempts", async ({
    request,
  }) => {
    // Five wrong-password attempts each return 401.
    for (let i = 0; i < 5; i++) {
      const r = await request.post(`${API_BASE}/auth/login`, {
        data: {
          email: "alice@acme.com",
          password: "definitely-wrong",
        },
      });
      expect(r.status()).toBe(401);
    }
    // Sixth attempt — even with the right password — is rate-limited.
    const blocked = await request.post(`${API_BASE}/auth/login`, {
      data: { email: "alice@acme.com", password: "dev123" },
    });
    expect(blocked.status()).toBe(429);
    expect(blocked.headers()["retry-after"]).toBe("60");
  });
});
