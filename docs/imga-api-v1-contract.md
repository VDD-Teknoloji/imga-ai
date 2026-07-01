# İmga API v1 — Contract Specification

**Status:** Draft v1.1 (kontrat-dondurma öncesi son revizyon) · **Owner:** İmga AI · **Consumer:** AsakAI (VDD) · **Effective:** 2026-Q3

**v1.1 değişiklikleri** (İmga kickoff-review 2026-07-01'e yanıt):
- `meta.model` alanı prod'da opak kod döner (§3); açık model kimliği yalnız staging.
- §9 KVKK residency tablosu Hybrid stratejiye güncellendi (bkz. brief §5.1).
- §8 auth: `IMGA_API_TOKEN` → vault (`SETTING_IMGA_API_KEY` — Sprint 13'te AsakAI'de zaten uygulandı).

---

## 1. Base

| Item | Value |
|---|---|
| Base URL (prod) | `https://api.imga.ai/v1` |
| Base URL (staging) | `https://api-staging.imga.ai/v1` |
| Versioning | URL path (`/v1`, `/v2`); breaking changes → new major |
| Auth | `Authorization: Bearer <tenant_token>` |
| Content-Type | `application/json; charset=utf-8` |
| Locale header | `Accept-Language: tr-TR` (default) / `en-US` |
| Timeouts | Client SHOULD wait ≤ 30 s (non-stream), ≤ 120 s (stream) |

---

## 2. Common Request Envelope

Every non-stream POST hits `/v1/analyze/{use_case}` with the same envelope:

```ts
interface AnalyzeRequest<TContext = Record<string, unknown>> {
  tenant_id: string;              // "asakai-prod"
  use_case: UseCase;              // enum below
  period: "day" | "week" | "month" | "custom";
  period_start: string;           // ISO-8601 date, TR timezone assumed
  period_end: string;             // ISO-8601 date, inclusive
  context: TContext;              // use-case specific payload (§4)
  user_prompt?: string;           // optional free-form question (required for free-analyze)
  language: "tr" | "en";
  session_id?: string;            // groups multi-turn calls, UUIDv4
  client_request_id: string;      // idempotency key, UUIDv4
}

type UseCase =
  | "anomaly-explain" | "ticket-analyze" | "ticket-suggest-reply"
  | "return-analyze" | "cargo-optimize" | "free-analyze";
```

---

## 3. Common Response Envelope

```ts
interface AnalyzeResponse<TResp = unknown> {
  ok: true;
  request_id: string;             // İmga-side trace id
  response: TResp;                // use-case specific (§4)
  meta: {
    model: string;                // PROD: opak kod (ör. "prov_a", "prov_tr_1") — açık model adı sızmaz
                                  // STAGING: açık model adı (ör. "gemini-2.5-pro") debug için OK
    processed_in: "tr" | "outbound";  // hangi bölgede işlendi (KVKK audit, §9)
    tokens: { prompt: number; completion: number; total: number };
    latency_ms: number;
    cost_try: number;             // billed to tenant in TRY, 4-decimal
    cached: boolean;
  };
}

interface AnalyzeError {
  ok: false;
  request_id: string;
  error: {
    code: "invalid_input" | "auth_failed" | "rate_limit"
        | "provider_error" | "timeout" | "quota_exceeded";
    message: string;              // human, localized to Accept-Language
    details?: Record<string, unknown>;
    retry_after_seconds?: number; // present iff rate_limit / provider_error
  };
}
```

---

## 4. Use Case Endpoints

All are `POST /v1/analyze/{use_case}`. Only the `context` and `response` fields differ.

### 4.1 `anomaly-explain`
**Context:**
```ts
{
  kpi_snapshot: { metric: string; value: number; unit: string }[];
  delta_vs_previous: { metric: string; delta_pct: number; sign: "up"|"down" }[];
  known_events?: string[];        // "kampanya", "tatil", ...
}
```
**Response:** `{ analysis: string; root_causes: string[]; actions: {title:string; priority:"high"|"med"|"low"; owner_role:string}[] }`

### 4.2 `ticket-analyze`
**Context:** `{ ticket_id: string; ticket_text: string; channel: "email"|"whatsapp"|"phone"|"web" }`
**Response:** `{ sentiment: "positive"|"neutral"|"negative"; category: string; urgency: 1|2|3|4|5; tags: string[]; language_detected: string }`

### 4.3 `ticket-suggest-reply`
**Context:** `{ ticket_text: string; customer_profile?: {name:string; segment:string}; policy_snippets?: string[]; tone: "resmi"|"samimi"|"özür" }`
**Response:** `{ reply_draft: string; sources_used: string[]; warnings: string[] }`

### 4.4 `return-analyze`
**Context:** `{ returns_list: { order_id:string; sku:string; reason_code:string; reason_text?:string; return_date:string; amount_try:number }[] }`
**Response:** `{ patterns: {label:string; share_pct:number}[]; causes: {hypothesis:string; evidence:string}[]; recommendations: string[] }`

### 4.5 `cargo-optimize`
**Context:** `{ order: {order_id:string; sku:string; destination_city:string; weight_kg:number; volume_dm3:number}; cargo_history: {carrier:string; city:string; avg_delivery_days:number; late_rate_pct:number}[] }`
**Response:** `{ suggestion: {carrier:string; reason:string; est_cost_try:number}; delay_forecast: {p50_days:number; p90_days:number; risk_flags:string[]} }`

### 4.6 `free-analyze`
**Context:** `{ snapshot: Record<string, unknown>; hints?: string[] }` — `user_prompt` REQUIRED.
**Response:** `{ answer_markdown: string; charts_suggested?: {kind:"line"|"bar"|"pie"; series:string[]}[]; follow_up_prompts: string[] }`

---

## 5. Error Taxonomy

| HTTP | `error.code` | When | Retry? |
|---|---|---|---|
| 400 | `invalid_input` | schema/enum/missing field | no — fix client |
| 401 | `auth_failed` | missing/expired/revoked token | no — rotate |
| 429 | `rate_limit` | per-min or per-day cap hit | yes after `retry_after_seconds` |
| 429 | `quota_exceeded` | monthly token cap exhausted | no until next billing period |
| 502 | `provider_error` | upstream LLM 5xx | yes ≤ 3× exponential |
| 504 | `timeout` | > 30 s non-stream / > 120 s stream | yes ≤ 1× |

Error body always matches `AnalyzeError` (§3).

---

## 6. Rate Limit & Quota

- **Per-tenant defaults:** 60 req/min, 600 req/hour, **2 000 000 tokens/day** (billed at contract rate).
- **Headers on every response** (2xx and 4xx):
  - `X-RateLimit-Remaining: <int>` — requests left in current minute window
  - `X-RateLimit-Reset: <unix_ts>` — when window resets
  - `X-Quota-Tokens-Remaining: <int>` — daily token budget left
  - `X-Quota-Reset: <unix_ts>` — daily reset (00:00 Europe/Istanbul)
- On 429, `retry_after_seconds` is authoritative; also mirrored in `Retry-After`.

---

## 7. SSE Streaming (free-analyze only)

Two-step handshake to keep the bearer token out of query strings:

1. `POST /v1/analyze/free-analyze/stream-token` with the standard envelope → returns `{ stream_token: string, expires_in: 60 }`.
2. `GET /v1/analyze/stream?token=<stream_token>` → `Content-Type: text/event-stream`.

**Event stream:**
```
event: partial
data: {"delta":"Satışlarda geçen haftaya göre "}

event: partial
data: {"delta":"%12 düşüş dikkat çekici."}

event: meta
data: {"tokens":{"prompt":842,"completion":57},"cost_try":0.0031}

event: done
data: {"finish_reason":"stop","final_length":312}
```
Heartbeat every 15 s as SSE comment (`: ping`). Client SHOULD close after `event: done` or on any `event: error`.

---

## 8. Authentication Flow

1. **Issuance.** İmga admin console mints per-tenant token: `imga_live_<base64url_32>`. Delivered out-of-band (KVKK-compliant channel — no email in cleartext).
2. **Storage.** AsakAI stores it in Docker secret `/etc/vdd-asakai/production/asakai.env` as `IMGA_API_TOKEN` (mirrors existing `GEMINI_API_KEY` pattern in `system_settings.py`).
3. **Usage.** `Authorization: Bearer imga_live_...` on every request.
4. **Rotation without downtime.** Admin creates a **second active token**. Both are valid during overlap window (default 24 h). AsakAI redeploys with new token. Old token revoked via `POST /v1/admin/tokens/{id}/revoke`. `POST /v1/admin/tokens/rotate` returns new token in one call.
5. **Revocation.** Token disabled ≤ 60 s after revoke; subsequent calls return `401 auth_failed`.

---

## 9. KVKK / Data Processing

| Item | Value |
|---|---|
| Veri sorumlusu | **AsakAI (VDD Vakıf Mağaza)** |
| Veri işleyen | **İmga AI** |
| Yasal dayanak | KVKK m.5/2 (sözleşmenin ifası) + tenant DPA |
| **Veri ikametgahı (v1.1)** | **Use-case-bazlı Hybrid** — bkz. tablo altta |
| İşleme amacı | KPI analizi, müşteri destek yanıtı taslakları, kargo/iade örüntüleri |
| Aktarılan alan | `context` payload'ları; PII scrubbing AsakAI tarafında yapılır — İmga PII geldiğinde reddedip 400 `invalid_input` döner (opsiyonel `X-Imga-PII-Mode: hash` — İmga hash uygular) |
| Saklama | İmga tarafında **azami 30 gün** (log + prompt/response), sonra sabit silme; model eğitiminde kullanılmaz |
| Silme talebi | `DELETE /v1/data/{session_id}` — 24 saat içinde tamamlanır, 202 döner |
| Erişim | AsakAI → `GET /v1/data/export?from=...&to=...` (JSONL export) |
| Alt-işleyen | Use-case bazlı; DPA Ek-B'de her use_case → provider bölgesi eşleşmesi listelenir |
| Şifreleme | TLS 1.3 in-transit; AES-256 at-rest |

**Residency tablosu (KVKK-kritik):**

| Use case | PII sınıfı | Zone (kanonik) | AsakAI'nin opt-out yolu |
|---|---|---|---|
| `anomaly-explain` | Yok (agrega) | `outbound` — yurt dışı LLM OK | — |
| `cargo-optimize` | Yok (agrega) | `outbound` | — |
| `return-analyze` | Yok (agrega + ürün) | `outbound` | — |
| `ticket-analyze` | **Var** (mesaj gövdesi) | `tr` **zorunlu** | Yok — override edilemez |
| `ticket-suggest-reply` | **Var** (profil + mesaj) | `tr` **zorunlu** | Yok — override edilemez |
| `free-analyze` | Kullanıcı-bağımlı | `tr` (varsayılan) | `Accept-Residency: outbound-ok` header (KVKK m.9 açık rıza şart) |

`processed_in` alanı (§3 response envelope) her yanıtta gerçekten hangi bölgede işlendiğini bildirir. Yukarıdaki tabloyla uyuşmayan yanıt = **contract violation**; AsakAI CI bunu nightly kontrol edecek.

---

## 10. Curl Examples

**Anomaly explain**
```bash
curl -X POST https://api.imga.ai/v1/analyze/anomaly-explain \
  -H "Authorization: Bearer $IMGA_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id":"asakai-prod","use_case":"anomaly-explain",
    "period":"week","period_start":"2026-06-22","period_end":"2026-06-28",
    "language":"tr","client_request_id":"9c1b...",
    "context":{
      "kpi_snapshot":[{"metric":"siparis","value":184,"unit":"adet"}],
      "delta_vs_previous":[{"metric":"siparis","delta_pct":-12.4,"sign":"down"}],
      "known_events":["kurban bayramı arifesi"]
    }
  }'
```

**Ticket analyze**
```bash
curl -X POST https://api.imga.ai/v1/analyze/ticket-analyze \
  -H "Authorization: Bearer $IMGA_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"tenant_id":"asakai-prod","use_case":"ticket-analyze","period":"day",
       "period_start":"2026-07-01","period_end":"2026-07-01","language":"tr",
       "client_request_id":"a1...","context":{"ticket_id":"T-8821",
       "ticket_text":"Kargo 5 gündür gelmedi, iade istiyorum.","channel":"whatsapp"}}'
```

**Ticket reply suggest**
```bash
curl -X POST https://api.imga.ai/v1/analyze/ticket-suggest-reply \
  -H "Authorization: Bearer $IMGA_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"tenant_id":"asakai-prod","use_case":"ticket-suggest-reply","period":"day",
       "period_start":"2026-07-01","period_end":"2026-07-01","language":"tr",
       "client_request_id":"b2...","context":{"ticket_text":"Kargom gelmedi.",
       "tone":"özür","policy_snippets":["7 günden fazla geciken siparişte %10 iade"]}}'
```

**Return analyze**
```bash
curl -X POST https://api.imga.ai/v1/analyze/return-analyze \
  -H "Authorization: Bearer $IMGA_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"tenant_id":"asakai-prod","use_case":"return-analyze","period":"month",
       "period_start":"2026-06-01","period_end":"2026-06-30","language":"tr",
       "client_request_id":"c3...","context":{"returns_list":[
       {"order_id":"O-1","sku":"TSHIRT-M","reason_code":"beden","return_date":"2026-06-12","amount_try":249}]}}'
```

**Cargo optimize**
```bash
curl -X POST https://api.imga.ai/v1/analyze/cargo-optimize \
  -H "Authorization: Bearer $IMGA_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"tenant_id":"asakai-prod","use_case":"cargo-optimize","period":"day",
       "period_start":"2026-07-01","period_end":"2026-07-01","language":"tr",
       "client_request_id":"d4...","context":{
       "order":{"order_id":"O-42","sku":"KITAP-01","destination_city":"Van","weight_kg":1.2,"volume_dm3":3},
       "cargo_history":[{"carrier":"Aras","city":"Van","avg_delivery_days":4.1,"late_rate_pct":18}]}}'
```

**Free analyze (non-stream)**
```bash
curl -X POST https://api.imga.ai/v1/analyze/free-analyze \
  -H "Authorization: Bearer $IMGA_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"tenant_id":"asakai-prod","use_case":"free-analyze","period":"week",
       "period_start":"2026-06-22","period_end":"2026-06-28","language":"tr",
       "user_prompt":"Bu hafta neden ciro düştü, en çok hangi kategori etkilendi?",
       "client_request_id":"e5...","context":{"snapshot":{"ciro_try":184320,"onceki_ciro_try":210500}}}'
```

**Free analyze (SSE)**
```bash
TOK=$(curl -s -X POST https://api.imga.ai/v1/analyze/free-analyze/stream-token \
  -H "Authorization: Bearer $IMGA_API_TOKEN" -H "Content-Type: application/json" \
  -d '{...same envelope...}' | jq -r .stream_token)

curl -N "https://api.imga.ai/v1/analyze/stream?token=$TOK" \
  -H "Accept: text/event-stream"
```

---

*End of contract v1.0. Change log will live at `docs/imga-api-changelog.md` once v1.1 is drafted.*
