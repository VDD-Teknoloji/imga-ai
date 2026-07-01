# Handoff — AsakAI v1 N+1 auth temeli (migration 0032) test koşumu

**Tarih:** 2026-07-01 · **Yazar:** local-agent · **Hedef:** server-agent
**Durum:** open · **Öncelik:** yüksek
**Branch:** `docs/asakai-v1-n0-contract-freeze` (commit `c43d1a3`)

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
