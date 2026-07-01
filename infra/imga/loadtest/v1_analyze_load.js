// İmga v1 partner API — load test (contract §11 / goal §2.4).
//
// Hedef: 10 req/s sabit yük × 10 dk, hata < %0.1, p95 < 3s (non-stream).
// Ayrıca /v1/health smoke (unauth) — provider degraded sinyali görünür mü.
//
// Çalıştırma (server-agent, gerçek altyapıda):
//   IMGA_BASE_URL=https://api-staging.imga.ai \
//   IMGA_TENANT_TOKEN=imga_stg_xxx \
//   IMGA_TENANT_ID=asakai-staging \
//   k6 run infra/imga/loadtest/v1_analyze_load.js
//
// Not: /v1/analyze GERÇEK Gemini çağrısı yapar → 10 req/s × 600s ≈ 6000 üretim
// çağrısı (maliyet + kota). Kotanın (2M/gün) bu yükü karşıladığını doğrula:
// 6000 istek × ~800 token ≈ 4.8M token > 2M → TEK KOŞUDA KOTA AŞILIR.
// Load test için ya kotayı geçici yükselt (POST /v1/admin/tenants/{id}/quota)
// ya da IMGA_QUOTA_SAFE=1 ile yük /v1/health'e (unauth, LLM'siz) yönlendirilir.

import http from "k6/http";
import { check, sleep } from "k6";
import { Counter, Trend } from "k6/metrics";

const BASE = __ENV.IMGA_BASE_URL || "https://api-staging.imga.ai";
const TOKEN = __ENV.IMGA_TENANT_TOKEN || "";
const TENANT_ID = __ENV.IMGA_TENANT_ID || "asakai-staging";
const QUOTA_SAFE = __ENV.IMGA_QUOTA_SAFE === "1";

const analyzeLatency = new Trend("imga_analyze_latency_ms", true);
const rateLimited = new Counter("imga_429_count");
const providerErrors = new Counter("imga_502_count");

export const options = {
  scenarios: {
    // Sabit 10 req/s × 10 dk (constant-arrival-rate → gerçek RPS, VU sayısına bağlı değil).
    steady_10rps: {
      executor: "constant-arrival-rate",
      rate: 10,
      timeUnit: "1s",
      duration: "10m",
      preAllocatedVUs: 40,
      maxVUs: 100,
    },
  },
  thresholds: {
    // §2.4 kabul kriterleri — biri kırmızıysa k6 non-zero exit → CI fail.
    http_req_failed: ["rate<0.001"], // hata < %0.1
    http_req_duration: ["p(95)<3000"], // p95 < 3s
    imga_analyze_latency_ms: ["p(95)<3000"],
  },
};

function uuid4() {
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export default function () {
  if (QUOTA_SAFE || !TOKEN) {
    // LLM'siz yol — sadece HTTP stack + health probe yükü.
    const res = http.get(`${BASE}/v1/health`);
    check(res, {
      "health 200": (r) => r.status === 200,
      "health json ok/degraded": (r) => {
        try {
          const s = r.json("status");
          return s === "ok" || s === "degraded";
        } catch (_e) {
          return false;
        }
      },
    });
    sleep(0.01);
    return;
  }

  const body = JSON.stringify({
    tenant_id: TENANT_ID,
    use_case: "free-analyze",
    period: "custom",
    period_start: "2026-06-01",
    period_end: "2026-06-30",
    context: { source: "loadtest" },
    user_prompt: "Son 30 günde iade oranı neden arttı? Kısa özetle.",
    language: "tr",
    client_request_id: uuid4(),
  });

  const res = http.post(`${BASE}/v1/analyze/free-analyze`, body, {
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${TOKEN}`,
    },
    timeout: "35s",
  });

  analyzeLatency.add(res.timings.duration);
  if (res.status === 429) rateLimited.add(1);
  if (res.status === 502) providerErrors.add(1);

  check(res, {
    "analyze 200": (r) => r.status === 200,
    "envelope ok:true": (r) => {
      try {
        return r.json("ok") === true;
      } catch (_e) {
        return false;
      }
    },
    "meta.processed_in outbound": (r) => {
      try {
        return r.json("meta.processed_in") === "outbound";
      } catch (_e) {
        return false;
      }
    },
    "X-Imga-Request-Id present": (r) =>
      (r.headers["X-Imga-Request-Id"] || "").length > 0,
  });
}
