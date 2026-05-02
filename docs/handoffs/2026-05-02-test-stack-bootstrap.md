# Handoff: test-stack-bootstrap

**Tarih:** 2026-05-02 13:20
**Sprint:** 8.3.1 → 8.3.2 köprü
**Yazar:** server-agent
**Hedef:** local-agent
**Durum:** open
**Öncelik:** yüksek

## Bağlam

Sprint 8.3.1 entegrasyon testlerini koşturmak için bir yol gerekiyordu. Önceki handoff (`2026-05-02-integration-tests-on-prod.md`) tespit etti: production image testleri içermiyor (kasten — runtime stage `tests/` kopyalamıyor) ve pytest yok. CI (Sprint 8.4) gelene kadar geçici çözüm: izole bir test stack.

Sunucu ajan `infra/imga/test/docker-compose.yml` dosyasını yarattı, sunucuda bir kez koşturdu, sonuçları aldı.

## Talep

`infra/imga/test/docker-compose.yml` dosyasını local repo'da uygula, commit + push. Sunucu ajan git identity yokluğundan push yapamıyor; patch flow.

## Mevcut durum

Yapılanlar:
- Yeni dosya: `infra/imga/test/docker-compose.yml` (104 satır)
- Sunucuda bir kez koşturuldu (build cached → 50sn pytest)
- Postgres init script çalıştı, 3 rol (`imga_owner`/`imga_app`/`imga_admin`) test default parolalarıyla yaratıldı
- Alembic 0001 → 0012 koştu, schema oluştu
- Pytest deps (httpx + factory-boy + pytest-* eklentileri) runtime'da `pip install` ile geldi
- 5 test dosyası (31 test toplam) koşturuldu

**Test sonucu: 17 passed, 14 failed** (50.59s)

| Dosya | Pass | Fail | Toplam |
|---|---|---|---|
| `test_reviews_list.py` | **10** | 0 | 10 |
| `test_batch_upload.py` | 6 | 7 | 13 |
| `test_batch_dedup.py` | 1 | 3 | 4 |
| `test_batch_concurrency.py` | 0 | **2** | 2 |
| `test_orphan_recovery.py` | 0 | **2** | 2 |

**Hata desenleri (72 occurrence — neredeyse hepsi aynı):**
```
sqlalchemy.exc.InterfaceError: <class 'asyncpg.exceptions._base.InterfaceError'>:
cannot perform operation: another operation is in progress
```

Asyncpg "tek connection üstünde paralel coroutine" sinyali. Üç olası kök:
1. **Test fixture'ında session/event loop scope karışıklığı** — pytest-asyncio'nun `auto` modu farklı testlerde aynı engine'i paylaştırıyor olabilir
2. **Worker'ın gerçek bir bug'ı** — `recover_orphans` ve worker pickup yolları aynı session üstünde paralel iş üretiyor olabilir (test bunu surfacing ediyor)
3. **Conftest'te transactional setup yok** — DDL/DML aynı async connection'da çakışıyor

Failing test isimleri orphan-recovery + concurrency ağırlıklı; bu bir patternleştirme sinyali. Sprint 8.3.2'ye geçmeden önce kök neden tespit edilmeli.

`test_reviews_list.py`'nin tamamı yeşil — read-only endpoint testleri sağlam. Yazma+worker tarafında bir mesele var.

Yapılmayanlar:
- 14 fail'in tek tek kök neden analizi (handoff ölçeği dışı; ayrı debugging handoff'u açılmalı)
- Diğer test dosyaları (`test_e2e_full_flow`, `test_auth`, `test_endpoints` vs.) — sadece istenen 5 batch + reviews dosyası koşturuldu
- CI entegrasyonu — Sprint 8.4 işi

## Beklenen çıktı

`origin/main` üzerinde tek commit:

```
chore(infra): server-side integration test stack

infra/imga/test/docker-compose.yml — pytest karşı izole bir postgres
+ pytest deps runtime'da pip ile yüklenen api container. Production
runtime image'ı yeniden kullanır, Dockerfile'a "test" stage
eklemekten kaçınır. CI çıkana kadar (Sprint 8.4) sunucuda
"docker compose -f infra/imga/test/docker-compose.yml up --build
--abort-on-container-exit --exit-code-from api-test" ile koşturulur.

İlk koşumda 5 batch+reviews dosyasından 17 passed, 14 failed
(detay: docs/handoffs/2026-05-02-test-stack-bootstrap.md). Failure
deseni asyncpg shared-session; ayrı debugging handoff'unda izlenecek.
```

Push sonrası bu handoff'u `Cevap` bölümünde commit hash'iyle resolve et.

## Diff (`infra/imga/test/docker-compose.yml` — yeni dosya)

```diff
diff --git a/infra/imga/test/docker-compose.yml b/infra/imga/test/docker-compose.yml
new file mode 100644
index 0000000..65d2098
--- /dev/null
+++ b/infra/imga/test/docker-compose.yml
@@ -0,0 +1,104 @@
+# İmga.AI — server-side integration test stack
+#
+# Yer: /opt/imga/infra/imga/test/docker-compose.yml (sunucuda)
+#
+# Amaç: Sprint 8.3.1+ entegrasyon testlerini canlı Postgres karşı koşturmak,
+# prod/staging stack'lerine dokunmadan. Production runtime image'ı yeniden
+# kullanılır; pytest deps runtime'da pip ile kurulur (Dockerfile'a "test"
+# stage eklemek yerine — minimal cerrahi). CI çıkana kadar (Sprint 8.4)
+# geçici çözüm.
+#
+# Komut:
+#   sudo docker compose -f /opt/imga/infra/imga/test/docker-compose.yml \
+#     up --build --abort-on-container-exit --exit-code-from api-test
+#
+# api-test container'ı pytest exit code'u ile sonlanır → compose o code'la
+# döner → CI/script entegrasyonu kolay. Volume yok, port expose yok,
+# init script konteynır ile başlar → tek shot, sıfır kalıcı durum.
+
+name: imga-test
+
+services:
+  postgres-test:
+    image: postgres:17-alpine
+    container_name: imga-test-postgres
+    # Test conftest'i hard-coded parolaları bekler (imga_dev_password /
+    # imga_app_password / imga_admin_password). Init script POSTGRES_USER
+    # rolünü POSTGRES_PASSWORD'le, app + admin'i IMGA_*_PASSWORD env'leri
+    # boşsa default'larla yaratır — burada POSTGRES_PASSWORD'ü conftest'in
+    # owner default'una eşitliyoruz, app/admin için env vermiyoruz ki
+    # default'lar devreye girsin.
+    environment:
+      POSTGRES_USER: imga_owner
+      POSTGRES_PASSWORD: imga_dev_password
+      POSTGRES_DB: imga
+    volumes:
+      - ../../../packages/imga-db/sql:/docker-entrypoint-initdb.d:ro
+    networks:
+      - imga-test-net
+    healthcheck:
+      test: ["CMD-SHELL", "pg_isready -U imga_owner -d imga"]
+      interval: 3s
+      timeout: 3s
+      retries: 20
+
+  api-test:
+    # Production image'ını yeniden kullanırız — pytest + plugin'leri
+    # runtime'da kurulur. Image build edilmemişse :latest tag'inden
+    # düşer, build context production ile aynı.
+    image: imga-api:test
+    build:
+      context: ../../..
+      dockerfile: packages/imga-api/Dockerfile
+    container_name: imga-test-api
+    networks:
+      - imga-test-net
+    depends_on:
+      postgres-test:
+        condition: service_healthy
+    environment:
+      # Conftest bu iki var'ı okur; defaultlar (localhost:5433) yerine
+      # docker network'teki postgres-test:5432'yi gösterir.
+      IMGA_TEST_PG_HOST: postgres-test
+      IMGA_POSTGRES_PORT: "5432"
+      # E2E tests bunu okur (e2e_env fixture override etse de güvenlik
+      # ağı). Test-only secret, gerçek bir şey değil.
+      JWT_SECRET_KEY: test-secret-key-32-bytes-min-padding-xyz
+      # Alembic migration'ları test postgres'e koşturmak için (E2E
+      # fixture create_engine("admin") etkisini kullanır; tablolar
+      # önce alembic upgrade head ile yaratılmalı — entrypoint command
+      # bunu yapar).
+      DATABASE_URL_OWNER: postgresql+asyncpg://imga_owner:imga_dev_password@postgres-test:5432/imga
+      DATABASE_URL: postgresql+asyncpg://imga_app:imga_app_password@postgres-test:5432/imga
+      DATABASE_URL_ADMIN: postgresql+asyncpg://imga_admin:imga_admin_password@postgres-test:5432/imga
+    # Pytest deps pip install için root gerekir (runtime image USER imga,
+    # site-packages owner root). Test'ler tmp_path'e yazar, root sorun değil.
+    user: root
+    # Tests + pyproject ro mount; src değil — production'a giden code
+    # path'i test edilir, lokal değişiklik testleri etkilemez.
+    volumes:
+      - ../../../packages/imga-api/tests:/app/tests:ro
+      - ../../../packages/imga-api/pyproject.toml:/app/pyproject.toml:ro
+    working_dir: /app
+    command:
+      - sh
+      - -ec
+      - |
+        echo "[test-stack] installing pytest deps"
+        pip install --no-cache-dir --quiet \
+          pytest pytest-asyncio pytest-timeout pytest-cov \
+          factory-boy httpx
+        echo "[test-stack] migrating test postgres to head"
+        alembic upgrade head
+        echo "[test-stack] running pytest"
+        python -m pytest \
+          tests/test_batch_upload.py \
+          tests/test_batch_dedup.py \
+          tests/test_batch_concurrency.py \
+          tests/test_reviews_list.py \
+          tests/test_orphan_recovery.py \
+          -v --tb=short
+
+networks:
+  imga-test-net:
+    name: imga-test-net
```

## Önerilen takip işleri (ayrı handoff'lar)

1. **Yeni handoff: `2026-05-02-batch-shared-session-bug.md`** — 14 failure'ın asyncpg shared-session kaynağını tespit + fix. Hedef: local-agent veya claude-chat (debug oturumu).
2. **Sprint 8.4 / CI handoff'u** — bu compose file CI runner'ında (GitHub Actions) doğrudan çalıştırılabilir; runner'da Docker var → step: `docker compose -f infra/imga/test/docker-compose.yml up --build --abort-on-container-exit --exit-code-from api-test`. Test stack repo'da olduğu için lokal + CI aynı yolu kullanır.
3. **CLAUDE.md güncellemesi** — "Test çalıştırma" başlığı altına bu yolu da ekle (local pytest + sunucu compose stack iki seçenek olarak).

## İlgili dosyalar

- `infra/imga/test/docker-compose.yml` (yeni)
- `packages/imga-api/Dockerfile` — runtime stage USER imga + site-packages root-owned
- `packages/imga-api/tests/conftest.py:99-105` — `_HOST/_PORT` env override mantığı
- `packages/imga-db/sql/01-init-roles.sh` — 3 rol yaratımı (default parolalar match'liyor)

## Cevap

(local-agent doldurur — push edilen commit hash, resolved date)

---
