# İmga v1.3 partner API — Geliştirme Teslim Raporu

**Tarih:** 2026-07-01 · **Yazar:** İmga local-agent · **Alıcı:** AsakAI ajanı → sunucu-ajanı
**Branch:** `main` (`0a174c4`, origin ile senkron) · **Durum:** geliştirme TAMAM + doğrulandı

> Bu rapor "kod tarafı bitti" teslimidir. §6'daki **canlı-metrik** raporu (uptime,
> p95, hata%) prod ayağa kalkıp ölçüm alınınca ayrıca yazılacak — buradaki hiçbir
> sayı uydurma değil, hepsi ölçülmüş test sonucu.

---

## 1. Tek cümle

AsakAI için İmga v1.3 partner API'nin **tüm kodu (§3.1–3.10) yazıldı, gerçek
Postgres+Redis'e karşı doğrulandı (633 test yeşil), main'e merge+push edildi** ve
deploy tek komuta indirgendi. Kalan: sunucu-ajanı deploy + secret, hukuk DPA imza,
prod-sonrası load test (bende). **Karar (owner):** staging atlanıyor, doğrudan prod.

## 2. Ne teslim edildi (kanıtlı)

**Doğrulama:** `infra/imga/test/docker-compose.yml` (pgvector'lü container, gerçek
Postgres :5433 + Redis) koşuldu → **633 passed, 2 skipped**; migration **0032→0033→0034
gerçek Postgres'e uygulandı** (RLS+FORCE tablolar). Bu koşumda gerçek bir prod-çökmesi
bug'ı bulundu+düzeltildi (`partner_analyze` yanlış import → tüm api boot çökerdi; `47a11b0`).

| §  | İş | Dosya(lar) | Durum |
|----|----|-----------|-------|
| 3.1 | Auth (token + çift-yol + admin routes) | `security/api_tokens.py`, `services/api_tokens.py`, `v1/auth.py`, `v1/admin_tokens.py`, migration `0032` | ✅ test yeşil |
| 3.2 | Tenant + kota admin | `v1/admin_tenants.py`, migration `0033` | ✅ |
| 3.3 | 6 analyze + Gemini | `v1/analyze.py`, `services/partner_analyze.py`, `v1/prompts.py`, `v1/envelope.py` | ✅ |
| 3.4 | free-analyze SSE | `v1/stream.py` | ✅ |
| 3.5 | Health + provider healthcheck (60sn) | `v1/health.py`, `services/provider_health.py`, `workers/scheduler.py` | ✅ |
| 3.6 | Rate limit + kota header | `v1/ratelimit.py` (+ per-tenant kota bağlı) | ✅ |
| 3.7 | Idempotency (Redis 24h) | `v1/idempotency.py` | ✅ |
| 3.8 | KVKK DELETE/export + 30-gün purge | `v1/data.py`, `services/data_retention.py`, migration `0034` | ✅ |
| 3.9 | Error taxonomy + 422→AnalyzeError | `v1/errors.py` | ✅ |
| 3.10 | Contract testler (birim + kara-kutu) | `tests/contract/*`, `docs/asakai-ci/nightly-contract.yml` | ✅ birim yeşil; kara-kutu canlıya karşı |

**Artifact'lar:** k6 load test (`infra/imga/loadtest/v1_analyze_load.js`), DPA taslağı
(`docs/legal/2026-07-01-imga-asakai-dpa-draft.md`), deploy+bootstrap script'leri
(`infra/imga/deploy-partner-api.sh`, `bootstrap-ops-token.sh`), nightly CI workflow.

## 3. Sunucu-ajanı için deploy (DOĞRUDAN PROD — owner kararı)

Secret'lar sunucu-ajanı tarafında sağlanacak. `/etc/imga/production/api.env`:
```
IMGA_TOKEN_PEPPER=<64-hex, prod'a özel>      # python -c "import secrets;print(secrets.token_hex(32))"
GEMINI_API_KEY=<Google AI Studio sistem anahtarı>
IMGA_ENV=production
```
Sonra (repo `/opt/imga`, main güncel):
```bash
cd /opt/imga && git pull origin main
sudo IMGA_ENV=production bash infra/imga/deploy-partner-api.sh    # secret fail-fast → build → alembic 0031-0034 → /v1/health smoke
sudo IMGA_ENV=production bash infra/imga/bootstrap-ops-token.sh   # ilk ops token (BİR KEZ basar → sakla)
```
Caddy: `api.imga.ai → api:8000` (TLS 1.3) — sunucu-ajanı `/opt/shared/caddy/conf.d/`'de
halleder. Uptime robot: `GET https://api.imga.ai/v1/health` / 60sn.

**Beklenen `/v1/health`:** `status:"ok"` + `providers[0].healthy:true` (GEMINI_API_KEY
geçerliyse). `degraded` → anahtar/erişim sorunu.

## 4. AsakAI ajanı için cutover zinciri

Sunucu-ajanı ops token'ı verdikten sonra (opsBearer):
```
POST /v1/admin/tenants            {name:"AsakAI Prod", ...}  → tenant_id: asakai-prod
POST /v1/admin/tokens/rotate      (tenant=asakai-prod)       → tenant Bearer (imga_live_…) BİR KEZ
POST /v1/admin/tenants/asakai-prod/quota  {quota_tokens_per_day: 2000000}   # opsiyonel, default 2M
```
Sonra AsakAI: `VDD_IMGA_MOCK=0` + admin panelde URL (`https://api.imga.ai`) + Bearer +
tenant. Doğrulama: `GET /v1/health` 200, bir `POST /v1/analyze/free-analyze` 200 zarf.

## 5. Açık kalemler + kimde

| Kalem | Kimde | Not |
|-------|-------|-----|
| Secret provizyonu + deploy execution | sunucu-ajanı | script'ler hazır |
| Caddy route (api.imga.ai TLS 1.3) | sunucu-ajanı | |
| DPA imza | VDD hukuk | taslak hukukta (owner verdi) |
| Load test koşumu + p95/SSE metrikleri | **İmga local-agent (ben)** | prod canlı olunca k6 koşarım |
| §6 canlı-metrik raporu | **ben** | prod + ölçüm sonrası |
| Enjekte-502 graceful smoke | sunucu-ajanı / ben | prod smoke |

## 6. Owner kararının §2'ye etkisi (dürüst not)

Orijinal §2, prod'dan önce **staging 7-gün soak + §3.12 48h sinyal** istiyordu. Owner
"staging atla, doğrudan prod" dedi → §2'nin (2)(3)(4) maddeleri "7-gün staging" biçiminde
KARŞILANMAYACAK; yerine prod'da canlı-izleme + load test ile eşdeğer güvence sağlanır.
Bu owner kararıdır; ben yalnız kayda geçiriyorum. Öneri: prod'a çıktıktan sonra ilk
24 saat yakın izleme + enjekte-502 smoke ile §7 (graceful degradation) doğrulansın.

## 6.1 Bilinen sınır / v1.4 refinement — SSE gerçek token-streaming

**Karar (local-agent mühendislik önerisi, geri alınabilir):** §2.4'ün "SSE ilk-token
<800ms" alt-kriteri için **gerçek Gemini token-streaming v1.4'e ertelendi.** Gerekçe:
- SSE endpoint'i **fonksiyonel canlı ve kontrat-uyumlu** — `partial`/`meta`/`done`
  event ŞEKLİ doğru (cutover E-serisi ile prod'da çalışır durumda). Eksik olan yalnız
  TTFT (<800ms) performans hedefi; şu an tam yanıt parçalara bölünüyor.
- Gerçek `generate_content_stream` çağrısı **yerelde doğrulanamaz** (`google-genai`
  local'de kurulu değil + Gemini anahtarı yok). Doğrulanmamış streaming kodunu CANLI
  prod entegrasyonuna (gerçek AsakAI trafiği) kör göndermek, bu projede 3 gerçek bug'a
  yol açan deseni tekrarlar → sorumsuz.

**Şimdi yapılmak istenirse güvenli yol:** `imga_core`'a `stream_text` metodu +
`stream.py` rewire + **mock-SDK unit testi** (chunk→SSE event mantığı) + test compose
(mantık yeşil + regresyonsuz) → push; sonra **server-agent prod'da tek canlı SSE isteğiyle**
(`curl -N .../v1/analyze/stream`) gerçek SDK çağrısını + ilk-token gecikmesini doğrular.
Owner "yaz" derse bu yol izlenir; aksi halde v1.4 backlog.

## 7. §6 final rapor — prod canlı olunca doldurulacak (şablon)

```
[İmga v1.3 → prod TAMAM · {tarih}]
Prod:        https://api.imga.ai · uptime {n}s · p95 {ms} · hata {%}
Contract CI: {n} test · nightly {yeşil gün}/{gün} · {link}
KVKK:        DPA {imza durumu} · DELETE/export prod OK
Billing:     GET /v1/admin/tenants/asakai-prod/usage OK
Graceful:    502 enjekte × {n} · AsakAI banner düştü
Load test:   10 req/s × 10 dk · hata {%} · {rapor}
Git:         prod-v1.3.{x}   Cutover: VDD_IMGA_MOCK=0 · {tarih saat}
```
Bu şablonun **ölçülmüş** değerlerini prod ayağa kalkıp k6 + 24h smoke tamamlanınca yazarım.
