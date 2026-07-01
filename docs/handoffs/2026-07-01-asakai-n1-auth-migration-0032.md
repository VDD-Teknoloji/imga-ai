# Handoff — AsakAI v1 N+1 auth temeli (migration 0032) test koşumu

**Tarih:** 2026-07-01 · **Yazar:** local-agent · **Hedef:** server-agent
**Durum:** ✅ ÇÖZÜLDÜ (foundation local-agent tarafından doğrulandı) · **Öncelik:** —
**Branch:** merge edildi → `main` (`e23bb5a`)

> **ÇÖZÜM (2026-07-01):** Bu handoff'un gerekçesi ("lokalde :5433 koşulamıyor")
> aşıldı — local-agent Docker test compose'unu (`infra/imga/test/docker-compose.yml`,
> pgvector'lü container) koştu. Sonuç: **633 passed, 2 skipped**; migration
> **0032→0033→0034 gerçek Postgres'e uygulandı** (RLS+FORCE tablolar); yeni testler
> (`test_api_token_security` ×10, `test_api_tokens_service` ×5, `tests/contract/*`)
> yeşil. Bu koşumda **gerçek bir prod-çökmesi bug'ı bulunup düzeltildi** (partner_analyze
> `LLMProviderError` yanlış modülden → tüm api boot çökerdi; commit `47a11b0`).
> Feature **main'e merge + push edildi** (`e23bb5a`). Server-agent doğrulamayı
> tekrar koşabilir ama artık zorunlu değil — sıra doğrudan **deploy** handoff'unda
> (`2026-07-01-asakai-n1-deploy-and-cutover.md`).

## Bağlam

AsakAI ⇒ İmga v1 partner API'nin N+1 auth temelinin ilk dilimi yazıldı
(contract §8/§8.1/§8.6). Lokalde **:5433 canlı-Postgres pytest koşulamıyor**
(conftest → pgvector); CLAUDE.md gereği push öncesi test yeşili şart →
sunucu ajanına devir.

## Değişen dosyalar

- `packages/imga-db/.../alembic/versions/20260701_0000_0032_api_and_admin_tokens.py`
  — yeni migration (head 0031 → 0032). İki tablo: `api_tokens` (RLS+FORCE
  `tenant_isolation`), `admin_tokens` (deny-all RLS, §8.6).
- `packages/imga-db/.../models/api_token.py` — `ApiTokenRecord`, `AdminTokenRecord`
  (+ `models/__init__.py` kaydı).
- `packages/imga-api/.../security/api_tokens.py` — saf token helper'ları
  (mint/hash HMAC+pepper/verify/prefix/cross-env). Lokalde izole 20+ assertion PASS.
- `packages/imga-api/tests/test_api_token_security.py` — helper testleri
  (canonical pytest listesine eklendi: `infra/imga/test/docker-compose.yml`).

## Sunucu ajanından istenen

1. **Migration:** `alembic upgrade head` → 0032 sorunsuz uygulanıyor mu?
   `alembic downgrade -1` + tekrar upgrade ile idempotent mi? (RLS policy +
   indexler + FK'ler yaratılıyor mu.)
2. **Canonical pytest:** test compose'u koştur; `test_api_token_security.py`
   **yeşil** olmalı (10 test). Regresyon yok mu (601+ → +10)?
3. **ruff + mypy strict:** yeni dosyalar temiz geçiyor mu?
4. **RLS smoke (elle veya kısa script):** `imga_app` rolüyle `api_tokens`'a
   `app.current_tenant_id` set edilmeden erişim 0 satır; `admin_tokens`'a
   `imga_app` erişimi 0 satır (deny-all), `imga_admin` (BYPASSRLS) erişebiliyor.

## Notlar

- Bu dilim **DB'ye yazan servis + dual-path middleware + admin route'ları
  İÇERMEZ** — onlar sonraki dilim. Şimdilik yalnız şema + saf helper.
- `IMGA_TOKEN_PEPPER` env (prod+staging AYRI) henüz wire edilmedi (servis
  diliminde gelecek); helper pepper'ı argüman olarak alıyor, import-time secret yok.
- Kırmızı çıkarsa: tam pytest çıktısı + `alembic` hatası ile geri bildir;
  local-agent tek-satır düzeltir.

## Güncelleme — §3.1 auth katmanı tamamlandı (commit sonrası)

Migration + helper'a EK OLARAK auth yüzeyi yazıldı:
- `settings.py`: `IMGA_TOKEN_PEPPER` (min-32, prod/staging AYRI) + `environment` (IMGA_ENV).
- `services/api_tokens.py`: `ApiTokenService` (mint/verify/rotate/revoke/list/mark_used).
  verify() **imga_admin (BYPASSRLS)** session ile lookup.
- `v1/errors.py`: `PartnerApiError` + AnalyzeError render + exception handler.
- `v1/auth.py`: `get_partner_principal` çift-yol (tenant/ops), cross-env (§8.1),
  `require_tenant`/`require_ops` (§8.6), `bind_api_tenant`.
- `v1/admin_tokens.py`: `POST /v1/admin/tokens/rotate` + `/{id}/revoke` + `GET ?tenant_id=`
  (opsBearer, §4A.3-4A.5). External tenant_id = Tenant.slug.
- `main.py`: exception handler register + router include.
- `tests/test_api_tokens_service.py`: ops token mint/verify/revoke + validations
  (admin_session, tenant FK gerektirmez). **Canonical listeye eklendi.**

Ek istenen (yukarıdaki 4 maddeye ek):
5. `test_api_tokens_service.py` yeşil mi? (ilk DB-backed test — admin_session
   fixture + `@pytest.mark.asyncio` kullanımı doğru mu, collection sorunu var mı.)
6. `mypy --strict` yeni `v1/` + `services/api_tokens.py` + `settings.py` temiz mi?
7. **Bootstrap notu:** ilk ops token'ı mint edecek bir yol henüz yok (admin routes
   opsBearer ister → tavuk-yumurta). Bir management CLI / seed script sonraki dilimde;
   şimdilik test dışında ops token elle DB'ye eklenebilir.

## Güncelleme 2 — §3.2 + §3.5 + migration 0033 (aynı foundation)

Bu handoff artık **tüm N+1 foundation'ı** kapsıyor. Ek dosyalar:
- `migration 0033`: `api_tenant_config` (quota/contact/residency_locks) +
  `api_request_log` (usage/billing/export/erasure — ham gövde YOK). İkisi RLS+FORCE.
- `models/api_tenant.py`: ApiTenantConfig + ApiRequestLog (+ kayıt).
- `v1/admin_tenants.py`: POST tenants (slugify) + POST quota + GET usage (§4A.1/§4A.2).
- `v1/health.py`: GET /v1/health (§4.7, unauth).

**Sunucu ajanından (tümü):** `alembic upgrade head` → 0032 **ve** 0033 sorunsuz;
canonical pytest (`test_api_token_security.py` + `test_api_tokens_service.py`) yeşil;
ruff + mypy strict yeni `v1/` + `services/api_tokens.py` + `models/api_*.py` + `settings.py`
temiz; `import imga_api.main` boot-time hatasız (router include + exception handler).
Kırmızı → tam çıktı ile geri bildir.

## Henüz YAPILMAYANLAR (sonraki dilimler — bu handoff kapsamı dışı)

§3.3 analyze+Gemini · §3.4 SSE · §3.6 rate-limit (Redis) · §3.7 idempotency (Redis) ·
§3.8 KVKK data lifecycle + purge worker · §3.10 contract test suite · §3.11 deploy.
