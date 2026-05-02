# Handoff: batch-asyncpg-debug-round-2

**Tarih:** 2026-05-02 14:10
**Sprint:** 8.3.1 → 8.3.2 köprü
**Yazar:** server-agent
**Hedef:** local-agent
**Durum:** open
**Öncelik:** yüksek

## Bağlam

Round 1 fix (`38f05d6 fix(api): batch worker engines owned by WorkerContext, not module globals`) deploy edildi, test stack tekrar koşturuldu. **5 test düzeldi, 9 hâlâ fail.**

Önceki: 17 passed, 14 failed
Şu an:  **22 passed, 9 failed** (40.05s)

## Talep

Kalan 9 fail'in kök nedenini bul ve düzelt. Round-1 fix `WorkerContext` engine sahipliğini taşıdı; ama testlerin gerçekten patladığı yer hâlâ event-loop scope karışıklığı — sadece **patlama anı değişti**: artık operation sırasında değil, **connection cleanup** sırasında.

## Mevcut durum

### Hâlâ fail eden 9 test

| Dosya | Test |
|---|---|
| `test_batch_upload.py` | `test_worker_processes_all_rows_and_marks_completed` |
| `test_batch_upload.py` | `test_worker_skips_empty_text_rows_as_failed` |
| `test_batch_upload.py` | `test_auto_create_disabled_skips_ticket_creation` |
| `test_batch_upload.py` | `test_auto_create_enabled_in_semi_auto_creates_tickets_for_negatives` |
| `test_batch_dedup.py` | `test_intra_batch_dedup_collapses_repeated_text` |
| `test_batch_dedup.py` | `test_cross_batch_dedup_24h_window_links_to_existing_ticket` |
| `test_batch_dedup.py` | `test_cross_batch_dedup_outside_24h_window_creates_fresh_ticket` |
| `test_batch_concurrency.py` | `test_per_tenant_lock_serialises_jobs` |
| `test_batch_concurrency.py` | `test_global_semaphore_caps_parallelism_at_two` |

Round-1'den düzelen 5: `test_orphan_recovery.py` (2/2), `test_batch_upload.py::{test_auto_create_enabled_in_manual_mode, test_cancel_before_worker_pickup, test_cancel_terminal_job}`.

### Hâlâ yeşil olanlar (22)

- `test_reviews_list.py` — 10/10 ✅ (read-only, sapasağlam)
- `test_batch_upload.py` — 7/13 (upload validation + cancel + RLS yeşil; worker write paths kırmızı)
- `test_batch_dedup.py` — 1/4 (`test_text_hash_is_turkish_case_insensitive` salt-fonksiyon yeşil)
- `test_orphan_recovery.py` — 2/2 ✅ (round-1 fix bunu çözdü)

### Yeni hata desenleri

Asıl pattern hâlâ aynı kök: **iki ayrı event loop'a bağlı future**. Ama artık iki yüzeyde:

**1) Operation-time hatası** (worker içinde):
```
sqlalchemy.exc.InterfaceError:
  cannot perform operation: another operation is in progress
```

**2) Cleanup-time hatası** (test bitiminde, connection pool kapanırken):
```
ERROR sqlalchemy.pool.impl.AsyncAdaptedQueuePool: Exception closing connection
RuntimeError: Task <Task pending name='anyio.from_thread.BlockingPortal._call_func'
  coro=<BlockingPortal._call_func()> ...> got Future <Future pending
  cb=[BaseProtocol._on_waiter_completed()]> attached to a different loop
...
RuntimeError: Event loop is closed
```

`anyio.from_thread.BlockingPortal._call_func` izi önemli: **FastAPI TestClient** üstüne sync API'den async app çalıştırmak için `anyio.from_thread.BlockingPortal` kullanır. Yani:
- Conftest'in `e2e_seed` veya benzer fixture'ı (pytest event-loop'unda) bir async engine yaratıyor
- Aynı test'te `e2e_client` (TestClient) FastAPI app'i kendi BlockingPortal thread'i üstündeki yeni event loop'ta çalıştırıyor
- Worker o app loop'undan tetikleniyor → yeni engine yaratıp DB'ye gidiyor (round-1 fix sayesinde)
- Ama conftest tarafından önceden-yaratılmış admin/owner engine BAŞKA loop'a bağlı; aynı test içinde ona dokunulduğunda veya teardown'da pool kapanırken o loop'a switch denenir → "different loop"

### Round-1 fix'in ne kapsadığı, neyi atladığı

Local ajan'ın commit'i (`38f05d6`):
- ✅ `packages/imga-api/src/imga_api/workers/batch_analyzer.py` — modül-global engine'leri kaldırıp `WorkerContext`'e taşıdı
- ✅ `recover_orphans` artık WorkerContext üstünden engine alıyor → `test_orphan_recovery` yeşil
- ⚠️ Conftest tarafında **hâlâ modül seviyesi engine yaratımı var olmalı** (E2E fixture'ları `create_engine("admin")` benzeri çağrılarla)

`packages/imga-api/tests/conftest.py:97-105` URL constants modül seviyesinde tanımlı; engine'in nerede yaratıldığını ve ne kadar yaşadığını izle. Asıl şüpheli: `e2e_seed` fixture'ı (pytest_asyncio.fixture) içinde `engine = create_engine("admin")` yapıyor — ve eğer bu engine fixture scope'unun gerektirdiği yerde dispose edilmiyorsa, sonraki test başka loop'ta açılınca patlar.

## Önerilen tanı adımları

1. **Tek failing test'i izole çalıştır** (event-loop kirliliğini kapatmak için):
   ```bash
   sudo docker compose -f /opt/imga/infra/imga/test/docker-compose.yml run --rm api-test \
     sh -ec 'pip install --quiet pytest pytest-asyncio pytest-timeout factory-boy httpx && \
       alembic upgrade head && \
       python -m pytest tests/test_batch_dedup.py::test_intra_batch_dedup_collapses_repeated_text \
         -v --tb=long'
   ```
   Tek test geçiyorsa → sorun test'lerin SIRA'sından geliyor (engine cross-contamination)
   Tek test bile fail ise → o test'in fixture'ı içinde engine + TestClient çelişkisi

2. **Conftest'te engine create eden tüm yerleri listele:**
   ```bash
   grep -n "create_engine\|create_session_factory" /opt/imga/packages/imga-api/tests/conftest.py
   ```
   Her birini kontrol et: fixture scope'u nedir, dispose ediliyor mu, hangi event loop'ta yaratılıyor.

3. **`event_loop` fixture'ını override et** (klasik pytest-asyncio çözümü):
   `pyproject.toml`'da zaten `asyncio_mode = "auto"` var. Eğer per-test event loop istiyorsa, fixture'lar function-scoped engine yaratmalı. Module/session scope'lu engine + function scope test = bu hata.

4. **WorkerContext hâlâ tek mi yaratılıyor:** Round-1 commit'i WorkerContext'i nerede tutuyor? `app.state` mı, modül global mi? Eğer `app.state`'te ve TestClient app'i yeniden yaratılmıyorsa, app context iki test arasında paylaşıldığı için engine de paylaşılır.

## Beklenen çıktı

**31/31 pass.** Round 1 fixture pattern'inden farklı bir yere müdahale gerekiyor — büyük ihtimalle conftest tarafında engine fixture'larının scope'unu function-scoped + dispose-on-teardown yapmak.

Production'a etkisi yine **sıfır** — bu pure-test infra issue. Ama 31/31 olmadan Sprint 8.3.2'ye güvenle geçemeyiz.

## İlgili dosyalar

- `packages/imga-api/tests/conftest.py:97-105` — module-level URL constants
- `packages/imga-api/tests/conftest.py:183, 396, 411, 426` — pytest_asyncio fixture'ları (engine yaratma şüphelileri)
- `packages/imga-api/src/imga_api/workers/batch_analyzer.py` — round-1 fix burada (WorkerContext)
- `packages/imga-api/src/imga_api/main.py` — app.state'e WorkerContext kuruyor olabilir (round-1 değişiklik dahil)

## Round-1'den çıkarılan öğreti (önemli)

Round-1 değiştirilen dosyalardan biri `packages/imga-api/src/imga_api/main.py` (5 satır). Yani lifespan/app.state üzerinde değişiklik vardı. WorkerContext büyük ihtimalle app.state'e bağlandı. TestClient app'i her test'te recreate etmiyorsa (default davranışı paylaşmaktır), aynı app instance + farklı event loop'lar = bug. Conftest'in `e2e_client` fixture'ı `app.router.lifespan_context` swap ediyor ama `app` global referansını değiştirmiyor — bu da kirlenme noktası olabilir.

## Doğrulama

Düzeltme sonrası sunucu ajan test stack'i koştursun:
```bash
sudo docker compose -f /opt/imga/infra/imga/test/docker-compose.yml up --build \
  --abort-on-container-exit --exit-code-from api-test
```
Beklenen: `==== 31 passed in <X>s ====` ve exit code 0.

## Cevap

(local-agent doldurur — round 2 fix commit hash'i, 31/31 doğrulama)

---
