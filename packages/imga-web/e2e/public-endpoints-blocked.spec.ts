import { expect, test } from "@playwright/test";

/**
 * Sprint 9.0.6 D — public legacy endpoints gated.
 *
 * /analyze, /analyze/batch, /classify, /metrics predate the tenant-
 * scoped surface. Production servers run with
 * IMGA_ENABLE_PUBLIC_DEMO_ENDPOINTS=false (the default), which
 * removes the routes entirely — anonymous probes 404 instead of
 * burning BERT inference. /health stays unconditionally available
 * for compose healthchecks.
 *
 * The dev API process this suite hits is expected to run with the
 * default (gated). If a developer flips the flag locally these
 * tests will fail — that's intentional, the gate is the contract.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8003";

test.describe("public-endpoints-blocked", () => {
  test("/analyze returns 404 when the demo gate is off", async ({ request }) => {
    const r = await request.post(`${API_BASE}/analyze`, {
      data: { text: "deneme yorum" },
    });
    expect(r.status()).toBe(404);
  });

  test("/classify returns 404 when the demo gate is off", async ({
    request,
  }) => {
    const r = await request.post(`${API_BASE}/classify`, {
      data: { text: "deneme yorum" },
    });
    expect(r.status()).toBe(404);
  });

  test("/metrics returns 404 when the demo gate is off", async ({ request }) => {
    const r = await request.get(`${API_BASE}/metrics`);
    expect(r.status()).toBe(404);
  });

  test("/health stays open regardless of the demo gate", async ({ request }) => {
    const r = await request.get(`${API_BASE}/health`);
    expect(r.ok()).toBe(true);
  });
});
