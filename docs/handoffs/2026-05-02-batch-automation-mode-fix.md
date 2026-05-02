# Handoff: batch-automation-mode-fix

**Tarih:** 2026-05-02 (local-agent saat)
**Sprint:** 8.3.1 hot-fix
**Yazar:** local-agent
**Hedef:** server-agent
**Durum:** resolved
**Öncelik:** kritik

## Bağlam

Browser smoke test sırasında 20 satırlık batch upload `asyncpg.CheckViolationError` ile düştü. `reviews.automation_mode` kolonunda `ck_reviews_automation_mode` CHECK constraint sadece `manual` / `semi_auto` / `full_auto` kabul ediyor; batch worker `auto_create_tickets=False` ve intra-batch dedup yollarında sentinel string'leri (`batch_opt_out`, `batch_intra_dedup`) yazmaya çalışıyordu.

Constraint tanımı: [`migration 0008`](../../packages/imga-db/src/imga_db/alembic/versions/20260108_0000_0008_reviews.py#L127-L130).

Sentinel atayan kod:

- `packages/imga-api/src/imga_api/workers/batch_analyzer.py:423` — intra-batch dedup path
- `packages/imga-api/src/imga_api/workers/batch_analyzer.py:489` — auto_create=False path

## Talep

Lokalde fix uygulandı + commit'lendi + push'landı. Server agent `git pull` + redeploy yapıp browser smoke test'i tekrarlasın. Patch sunucuda da tekrar çalıştırılmak istenirse: `/tmp/batch-automation-mode-fix.patch`.

## Mevcut durum

Yapılanlar:

- `_process_chunk` artık tenant config'i bir kez okuyup `tenant_mode` değişkeninde tutuyor.
- İki Review insert path'i (intra-batch dedup ve opt-out) `automation_mode=tenant_mode` kullanıyor; batch-spesifik niyet zaten `decision` + `decision_reason` alanlarında.
- `test_batch_upload.py`'a iki regression test eklendi:
  - `test_auto_create_disabled_skips_ticket_creation` artık `automation_mode == "full_auto"` da assert ediyor.
  - `test_intra_batch_dedup_uses_real_tenant_automation_mode` — yeni test, semi_auto tenant + duplicate rows.
- `ruff check src tests` clean, `mypy src` clean.

Yapılmayanlar:

- Server agent `infra/imga/test/docker-compose.yml` ile fix'i doğrulamadı (bu turn'de test stack'i koşmadı — local-agent'ın Docker'ı yok).

## Beklenen çıktı

- Server agent `git pull` çekip redeploy yapsın (`fix(api): batch worker uses real tenant automation_mode`).
- Test stack'i tekrar koştursun: 31/31 + 2 yeni test = 33/33 pass beklenir.
- Browser smoke test'i tekrar etsin — 20 satırlık batch artık COMPLETED'a varmalı.

## İlgili dosyalar / commit'ler

- `packages/imga-api/src/imga_api/workers/batch_analyzer.py`
- `packages/imga-api/tests/test_batch_upload.py`
- `packages/imga-db/src/imga_db/alembic/versions/20260108_0000_0008_reviews.py` (CHECK constraint referansı)

## Cevap

**Tamamlandı:** local-agent
**Commit:** `bde7037` — `fix(api): batch worker uses real tenant automation_mode, not sentinel`
**Patch (server agent için):** `/tmp/batch-automation-mode-fix.patch` (151 satır)

Sentinel'ler kaldırıldı, automation_mode her zaman tenant config'ten geliyor. Test stack koşumu server-agent tarafından doğrulanacak.

---
