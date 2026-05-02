# Handoff: integration-tests-on-prod

**Tarih:** 2026-05-02 11:55
**Sprint:** 8.3.1
**Yazar:** claude-chat
**Hedef:** server-agent
**Durum:** resolved
**Öncelik:** yüksek

## Bağlam

Kullanıcı `sudo docker compose exec api pytest ...` çalıştırmaya çalıştı, "service not running" hatası aldı (`-f` ile compose dosyası belirtilmediği için yanlış stack arandı). Production stack ayağa kaldırıldı; Sprint 8.3.1 testleri prod container'ında koşturulmak istendi.

## Talep

Production stack'teki API container içinde `pytest` ile beş integration test dosyasını çalıştır, sonucu raporla:
- `tests/test_batch_upload.py`
- `tests/test_batch_dedup.py`
- `tests/test_batch_concurrency.py`
- `tests/test_reviews_list.py`
- `tests/test_orphan_recovery.py`

## Mevcut durum

Yapılanlar:
- Production stack durumu doğrulandı: `imga-prod-postgres` (healthy, 15h), `imga-prod-api` (healthy, 27 dk — Sprint 8.3.1 image'ı), `imga-prod-web` (healthy, 25 dk).
- API image içinde test dosyalarının varlığı kontrol edildi: `find / -name test_batch_upload.py` boş döndü, `/app` altında `tests/` dizini yok.
- Test fixture izolasyonu kontrol edildi (`packages/imga-api/tests/conftest.py`):
  - `_HOST = os.environ.get("IMGA_TEST_PG_HOST", "localhost")`
  - `_PORT = os.environ.get("IMGA_POSTGRES_PORT", "5433")`
  - `_ADMIN_URL = "...imga_admin:imga_admin_password@{_HOST}:{_PORT}/imga"` (parola test default'u, hard-coded)
- Prod container'da `IMGA_TEST_PG_HOST` ve `IMGA_POSTGRES_PORT` env'leri **set değil** (değer dump etmeden boolean check ile doğrulandı).

Yapılmayanlar:
- pytest run edilmedi.

## Beklenen çıktı (asıl talebin)

Test sayıları (passed/failed/skipped) + fail traceback + toplam süre.

## Cevap

**Sonuç: feasible değil — production image'ı testleri içermiyor (kasten, doğru pratik).**

İki gerçek tıkanma noktası:

### 1. Test dosyaları image'da yok

`packages/imga-api/Dockerfile` runtime stage'ine `tests/` dizinini kopyalamıyor (sadece `/app/alembic.ini` ve site-packages'a kurulmuş `imga_api`). Bu doğru pratik: prod image küçük kalsın, test kodu attack surface'ten çıksın. `pytest tests/...` komutu container içinde çalıştırıldığında `ERROR: file or directory not found: tests/test_batch_upload.py` döner.

### 2. Bağlanabilse bile prod DB'ye dokunması yanlış

Test fixture'ları kendi yarattıkları tenant'ı silen `DELETE FROM reviews|tickets|tenants WHERE tenant_id = :t` komutları çalıştırıyor (`packages/imga-api/tests/batch_helpers.py:134-153`). Mid-test fail durumunda prod'da orphan tenant kalabilir. Hard-coded `imga_admin_password` ve `5433` portu doğal bir korumaydı (prod DB'ye bağlanamaz), ama tasarım gereği bu testler **ayrı bir test postgres'e** karşı koşulmalı.

### Doğru çalıştırma yolları (öneri — yeni handoff açılırsa)

Üç seçenek, hepsi için ayrı bir handoff açılması gerekir:

**A. Sunucuda ayrı test postgres + tests/ mount'u**
```bash
# Terminal 1 — ayrı postgres :5433
sudo docker run -d --name imga-test-pg -p 127.0.0.1:5433:5432 \
  -e POSTGRES_USER=imga_admin -e POSTGRES_PASSWORD=imga_admin_password \
  -e POSTGRES_DB=imga postgres:17-alpine

# Terminal 2 — tests'i mount edip ayrı container'da pytest
sudo docker run --rm \
  -v /opt/imga/packages/imga-api/tests:/app/tests:ro \
  -v /opt/imga/packages/imga-api/pyproject.toml:/app/pyproject.toml:ro \
  --network host \
  -e IMGA_TEST_PG_HOST=127.0.0.1 \
  imga-api:production \
  python -m pytest tests/test_batch_upload.py -v
```

**B. CI runner üzerinde (GitHub Actions)** — Sprint 8.3 yol haritasında zaten var. Doğru yer.

**C. Local dev makinesinde** — `(cd packages/imga-api && pytest tests/test_batch_upload.py ...)` — CLAUDE.md'deki tavsiye edilen yol; live postgres :5433 ile.

Bu handoff "feasible değil" sonucuyla resolved. Eğer sunucuda ayrı test postgres kurmak istiyorsan, A için yeni handoff aç.

## İlgili dosyalar

- `packages/imga-api/Dockerfile` — runtime stage, tests kopyalanmıyor
- `packages/imga-api/tests/conftest.py:264-268` — DELETE FROM tenants
- `packages/imga-api/tests/batch_helpers.py:134-153` — DELETE FROM ... WHERE tenant_id
- `CLAUDE.md` (Local development) — testler için live postgres :5433 önerisi

---
