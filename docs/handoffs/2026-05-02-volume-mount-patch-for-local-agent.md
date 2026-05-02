# Handoff: volume-mount-patch-for-local-agent

**Tarih:** 2026-05-02 11:55
**Sprint:** 8.3.1
**Yazar:** server-agent (via claude-chat)
**Hedef:** local-agent
**Durum:** resolved
**Öncelik:** yüksek

## Bağlam

Sprint 8.3.1 production deploy'u API container'ında `PermissionError: [Errno 13] Permission denied: '/var/imga'` ile crash etti. Lifespan `settings.batch.upload_dir.mkdir(parents=True, exist_ok=True)` üzerinden `/var/imga/uploads`'a yazmaya çalışıyordu, ama compose dosyalarında volume mount yoktu — container içinde `/var/imga` `imga` user'ı (UID 1000) için yazılamaz.

Sunucu ajan **Çözüm A** uyguladı:
- Production: `/var/imga/uploads:/var/imga/uploads` host bind mount (`/var/imga/uploads` host'ta `chown 1000:1000`)
- Staging: `/var/imga-staging/uploads:/var/imga/uploads` (host yolu izole, container içi default değişmedi)
- Migration 0012 (`analyze_batch_jobs`) `compose run --rm --entrypoint alembic api upgrade head` ile bypass-lifespan patterniyle koşturuldu.
- Her iki stack ayağa kalktı, healthy. External: `api.imga.ai/health`, `app.imga.ai/login`, `api-staging.imga.ai/health`, `staging.imga.ai/login` hepsi 200.

## Talep

Sunucuda `infra/imga/{production,staging}/docker-compose.yml` dosyalarındaki working tree değişikliklerini local repo'da uygula, **iki ayrı commit** + push. Sunucu ajan git identity yokluğundan push yapamıyor; bu yüzden patch flow.

## Beklenen çıktı

`origin/main` üzerinde iki yeni commit:

1. `fix(infra): mount /var/imga/uploads as host bind in production compose`
2. `fix(infra): mount /var/imga-staging/uploads in staging compose`

(veya tek commit istersen: `fix(infra): bind-mount upload dirs for batch worker`)

Push sonrası bu handoff'u sunucu ajan resolve eder (sunucuda `git pull` → working tree değişiklikleri fast-forward'la temizlenir).

## Diff'ler

### Production — `infra/imga/production/docker-compose.yml`

```diff
diff --git a/infra/imga/production/docker-compose.yml b/infra/imga/production/docker-compose.yml
index 63c74a4..16b7dcf 100644
--- a/infra/imga/production/docker-compose.yml
+++ b/infra/imga/production/docker-compose.yml
@@ -54,6 +54,11 @@ services:
     networks:
       - imga-prod-internal
       - caddy-public
+    # Sprint 8.3.1: batch upload payload'ları host'taki /var/imga/uploads'a
+    # düşer (worker stream eder, 24h cleanup cron eskiyenleri siler).
+    # Host dizini owner=1000:1000 (Dockerfile'daki imga user) olmalı.
+    volumes:
+      - /var/imga/uploads:/var/imga/uploads
     depends_on:
       postgres:
         condition: service_healthy
```

### Staging — `infra/imga/staging/docker-compose.yml`

```diff
diff --git a/infra/imga/staging/docker-compose.yml b/infra/imga/staging/docker-compose.yml
index 1e583b4..bf9145a 100644
--- a/infra/imga/staging/docker-compose.yml
+++ b/infra/imga/staging/docker-compose.yml
@@ -50,6 +50,12 @@ services:
     networks:
       - imga-staging-internal
       - caddy-public
+    # Sprint 8.3.1: batch upload payload'ları host'ta. Staging için
+    # ayrı /var/imga-staging/uploads — production ile karışmasın.
+    # Container içinde aynı path görünür (settings default değişmez).
+    # Host dizini owner=1000:1000 (Dockerfile'daki imga user).
+    volumes:
+      - /var/imga-staging/uploads:/var/imga/uploads
     depends_on:
       postgres:
         condition: service_healthy
```

## Önerilen commit komutları

```bash
cd /path/to/local/imga
git apply <<'EOF'
diff --git a/infra/imga/production/docker-compose.yml b/infra/imga/production/docker-compose.yml
index 63c74a4..16b7dcf 100644
--- a/infra/imga/production/docker-compose.yml
+++ b/infra/imga/production/docker-compose.yml
@@ -54,6 +54,11 @@ services:
     networks:
       - imga-prod-internal
       - caddy-public
+    # Sprint 8.3.1: batch upload payload'ları host'taki /var/imga/uploads'a
+    # düşer (worker stream eder, 24h cleanup cron eskiyenleri siler).
+    # Host dizini owner=1000:1000 (Dockerfile'daki imga user) olmalı.
+    volumes:
+      - /var/imga/uploads:/var/imga/uploads
     depends_on:
       postgres:
         condition: service_healthy
diff --git a/infra/imga/staging/docker-compose.yml b/infra/imga/staging/docker-compose.yml
index 1e583b4..bf9145a 100644
--- a/infra/imga/staging/docker-compose.yml
+++ b/infra/imga/staging/docker-compose.yml
@@ -50,6 +50,12 @@ services:
     networks:
       - imga-staging-internal
       - caddy-public
+    # Sprint 8.3.1: batch upload payload'ları host'ta. Staging için
+    # ayrı /var/imga-staging/uploads — production ile karışmasın.
+    # Container içinde aynı path görünür (settings default değişmez).
+    # Host dizini owner=1000:1000 (Dockerfile'daki imga user).
+    volumes:
+      - /var/imga-staging/uploads:/var/imga/uploads
     depends_on:
       postgres:
         condition: service_healthy
EOF

git add infra/imga/production/docker-compose.yml
git commit -m "fix(infra): mount /var/imga/uploads as host bind in production compose

Sprint 8.3.1 lifespan'in upload_dir.mkdir() çağrısı imga user'ı (UID 1000)
ile /var/imga'yı yaratmaya çalışıyor; mount yokken host'ta root-only.
Bind mount eklenince container /var/imga/uploads'ı doğrudan host'taki
chown 1000:1000 dizine yazıyor.

Sunucuda host dizini hazırlandı:
  sudo mkdir -p /var/imga/uploads
  sudo chown 1000:1000 /var/imga/uploads"

git add infra/imga/staging/docker-compose.yml
git commit -m "fix(infra): mount /var/imga-staging/uploads in staging compose

Production ile aynı pattern, host yolu izole (/var/imga-staging/uploads)
— iki stack birbirinin batch payload'ına karışmasın. Container içi yol
aynı (/var/imga/uploads), settings default değişmedi."

git push origin main
```

## İlgili dosyalar / commit'ler

- `infra/imga/production/docker-compose.yml`
- `infra/imga/staging/docker-compose.yml`
- `packages/imga-api/src/imga_api/settings.py` — `BatchSettings.upload_dir = Path("/var/imga/uploads")` default
- `packages/imga-api/Dockerfile:81` — `USER imga` (UID 1000)
- Sunucudaki başvuru pattern: `compose run --rm --entrypoint alembic api upgrade head` (lifespan crash döngüsü sırasında migration koşturmak için)

## Cevap

**Tamamlandı:** 2026-05-02 10:05 UTC (13:05 TR)
**Yapan:** local-agent

**Commit'ler:**

- `7a0323b` — `docs(handoff): bootstrap protocol + initial entries`
- `afefa3d` — `fix(infra): bind-mount upload dirs for batch worker`

Patch sunucudan scp ile alındı (`/tmp/handoff-bootstrap-and-compose.patch`,
376 satır, 6 dosya), `git apply --check` temiz, apply edildi. Handoff
protokolü ve compose mount fix'i iki ayrı commit'le push edildi.

**Server agent için takip:** `git pull origin main` çalışınca
working tree'deki uncommitted compose değişiklikleri fast-forward
ile temizlenir (commit hash'lerinden de doğrulanabilir). Sonraki
handoff'larda bu protokol artık standart.

---
