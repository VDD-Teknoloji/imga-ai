# İmga API v1 — Contract Specification

**Status:** Draft **v1.3** (residency Hybrid geri alındı — VDD sahibi kararıyla tüm use-case'ler outbound/Gemini) · **Owner:** İmga AI · **Consumer:** AsakAI (VDD) · **Effective:** 2026-Q3

**v1.3 değişiklikleri** (2026-07-01 son revizyon, VDD sahibi direktifi):
- **§9 residency tablosu revize.** Hybrid strateji + TR-zorunluluk + Accept-Residency opt-out düştü. VDD tek sahibinin kararı: tüm use-case'ler `outbound` bölgesinde işlenir. Backend model olarak **Gemini** kanonik (İmga router'ı OpenAI/Anthropic'e de anahtarlayabilir — tenant config). AsakAI KVKK aydınlatma metninin kapsadığı şekilde çalışır; kullanıcı akışına ek m.9 açık rıza konmaz.
- **§4A.1 residency_locks alanı yorumu değişti.** Artık "tr zorunlu use-case'e izin verme" için değil, ileride bir tenant "outbound yasak" derse override için kullanılır. Varsayılan tüm use-case'ler outbound.
- **§5 residency_denied error code** korunur ama şu an tetiklenmez (future-proof).
- Brief §5.1 (Hybrid tablosu) ve §5.2 (T3AI/TİDE managed karar) geri alındı — birlikte push edildi.

**v1.2 değişiklikleri** (İmga N+0 turn 3 raporu + AsakAI adversaryal completeness sweep 2026-07-01):

İmga tarafında flag'lenen 3 çelişki:
- **§8.5 Revocation** — normative MUST ≤60s + advisory SHOULD ≤5s + threat model split (RFC-2119 stil).
- **§7 SSE meta** — `processed_in` alanı eklendi; §9 residency audit'i SSE'de de çalışır.
- **§8.1 Issuance** — Stripe-style env-prefix scheme (`imga_live_` prod / `imga_stg_` staging) + edge cross-env enforcement.

AsakAI completeness sweep'inde yakalanan 8 boşluk (5 high, 3 med) kapatıldı:
- **§2 ↔ §4.6** — `user_prompt` §4.6 için normatif olarak zorunlu; envelope'da opsiyonel kalır (§2 not).
- **§2.1 (yeni)** — Idempotency semantics: 24h replay penceresi, `meta.cached=true`, `Idempotency-Replayed` header.
- **§3.5 (yeni)** — Consolidated Header Reference tablosu.
- **§4.7 / §4A (yeni)** — `/v1/health` + Admin Surface (tenants/tokens/usage) tam şema.
- **§4.8 / §4.9 (yeni)** — `DELETE /v1/data/{session_id}` + `GET /v1/data/export` tam şema.
- **§5** — `403 residency_denied` error code eklendi.
- **§11 (yeni)** — Acceptance Criteria bölümü (brief §7'den contract'a normatif olarak taşındı).
- **§1** — Versioning `Accept` header seçeneği tamamen kaldırıldı; URL-path only.
- **§4.2** — `language_detected` BCP-47 + envelope `language` her zaman kazanır (source of truth).

v1.1 değişiklikleri (İmga kickoff-review 2026-07-01'e yanıt):
- `meta.model` alanı prod'da opak kod döner (§3); açık model kimliği yalnız staging.
- §9 KVKK residency tablosu Hybrid stratejiye güncellendi (bkz. brief §5.1).
- §8 auth: `IMGA_API_TOKEN` → vault (`SETTING_IMGA_API_KEY` — Sprint 13'te AsakAI'de zaten uygulandı).

---

## 1. Base

| Item | Value |
|---|---|
| Base URL (prod) | `https://api.imga.ai/v1` |
| Base URL (staging) | `https://api-staging.imga.ai/v1` |
| Versioning | **URL path only** (`/v1`, `/v2`); breaking changes → new major mount point. `Accept: application/vnd.imga.v2+json` **NOT supported** — brief §2'deki taslak öneri v1.2'de reddedildi (single-strategy, CDN/gateway kolay). |
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

> **`user_prompt` semantik (§2 ↔ §4.6 çelişkisi kapatıldı, v1.2).** Envelope'da `user_prompt?: string` opsiyoneldir; ancak `use_case === "free-analyze"` ise **normatif olarak zorunludur** — boş/eksik olursa İmga `400 invalid_input` döner (`error.details = {field: "user_prompt", reason: "required_for_free_analyze"}`). Diğer 5 use-case için `user_prompt` opsiyoneldir ve varsa system prompt'a ek talimat olarak enjekte edilir. Contract test suite bu davranışı doğrulamak zorundadır.

---

## 2.1 Idempotency (v1.2)

Envelope'un `client_request_id` (UUIDv4) alanı **idempotency key**'dir:

- **Pencere:** İmga her `(tenant_id, client_request_id)` ikilisi için yanıtı **24 saat** cache'ler.
- **Replay semantik:** Aynı `client_request_id` ile ikinci istek geldiğinde:
  - Yanıt gövdesi **byte-identical** döner (aynı `request_id` değeri, aynı `response`, aynı `meta.tokens`, aynı `meta.cost_try`).
  - `meta.cached = true` işaretlenir (§3).
  - Response header `Idempotency-Replayed: true` eklenir.
  - **LLM tekrar çağrılmaz** — cost_try double-charge OLMAZ (§6 kota da azalmaz).
- **Retryable hatalar** (`timeout`, `provider_error`): fresh execution — cache'te "hata cache'lenir mi?" kuralı: **hayır**, yalnız `ok: true` yanıtlar cache'lenir. `retry` sonrası başarılı yanıt cache'e girer.
- **Non-retryable hatalar** (`invalid_input`, `auth_failed`, `residency_denied`): cache'lenmez; retry aynı hatayı üretir.
- **SSE etkileşimi** (§7): step-1 `POST /stream-token` idempotency sınırıdır (aynı `client_request_id` aynı stream_token'ı iade eder). Step-2 `GET /stream` **idempotent değildir** — her çağrı stream başlatır; stream_token 60s TTL, tek kullanımlık.
- **Tenant izolasyonu:** `client_request_id` tenant başına scope'ludur — iki farklı tenant aynı UUID'yi göndermek serbestir.

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

## 3.5 Header Reference (v1.2 — consolidated)

Header'lar önceden §6/§9/brief §3.4'e dağılmıştı; bu tablo tek referans:

### Request headers

| Header | Zorunlu | Değer | Semantik |
|---|---|---|---|
| `Authorization` | ✅ | `Bearer <token>` | §8 (tenant Bearer veya opsBearer — endpoint-specific) |
| `Content-Type` | ✅ (POST) | `application/json; charset=utf-8` | §1 |
| `Accept-Language` | opsiyonel | `tr-TR` (default) \| `en-US` | §1 |
| `Accept-Residency` | opsiyonel | `outbound-ok` | Yalnız `free-analyze` (§9); diğerlerinde 403 `residency_denied` |
| `X-Imga-PII-Mode` | opsiyonel | `hash` | İmga PII'yi hash'ler (§9). Default: PII kabul edilmez, 400 döner. |

### Response headers

| Header | Ortam | Değer | Bölüm |
|---|---|---|---|
| `X-Imga-Request-Id` | prod + staging | UUIDv4 | §3 (error correlation) |
| `X-RateLimit-Remaining` | her yanıt | integer | §6 |
| `X-RateLimit-Reset` | her yanıt | unix_ts | §6 |
| `X-Quota-Tokens-Remaining` | her yanıt | integer | §6 |
| `X-Quota-Reset` | her yanıt | unix_ts (00:00 Europe/Istanbul) | §6 |
| `X-Imga-Tokens-Used` | başarılı 2xx | integer | §6 |
| `Retry-After` | 429/503 | integer seconds | §5 (`retry_after_seconds` ile aynı) |
| `Idempotency-Replayed` | cache hit | `true` | §2.1 |
| `X-Imga-Next-Cursor` | §4.9 pagination | opak string | §4.9 |
| `X-Imga-Provider` | **staging only** | opak kod (`prov_a`, `prov_tr_1`) | §3, brief §3.4 — prod'da GÖNDERİLMEZ |

---

## 4. Use Case Endpoints

All are `POST /v1/analyze/{use_case}`. Only the `context` and `response` fields differ. Ek olarak §4.7 (health), §4A (admin), §4.8/9 (data lifecycle) — hepsi §4 kapsamındadır.

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

> **language / language_detected (v1.2).** `language_detected` **BCP-47** formatındadır (`"tr"`, `"ar-SA"`, `"en-US"`). Envelope `language` (§2, `"tr" | "en"`) her zaman **kazanır** — yanıt bu dilde üretilir. `language_detected` yalnız observability için doldurulur (ör. ticket Arapça yazılmış ama caller Türkçe yanıt istemişse). İki alan uyuşmazsa `response.warnings` dizisine `"language_mismatch: detected=ar-SA, response=tr"` eklenir; hata değildir.

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
**Context:** `{ snapshot: Record<string, unknown>; hints?: string[] }`
**Envelope requirement:** `user_prompt` **NORMATİVE OLARAK ZORUNLUDUR** bu use-case için — §2 not paragrafına bakınız; eksikse `400 invalid_input`.
**Response:** `{ answer_markdown: string; charts_suggested?: {kind:"line"|"bar"|"pie"; series:string[]}[]; follow_up_prompts: string[] }`

---

### 4.7 `GET /v1/health` — Liveness + provider durumu

- **Auth:** yok (public, unauth). Ops monitoring / uptime robot.
- **Response:**
  ```ts
  interface HealthResponse {
    status: "ok" | "degraded" | "down";
    version: string;             // "1.2.3" — İmga servis versiyonu
    region: "tr" | "outbound";   // İmga bu yanıtı üreten node'un bölgesi
    providers: {                 // opak; AsakAI karar için değil observability için
      zone: "tr" | "outbound";
      healthy: boolean;
      last_checked_at: string;   // ISO-8601
    }[];
  }
  ```
- `status: "degraded"` → bazı provider'lar down; İmga fallback ile yanıt vermeye devam eder.
- `status: "down"` → hiçbir provider erişilebilir değil; analyze endpoint'leri 502 döner.

---

### 4A. Admin Surface — VDD Ops uçları (v1.2)

Admin endpoint'leri **ayrı Bearer scheme** kullanır (§8 opsBearer). Tenant token'ı bu yollara erişemez → `403 auth_failed`.

#### 4A.1 `POST /v1/admin/tenants` — tenant oluştur
- **Auth:** opsBearer
- **Request:** `{ name: string; contact_email: string; quota_tokens_per_day?: number; residency_locks?: Partial<Record<UseCase, "tr" | "outbound">> }`
- **Response:** `{ tenant_id: string; created_at: string }`

#### 4A.2 `GET /v1/admin/tenants/{tenant_id}/usage` — kota + faturalama
- **Auth:** opsBearer **veya** tenant Bearer (kendi tenant'ı için)
- **Query:** `from=ISO`, `to=ISO`, `group_by=day|week|month|use_case`
- **Response:**
  ```ts
  interface UsageResponse {
    tenant_id: string;
    window: { from: string; to: string };
    totals: {
      requests: number;
      tokens_in: number;
      tokens_out: number;
      cost_try: number;
    };
    breakdown: {
      bucket: string;              // ISO date or use_case name
      requests: number;
      tokens_in: number;
      tokens_out: number;
      cost_try: number;
    }[];
  }
  ```

#### 4A.3 `POST /v1/admin/tokens/rotate` — kesintisiz rotation
- **Auth:** opsBearer
- **Request:** `{ tenant_id: string; overlap_window_hours?: number }` (default 24, max 72)
- **Response:** `{ new_token: string; new_token_id: string; old_token_expires_at: string }`
- `new_token` **yalnız bu yanıtta** açık gösterilir; sonrasında hash lookup'tan başka yol yoktur.
- Yeni token contract §8.1 prefix şemasını izler (aynı ortam: prod token rotate → prod token, staging → staging).

#### 4A.4 `POST /v1/admin/tokens/{token_id}/revoke` — token iptal
- **Auth:** opsBearer
- **Response:** `{ revoked_at: string; propagation_deadline: string }` (deadline = revoked_at + 60s, §8.5 normative).
- Yanıttan sonra §8.5 propagation SLA'sı işler.

#### 4A.5 `GET /v1/admin/tokens?tenant_id=...` — aktif token listesi
- **Auth:** opsBearer
- **Response:**
  ```ts
  interface TokenListResponse {
    tokens: {
      token_id: string;
      prefix: string;         // "imga_live_" or "imga_stg_"
      label?: string;
      created_at: string;
      expires_at: string;     // 1 yıl max, NULL yok
      last_used_at?: string;
      scope: "tenant" | "service_account";
    }[];
  }
  ```
- Token hash'i **hiçbir zaman** döndürülmez — yalnız prefix + metadata.

---

### 4.8 `DELETE /v1/data/{session_id}` — KVKK erasure (v1.2)

- **Auth:** tenant Bearer (yalnız kendi tenant'ının session'ı)
- **Response:** `202 Accepted`
  ```ts
  interface EraseResponse {
    ok: true;
    purge_job_id: string;   // UUIDv4 — audit için
    session_id: string;
    eta_seconds: number;    // MAX 86400 (24 h)
  }
  ```
- Purge async yürütülür; `purge_job_id` `tenant_deletion_audit` tablosuna yazılır.
- Session bulunamazsa `404 session_not_found`.
- Silme tamamlandığında (job DONE), aynı session_id ile yeni istek `404 session_not_found` döner — replay değil.

---

### 4.9 `GET /v1/data/export` — KVKK access right (v1.2)

- **Auth:** tenant Bearer
- **Query:** `from=ISO`, `to=ISO`, `use_case?=...`, `cursor?=<opaque>`
- **Response:** `Content-Type: application/x-ndjson`; her satır bir JSON record:
  ```ts
  interface ExportRecord {
    request_id: string;
    session_id?: string;
    tenant_id: string;
    use_case: UseCase;
    created_at: string;
    context_hash: string;       // SHA-256 — body kalıcı saklanmadığı için hash döner
    response_summary: string;   // 200 chars max — full body 30 gün sonra silinir
    processed_in: "tr" | "outbound";
    tokens_total: number;
    cost_try: number;
  }
  ```
- **Pagination:** yanıt header'ında `X-Imga-Next-Cursor: <opaque>` — client bir sonraki sayfa için query'ye ekler.
- **Max pencere:** `to - from ≤ 31 gün`; aşarsa `400 export_window_too_large`.

---

## 5. Error Taxonomy

| HTTP | `error.code` | When | Retry? |
|---|---|---|---|
| 400 | `invalid_input` | schema/enum/missing field (§2, §4.6 user_prompt dahil) | no — fix client |
| 400 | `export_window_too_large` | §4.9 `to - from > 31 gün` | no — narrow window |
| 401 | `auth_failed` | missing/expired/revoked token; hint alanı `wrong_environment` içerebilir (§8.1) | no — rotate |
| 403 | `residency_denied` | **v1.2** — `Accept-Residency: outbound-ok` header PII-kilitli use-case'e gönderildi (§9 tablo); `details = {requested_zone, required_zone, use_case}` | no — remove header |
| 404 | `session_not_found` | §4.8 DELETE için session yok veya zaten silindi | no |
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
data: {"tokens":{"prompt":842,"completion":57},"cost_try":0.0031,"processed_in":"tr"}

event: done
data: {"finish_reason":"stop","final_length":312}
```
Heartbeat every 15 s as SSE comment (`: ping`). Client SHOULD close after `event: done` or on any `event: error`.

> **`event: meta` normatif zorunluluk (v1.2).** Payload MUST içerir `processed_in: "tr" | "outbound"` — §3 `meta.processed_in` ile aynı semantik. §9 residency audit'i SSE'de bu alanla çalışır; AsakAI CI nightly kontrat testi hem stream hem non-stream response'lara aynı validator'ı uygular. Eksik olması = **contract violation**.

---

## 8. Authentication Flow

1. **Issuance.** İmga admin console mints per-tenant token with an **environment-scoped prefix** (Stripe `sk_live_` / `sk_test_` deseni):

   | Ortam | Prefix | Base URL (§1) | Örnek |
   |---|---|---|---|
   | Production | `imga_live_` | `https://api.imga.ai/v1` | `imga_live_<base64url_32>` |
   | Staging    | `imga_stg_`  | `https://api-staging.imga.ai/v1` | `imga_stg_<base64url_32>` |

   Delivered out-of-band (KVKK-compliant channel — no email in cleartext). Prefix, VDD Ops'un vault'a yapıştırırken **görsel doğrulaması** içindir; token gövdesi hâlâ 32-byte base64url random (prefix entropi kaybı sayılmaz).

   **Cross-environment enforcement (normatif).** İmga edge, isteğin geldiği host'la token prefix'ini karşılaştırır. Uyuşmazlık halinde (`imga_stg_...` → `api.imga.ai`, veya tersi) yanıt `401 auth_failed` olur ve `error.details.hint = "wrong_environment"` alanı **zorunlu** eklenir; log satırı staging↔prod karışmasını tek bakışta diagnoz edilebilir kılar. AsakAI prefix'i **parse etmez** — token `system_settings.py` vault'unda opak secret olarak durur (`backend/app/imga/client.py` bunu doğrudan `Authorization: Bearer` başlığına koyar); prefix client-side check değil, issuer-side güvenlik ağıdır. Rotation (§8.4) hiçbir zaman ortam sınırını aşmaz: overlap penceresindeki iki aktif token daima aynı prefix'i taşır.

2. **Storage.** AsakAI stores it via `system_settings.SETTING_IMGA_API_KEY` (Sprint 13'te AES-256 Fernet vault; `backend/app/imga/client.py:_load_config`).
3. **Usage.** `Authorization: Bearer imga_live_...` (prod) veya `Bearer imga_stg_...` (staging) on every request.
4. **Rotation without downtime.** Admin creates a **second active token** (aynı prefix). Both are valid during overlap window (default 24 h, max 72 h — §4A.3). AsakAI redeploys with new token. Old token revoked via `POST /v1/admin/tokens/{id}/revoke`. `POST /v1/admin/tokens/rotate` returns new token in one call.
5. **Revocation.**
   - **Normative (MUST).** Revoked token disabled ≤ **60 s** after `POST /v1/admin/tokens/{id}/revoke`; subsequent calls return `401 auth_failed`. AsakAI CI SHALL verify this window in a nightly job (revoke → poll old token every 5 s → assert 401 within 60 s). Exceeding 60 s = contract violation.
   - **Advisory (SHOULD).** İmga targets ≤ **5 s** in single-region hot-path as an internal SLO — **not** a contract guarantee. Cross-region cache propagation may extend propagation toward the 60 s ceiling. AsakAI operational monitoring MAY alert on p95 revoke-propagation > 10 s as an early-warning signal before contract breach.
   - **Threat model.** Between revoke and full propagation, a compromised token remains usable but is bounded by §6 rate-limit (60 req/min per tenant) — worst-case residual attack surface ≈ 60 requests. For suspected mass exfiltration, AsakAI SHOULD rotate the tenant token in parallel with revocation (§8.4) rather than relying on revocation timing alone.

### 8.6 Admin Bearer Scheme (opsBearer, v1.2)

Admin endpoint'leri (§4A) tenant Bearer'ıyla erişilemez. VDD Ops kendi opsBearer token'larını kullanır:

- Prefix: `imga_ops_live_<base64url_32>` (prod) / `imga_ops_stg_<base64url_32>` (staging).
- Ayrı DB tablosu (`admin_tokens`) — RLS tenant_id sınırlaması yok, ancak `scope = "ops"` enforce.
- Tenant scope'lu Bearer bir `/v1/admin/*` uç noktası çağırırsa `403 auth_failed` (`hint: "tenant_scope_cannot_access_admin"`).
- opsBearer bir tenant analiz endpoint'i çağırırsa `403 auth_failed` (`hint: "ops_scope_cannot_impersonate_tenant"` — audit hijack koruması).
- Rotation ve revocation §8.4/8.5 kurallarına uyar.

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

**Residency tablosu (v1.3 — VDD sahibi kararıyla düzleştirildi):**

| Use case | PII sınıfı | Zone (kanonik) | Not |
|---|---|---|---|
| `anomaly-explain` | Yok (agrega) | `outbound` (Gemini kanonik) | — |
| `cargo-optimize` | Yok (agrega) | `outbound` | — |
| `return-analyze` | Yok (agrega + ürün) | `outbound` | — |
| `ticket-analyze` | Var (mesaj gövdesi) | `outbound` | AsakAI KVKK aydınlatma metni kapsamında; PII scrubbing best-effort |
| `ticket-suggest-reply` | Var (profil + mesaj) | `outbound` | Aynı |
| `free-analyze` | Kullanıcı-bağımlı | `outbound` | — |

`processed_in` alanı (§3 response envelope) enum'u hâlâ `"tr" | "outbound"` — v1.3'te varsayılan tüm use-case'ler `outbound` döner. `tr` değeri gelecekte bir tenant self-host/TR-model isterse (Sprint 15+) reserve edilmiş durumda; şimdi kullanılmıyor. `Accept-Residency` header'ı contract'ta tanımlı kalır ama v1.3'te no-op — İmga tarafı sessizce yok sayar (400 döndürmez).

AsakAI CI nightly contract testi bu tabloyu doğrular: her use-case yanıtında `meta.processed_in == "outbound"`; sapma = contract violation (İmga tarafında router config regresyonu).

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

---

## 11. Acceptance Criteria (v1.2 — brief §7'den normatif olarak taşındı)

AsakAI prod'da `VDD_IMGA_MOCK=0` bayrağını **şu 6 koşul birlikte sağlandığında** açacaktır:

1. **Uptime.** İmga staging'de 7 gün kesintisiz uptime (uptime robot 60 sn interval, MIN 99.5%).
2. **Contract test suite.** AsakAI nightly'de 7 ardışık gün %100 yeşil. Test kapsamı:
   - Envelope shape (§2, §3)
   - Error taxonomy (§5 tüm codes)
   - Header reference (§3.5 tam matrisi)
   - Residency zone declaration (§9 tablo × yanıt `processed_in`) — non-stream + SSE
   - Idempotency replay (§2.1)
   - Revocation SLA ≤60s (§8.5 normative)
   - Cross-env prefix rejection (§8.1 wrong_environment)
3. **Latency SLA.** p95 < 3 s (non-stream, 7 gün ortalama) · ilk token < 800 ms (SSE, 7 gün ortalama).
4. **KVKK compliance.**
   - DPA imzalı (VDD hukuk + İmga hukuk).
   - Veri ikametgahı doğrulaması: ticket-* endpoint'lerine traceroute kanıtı (yanıt üreten IP TR ASN'de).
   - §4.8 DELETE + §4.9 GET data lifecycle uçları prod'da çalışıyor.
5. **Billing observability.** `/v1/admin/tenants/asakai-prod/usage` (§4A.2) ile kota + fatura AsakAI admin panelinden okunabiliyor; son 30 gün breakdown by use_case.
6. **Graceful degradation.** İmga 502/503 dönerse AsakAI kullanıcıya "AI şu an kullanılamıyor" gösterir, çökmez (client'ta `ImgaUpstreamError` → HTTP 502 → UI banner). Testte enjekte edilmiş 502 senaryosu ile 24 saat prod smoke içinde en az 1 kez doğrulanmış olmalı.

---

*End of contract v1.3 (2026-07-01). Change log her revizyonda header'a taşınır; ayrı changelog dosyası açılmayacak (contract-first, tek dosya normatif kaynak).*
