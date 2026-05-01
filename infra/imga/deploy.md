# İmga.AI — production + staging deploy runbook

Bu doküman sunucuda **tek başına** uygulanır. Ön koşul: `infra/server-setup.md`'in §1-10'u tamamlanmış olmalı (sistem hardening + multi-project foundation kurulu).

Sıralama önemli — Caddy'nin Let's Encrypt'ten sertifika alabilmesi için DNS doğru, port 80/443 açık olmalı. Postgres ilk başlatmada init script'i çalıştırır; bir kere çalıştıktan sonra parolaları değiştirmek volume'u resetlemeden mümkün değil, o yüzden başlangıçta doğru kur.

## 0. Ön koşullar

```bash
# Repo /opt/imga'da klonlanmış olmalı
cd /opt/imga
git pull origin main      # son sprint çalışmasını çek

# §10 multi-project foundation kurulu olmalı
ls /opt/shared/caddy/conf.d/      # var olmalı, içinde sadece .gitkeep
docker network ls | grep -E '(caddy-public|shared-db)'

# Cloudflare tarafında DNS A kayıtları VPS IP'sine yönlendirilmiş olmalı
# (en azından DNS-only / gri bulut modunda):
#   app.imga.ai          → <VPS_IP>
#   api.imga.ai          → <VPS_IP>
#   staging.imga.ai      → <VPS_IP>
#   api-staging.imga.ai  → <VPS_IP>
# Test:
dig +short app.imga.ai
# <VPS_IP> dönmeli. Cloudflare proxy modunda Cloudflare IP'si döner;
# o durumda da OK ama §1'de SSL/TLS modunu doğru ayarlamak gerekecek.
```

> **Cloudflare proxy ile başlatma:** İlk sertifika alımında **DNS-only (gri bulut)** seçmek en pürüzsüz yoldur. Caddy LE'den HTTP-01 ile sertifika alır, sonra istersen "Proxied (turuncu bulut)" + SSL/TLS "Full (strict)" moduna geçirebilirsin. Proxied başlatırsan SSL/TLS modunu mutlaka **"Full (strict)"** yap, "Flexible" sonsuz redirect döngüsü yapar.

## 1. Postgres parolalarını üret

```bash
# 6 farklı güçlü parola (3 prod + 3 staging)
for env in production staging; do
  echo "=== $env ==="
  for role in OWNER APP ADMIN; do
    echo "$role: $(openssl rand -base64 32)"
  done
done
```

Çıktıyı **password manager'a kaydet** — bir daha üretemiyorsun, kayıp = volume'u silip baştan başlamak.

## 2. Env dosyalarını yaz (root-only)

```bash
# Klasörler
sudo mkdir -p /etc/imga/production /etc/imga/staging
sudo chmod 700 /etc/imga /etc/imga/production /etc/imga/staging
sudo chown root:root /etc/imga /etc/imga/production /etc/imga/staging
```

### 2.1. Production postgres.env

```bash
sudo tee /etc/imga/production/postgres.env > /dev/null <<'EOF'
POSTGRES_PASSWORD=<adim-1-de-uretilen-OWNER-parolasi>
IMGA_APP_PASSWORD=<APP-parolasi>
IMGA_ADMIN_PASSWORD=<ADMIN-parolasi>
EOF
sudo chmod 600 /etc/imga/production/postgres.env
```

### 2.2. Production api.env

```bash
# JWT secret üret
JWT_SECRET=$(openssl rand -base64 32)
echo "JWT (production): $JWT_SECRET   # password manager'a yaz"

# Şablonu doldur — DATABASE_URL'lerdeki <APP_PWD>/<ADMIN_PWD>/<OWNER_PWD>
# yerine ADIM 1'de üretilen parolaları yapıştır
sudo tee /etc/imga/production/api.env > /dev/null <<EOF
DATABASE_URL=postgresql+asyncpg://imga_app:<APP_PWD>@postgres:5432/imga
DATABASE_URL_ADMIN=postgresql+asyncpg://imga_admin:<ADMIN_PWD>@postgres:5432/imga
DATABASE_URL_OWNER=postgresql+asyncpg://imga_owner:<OWNER_PWD>@postgres:5432/imga
JWT_SECRET_KEY=$JWT_SECRET
IMGA_CORS_ORIGINS=https://app.imga.ai
IMGA_LLM_FALLBACK_ENABLED=false
ENVIRONMENT=production
LOG_LEVEL=info
EOF
sudo chmod 600 /etc/imga/production/api.env

unset JWT_SECRET
```

### 2.3. Staging — production'la birebir aynı yapı, farklı parolalarla

`infra/imga/staging/env.postgres.example` ve `infra/imga/staging/env.api.example` şablonlarını referans alarak aynı şekilde doldur. Staging için de bağımsız JWT secret ürettiğinden emin ol.

### 2.4. Doğrula

```bash
sudo ls -la /etc/imga/production/ /etc/imga/staging/
# postgres.env api.env  her ikisi de mode 600 root:root olmalı

# İçerikteki placeholder'lar ('<APP_PWD>' vb.) gerçek parolayla değiştirildi mi
sudo grep -F '<' /etc/imga/production/api.env /etc/imga/staging/api.env
# hiçbir çıktı vermemeli — '<' karakteri kalmadı demektir
```

## 3. Production stack'ini ayağa kaldır

```bash
cd /opt/imga/infra/imga/production
sudo docker compose build       # api ve web image'larını build et
# api: ~5-10 dk (BERT modelinin ilk indirilmesi + image içine baking ~440MB)
# web: ~2-4 dk (npm ci + next build)
```

`build` bitince:

```bash
sudo docker compose up -d
```

Container'lar healthcheck olmaya başlar. Postgres ~10-30 sn'de healthy. API ~60-120 sn (BERT model warmup). Web 5-10 sn.

```bash
# Durumu izle
sudo docker compose ps
# Hepsi "running (healthy)" olmalı, ~3 dk içinde
```

### 3.1. Migration çalıştır

İlk başlatmada init script `imga_owner` / `imga_app` / `imga_admin` rollerini yarattı; ama tablolar henüz yok. Alembic migration'ları bunu tamamlar:

```bash
sudo docker compose exec api alembic upgrade head
# "Running upgrade -> 0001_initial_schema_with_rls" ... "0010_..." gibi 10 migration satırı görmelisin
```

### 3.2. Smoke test (container içinden)

```bash
# API health
sudo docker compose exec api curl -fs http://localhost:8000/health
# {"status":"ok","version":"0.7.0",...}

# Web /login
sudo docker compose exec web wget -qO- http://localhost:3000/login | head -c 200
# HTML görmelisin
```

Hatâ varsa logları okumadan ileri gitme:

```bash
sudo docker compose logs api  | tail -50
sudo docker compose logs web  | tail -50
sudo docker compose logs postgres | tail -50
```

## 4. Staging stack'ini ayağa kaldır

```bash
cd /opt/imga/infra/imga/staging
sudo docker compose build      # api+web tekrar build edilir, NEXT_PUBLIC_API_URL farklı
sudo docker compose up -d
sudo docker compose exec api alembic upgrade head
sudo docker compose ps
```

Production'la aynı şekilde smoke test yap (`docker compose exec api curl …`).

## 5. Caddy config'lerini yerleştir + Caddy'i başlat

```bash
# Repo'daki şablonları /opt/shared/caddy/conf.d/ altına kopyala
cp /opt/imga/infra/imga/caddy/imga-production.conf /opt/shared/caddy/conf.d/
cp /opt/imga/infra/imga/caddy/imga-staging.conf    /opt/shared/caddy/conf.d/

ls -la /opt/shared/caddy/conf.d/
# imga-production.conf  imga-staging.conf  .gitkeep
```

Caddy ilk kez başlatılıyorsa:

```bash
cd /opt/shared/caddy
docker compose up -d
docker compose logs -f caddy
```

İlk birkaç saniye Caddy LE'den sertifika talep eder. Beklenen log satırları:

```text
{"level":"info","msg":"obtaining certificate","domain":"app.imga.ai"}
{"level":"info","msg":"certificate obtained successfully","domain":"app.imga.ai"}
... aynı dört subdomain için ...
```

`Ctrl+C` ile log takibinden çık (container çalışmaya devam eder).

Caddy zaten çalışıyorsa (önceki bir deploy):

```bash
docker compose -f /opt/shared/caddy/docker-compose.yml exec caddy \
  caddy reload --config /etc/caddy/Caddyfile
# "successfully reloaded"
```

## 6. Public smoke test

Lokal makineden (sunucu dışında):

```bash
# DNS resolve doğru mu
dig +short app.imga.ai api.imga.ai staging.imga.ai api-staging.imga.ai

# HTTPS yanıt
curl -I https://app.imga.ai
# HTTP/2 200, server: Caddy ya da Cloudflare (proxied modda)

curl -fs https://api.imga.ai/health
# {"status":"ok",...}

curl -I https://staging.imga.ai
curl -fs https://api-staging.imga.ai/health
```

Browser'da:
- `https://app.imga.ai` → Türkçe login sayfası, valid TLS sertifikası (kilit ikonu)
- `https://staging.imga.ai` → aynı

## 7. Süper-admin kullanıcı yarat (production)

İlk kullanıcı veritabanına manuel insert. `imga_owner` rolüyle alembic-yönetimli scripts/seed yöntemi yok henüz; SQL ile elle:

```bash
# Argon2 hash üret (Python'la — imga_api'nin security modülünü kullan)
sudo docker compose -f /opt/imga/infra/imga/production/docker-compose.yml \
  exec api python -c "
from imga_api.security import hash_password
import getpass
pw = getpass.getpass('Super-admin password: ')
print('HASH:', hash_password(pw))
"
# Çıkan hash'i bir yere kopyala. password'ü password manager'a kaydet.
```

```bash
# DB'ye insert
sudo docker compose -f /opt/imga/infra/imga/production/docker-compose.yml \
  exec postgres psql -U imga_owner -d imga <<SQL
INSERT INTO users (email, password_hash, full_name, is_super_admin)
VALUES ('admin@imga.ai', '<yukarida-uretilen-hash>', 'İmga Admin', true);
SQL
```

> Bunu Sprint 8.5'te `python -m imga_api.scripts.create_super_admin` interactive script'iyle değiştireceğiz; o zamana kadar bu manuel akış yeterli.

## 8. Browser'da end-to-end smoke test

1. `https://app.imga.ai/login` aç
2. `admin@imga.ai` + adım 7'de set ettiğin parola
3. Dashboard yükleniyor mu? (boş tenant olduğundan kart sayıları 0 olabilir)
4. **Yönetim** sidebar section'ı görünüyor mu (super-admin için)
5. **Tenant'lar** sayfasına git → "Yeni Tenant" → bir test tenant'ı oluştur
6. Davet linki kopyala, başka tarayıcıda aç → davet kabul et → yeni hesap

Hepsi çalışıyorsa İmga production'a alındı demektir.

## 9. Sıkça yapılan hatalar

### Caddy "no certificate available" döküyor

DNS hâlâ propagate olmamış olabilir, ya da Cloudflare proxy modunda SSL/TLS "Flexible" yerine "Full (strict)" gerek. `dig` ile kontrol et, gerekirse Cloudflare panel SSL/TLS settings'i değiştir.

### API "alembic: command not found"

Image build sorunu — `pip install -e packages/imga-api` yapılmamış. `sudo docker compose build api --no-cache` ile yeniden build et.

### Postgres init script hatası — "role already exists"

Volume önceden vardı (eski deploy denemesi). Tamamen sıfırlamak istersen:

```bash
cd /opt/imga/infra/imga/production
sudo docker compose down -v       # -v ile volume da silinir, DB sıfırlanır
# Sonra adım 3'ten devam et
```

> **DİKKAT:** Production'da müşteri verisi varken `down -v` veriyi siler. Sadece ilk kurulum / clean-room yeniden başlatma için.

### NEXT_PUBLIC_API_URL yanlış (web → api isteği başarısız)

Frontend image build-time'da NEXT_PUBLIC_API_URL'i bake eder. Compose dosyasında build args değiştiyse cache invalidate gerek:

```bash
sudo docker compose build web --no-cache
sudo docker compose up -d web
```

### CORS hatası

API env'de `IMGA_CORS_ORIGINS=https://app.imga.ai` doğru mu? Production'a `https://staging.imga.ai`'i de eklemek istersen virgülle ayır.

## 10. Alt-Faz 8.2 doğrulama checklist

Bittiğinde aşağıdakilerin hepsi yeşil olmalı:

- [ ] `dig +short app.imga.ai` → VPS IP (veya CF IP, proxied modda)
- [ ] `curl -fs https://api.imga.ai/health` → `{"status":"ok",...}`
- [ ] `curl -fs https://api-staging.imga.ai/health` → `{"status":"ok",...}`
- [ ] Browser: `https://app.imga.ai` → login sayfası, valid TLS
- [ ] Browser: `https://staging.imga.ai` → login sayfası, valid TLS
- [ ] Süper-admin login + yeni tenant create + davet flow çalışıyor
- [ ] `docker stats --no-stream` çıktısında her container limit içinde
- [ ] `sudo docker compose logs caddy | grep -i error` → boş

Bu checklist tamamlandığında Sprint 8.2 kapanır; Sprint 8.3 (CI/CD with GitHub Actions) sıraya gelir.
