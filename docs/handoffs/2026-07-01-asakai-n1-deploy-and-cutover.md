# Handoff — AsakAI v1 partner API deploy + cutover (§3.11/§3.12)

**Tarih:** 2026-07-01 · **Yazar:** local-agent · **Hedef:** server-agent
**Durum:** open · **Öncelik:** yüksek · **Branch:** `docs/asakai-v1-n0-contract-freeze`

## Önemli: v1 AYNI api container'ında

Partner API için **yeni bir servis/compose yok** — `/v1/*` route'ları mevcut
FastAPI `api` servisine eklendi (main.py include_router). Deploy = mevcut api
image'ını yeniden build + yeni env + migration + Caddy route.

## 0. Ön-koşul: foundation `:5433`'te yeşil olmalı

Önce `2026-07-01-asakai-n1-auth-migration-0032.md` handoff'undaki doğrulama
(alembic 0032+0033+0034, canonical pytest, ruff, mypy, boot). Kırmızıysa DEPLOY ETME.

## 1. Env değişkenleri (`/etc/imga/{production,staging}/api.env`)

| Var | prod | staging | Not |
|---|---|---|---|
| `IMGA_TOKEN_PEPPER` | 64-hex A | 64-hex B (FARKLI) | `python -c "import secrets;print(secrets.token_hex(32))"`; secret store, repoya asla |
| `GEMINI_API_KEY` | sistem anahtarı | (aynı olabilir) | partner API sistem anahtarı kullanır (tenant cred değil) |
| `IMGA_ENV` | `production` | `staging` | önek + cross-env enforcement (production→imga_live_, staging→imga_stg_) |
| `IMGA_GEMINI_MODEL` | (ops.) | (ops.) | default `gemini-3-flash-preview` |

> **Blokaj:** `GEMINI_API_KEY` + `IMGA_TOKEN_PEPPER` değerleri VDD tarafında
> sağlanmalı (local-agent üretemez/görmemeli).

## 2. Build + migrate + deploy (her ortam)

```bash
git pull origin main   # (branch merge sonrası)
ENV=staging   # sonra production
COMPOSE=/opt/imga/infra/imga/$ENV/docker-compose.yml
sudo docker compose -f $COMPOSE build api
sudo docker compose -f $COMPOSE up -d api
sudo docker compose -f $COMPOSE exec api alembic upgrade head   # 0031→0034
```

## 3. Caddy route (shared Caddy, `/opt/shared/caddy/conf.d/imga-*.conf`)

```
api-staging.imga.ai {
    reverse_proxy imga-staging-api:8000   # staging api container
    tls { ... }   # TLS 1.3
}
api.imga.ai {
    reverse_proxy imga-prod-api:8000
    tls { ... }
}
```
`caddy reload`. (Healthcheck 127.0.0.1 kuralı — CLAUDE.md.)

## 4. Bootstrap: ilk ops token (tavuk-yumurta)

`/v1/admin/*` opsBearer ister ama ilk ops token yok. Tek seferlik mint + INSERT:

```bash
# 1) plaintext + hash üret (api container içinde, IMGA_TOKEN_PEPPER env'li):
sudo docker compose -f $COMPOSE exec api python -c \
"from imga_api.security.api_tokens import mint_token, OPS_LIVE_PREFIX; import os; \
t=mint_token(prefix=(OPS_LIVE_PREFIX if os.environ['IMGA_ENV']=='production' else 'imga_ops_stg_'), pepper=os.environ['IMGA_TOKEN_PEPPER']); \
print('TOKEN', t.plaintext); print('HASH', t.token_hash); print('PREFIX', t.token_prefix); print('LAST4', t.last4)"

# 2) admin_tokens'a INSERT (imga_owner/imga_admin ile; admin_tokens deny-all RLS):
INSERT INTO admin_tokens(token_prefix, token_hash, last4, scope, label, expires_at)
VALUES('<PREFIX>', '<HASH>', '<LAST4>', 'ops', 'bootstrap', now() + interval '365 days');
```
`TOKEN`'ı VDD Ops'a güvenli kanalla ilet. Bu token ile `POST /v1/admin/tenants`
(asakai-prod / asakai-staging) + `POST /v1/admin/tokens/rotate` ile tenant token'ları mint.

## 5. Log + uptime + arka plan job'ları

- Log: JSON structured (request_id, tenant_id, use_case, latency_ms, status,
  processed_in). **Prompt/response BODY log'a YAZILMAZ** — kod zaten yalnız hash yazar.
- Uptime robot: `GET https://api-staging.imga.ai/v1/health` her 60 sn (§11.1, MIN %99.5).
- **İki yeni APScheduler job'u** (api lifespan'de, boot log'unda görünür):
  - `provider-healthcheck` (60sn) — Gemini `health_check` (ping). Doğrula:
    `GET /v1/health` → `status:"ok"` + `providers[0].healthy:true` (GEMINI_API_KEY
    geçerliyse). Anahtar geçersiz/eksik → `status:"degraded"` beklenir. Boot log:
    `scheduler: provider healthcheck every 60s`.
  - `data-retention-purge` (24s) — 30 günü aşmış `api_request_log` hard-delete +
    `data_purge_audit` satırı. Boot'ta idempotent bir kez koşar (taze DB'de 0 satır).
    Boot log: `scheduler: data retention purge every 24h`. Doğrula:
    `SELECT count(*) FROM data_purge_audit;` ≥ 1 (boot koşusu kanıtı).

## 6. Cutover (§3.12)

1. Staging 7 gün yeşil (uptime + AsakAI nightly contract test) → prod'a çıkmadan
   **48 saat önce** AsakAI'ye sinyal (bu kanal).
2. AsakAI: `VDD_IMGA_MOCK=0` + admin panelden URL/Bearer/tenant.
3. Cutover sonrası 24 saat prod smoke: hata < %0.5, p95 < 3.5s, enjekte 502 → AsakAI banner.

## 7. Duvar-saati / user blokajları (local-agent YAPAMAZ)

- 7-gün kesintisiz staging uptime · 7-ardışık-gün nightly CI yeşil · 7-gün p95 ortalaması
  — **zaman geçmesi gerekir**, kodla "şimdi" tamamlanmaz.
- Load test (10 req/s×10dk) gerçek altyapıda.
- `GEMINI_API_KEY` + `IMGA_TOKEN_PEPPER` provizyonu.
- DPA imzası (VDD hukuk).

## 8. Kod tarafında durum (2026-07-01 güncel)

**Yazıldı + push edildi** (branch `docs/asakai-v1-n0-contract-freeze`):

- §3.4 SSE `free-analyze/stream-token` + `/stream` (iki-adım handshake) — `24858ff`.
- §3.5 provider healthcheck job (60sn) + canlı `/v1/health` — `abe5594`.
- §3.8 30-gün KVKK retention purge job (günlük) — `0d00d09`.
- §3.10 **birim-seviyesi** contract test (`tests/contract/`: envelope + error taxonomy
  + use-case şema + 422 mapper, ham-gövde sızıntı testi) — `af0fa38` + `3de08e8`.
  Canonical pytest listesinde; yerelde conftest-baypas ile tüm assertion PASS.
- Rafinman TAMAM: 422→AnalyzeError(400) /v1 mapper (`3de08e8`) · per-tenant kota
  override okuma (`67f41b8`).

**Foundation `:5433` yeşili sonrası (fixture bağımlı — server-agent):**

- §3.10 **endpoint-seviyesi** suite: `test_auth_scopes` · `test_headers` (10 header
  matrisi) · `test_idempotency` (mock Gemini spy) · `test_revocation_sla` (≤60s) ·
  `test_cross_env_prefix` · `test_sse_meta_residency`. Bunlar canlı app + DB + Redis
  fixture ister; birim testler zaten şekil değişmezlerini kilitledi.
- SSE gerçek token-by-token stream: şu an non-stream sonucu parçalanıyor (event
  ŞEKLİ tam); `generate_content_stream` entegrasyonu ilk-token<800ms için rafinman.
