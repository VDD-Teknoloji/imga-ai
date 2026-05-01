# Sunucu kurulum runbook'u — multi-project foundation

Hedef: Contabo VPS 30 (Ubuntu 24.04) üzerinde production-ready, **çok
proje barındırabilir** bir host hazırlamak. Bu doküman tek başına
yeterlidir; sırasıyla uygulandığında sunucu şu hâle gelir:

- Sertleştirilmiş SSH, deploy kullanıcısı, UFW, fail2ban, otomatik
  güvenlik yamaları, Docker.
- `/opt/shared/` altında **tek Caddy reverse proxy** (auto-TLS,
  zero-downtime reload, conf.d import pattern).
- `/opt/shared/postgres/` altında **shared Postgres** instance'ı
  (yalnızca statik / küçük site projeleri için; production SaaS
  projeleri kendi izole Postgres'lerini /opt/`<proje>`/ altında
  taşır).
- `caddy-public` ve `shared-db` Docker network'leri hazır.
- Her yeni projeyi eklemek için tekrar uygulanabilir kalıp.

Tasarım kararları (neden böyle?) için: `infra/multi-project-architecture.md`.

> **Önemli güvenlik notu — kilitlenmemek için:**
> SSH hardening ve UFW adımlarında MEVCUT root SSH oturumunu
> KAPATMA. Yeni bir terminalden `ssh deploy@<ip>` ile bağlanıp test
> et. Eğer yeni oturum açılmıyorsa, hâlâ açık olan eski oturumdan
> son değişikliği geri al ve neden başarısız olduğunu çöz.
>
> **Bu doküman ne zaman uygulanır?** Yeni boş bir Contabo (veya
> benzer) VPS provisioning'inde tek seferlik. Tamamlandığında
> sunucu üzerinde proje deploy etmek için altyapı hazır olur;
> her proje kendi compose dosyasıyla ayağa kalkar (§10.6 pattern).

---

## 0. Ön koşullar

- Contabo Cloud VPS 30 instance ayağa kalkmış olmalı, Ubuntu 24.04
  imajıyla provisioned olmalı.
- Public IP adresi elinde olmalı (`<vps-ip>`).
- Root SSH erişimi public-key ile çalışıyor olmalı:

  ```bash
  ssh root@<vps-ip>
  ```

---

## 1. Sistem hazırlığı

```bash
# Mevcut paketleri güncelle
apt update && apt upgrade -y

# Sürekli kullanılacak araçları kur
apt install -y curl git ufw fail2ban unattended-upgrades htop ncdu

# Saat dilimi
timedatectl set-timezone Europe/Istanbul

# Hostname (proje-agnostic; birden fazla proje barındıracak)
hostnamectl set-hostname app-server-1
```

**Doğrula:**

```bash
hostnamectl       # Static hostname: app-server-1, Time zone: Europe/Istanbul
df -h /           # Boş alan kontrol
free -h           # RAM
```

Bu çıktıları bir yere kaydet — kurulum doğrulamasında karşılaştırma
referansı olarak işine yarayacak.

---

## 2. `deploy` kullanıcısı + SSH keys

```bash
# Yeni kullanıcı (root yerine bu kullanılacak)
adduser deploy --disabled-password
usermod -aG sudo deploy

# Root'un authorized_keys'ini deploy'a kopyala
mkdir -p /home/deploy/.ssh
cp /root/.ssh/authorized_keys /home/deploy/.ssh/
chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys

# Passwordless sudo (deploy için)
echo "deploy ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/deploy
chmod 440 /etc/sudoers.d/deploy
```

**Doğrula — bu test BAŞARILI OLMADAN bir sonraki adıma geçme:**

Yeni bir terminalde:

```bash
ssh deploy@<vps-ip>     # şifresiz key ile girmeli
sudo whoami             # "root" dönmeli, şifre sormamalı
exit                    # deploy oturumundan çık
```

Bu test başarısızsa, **mevcut root oturumunda** sorunu çöz. Sıkça
görülen hatalar:

- `authorized_keys` permission'ları yanlış → `chmod 700/600` tekrar uygula.
- SSH key kopyalanırken `chown` unutulmuş → ev dizini hâlâ `root` sahipliğinde olabilir.

---

## 3. SSH hardening

```bash
# Override config (dağıtım upgrade'i base /etc/ssh/sshd_config'i değiştirebilir;
# *.conf dosyaları sshd_config'in sonunda source edildiği için hardening
# burada güvende kalır).
cat > /etc/ssh/sshd_config.d/99-hardening.conf <<'EOF'
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
ClientAliveInterval 300
ClientAliveCountMax 2
EOF

# Config'i syntax-check et (yanlış syntax sshd'yi kapatabilir, dikkat)
sshd -t

# Reload (restart yerine reload — açık oturumları düşürmez)
systemctl reload ssh
```

**Doğrula — KESİNLİKLE şu sırayla:**

1. **Mevcut root oturumunu KAPATMA.**
2. Yeni terminalde:

   ```bash
   ssh deploy@<vps-ip>     # ÇALIŞMALI
   ssh root@<vps-ip>       # REDDEDİLMELİ ("Permission denied" + key auth fail)
   ```

3. Her iki test de doğru sonuç verirse, mevcut root oturumunu kapatabilirsin.

`ssh root@...` reddedilmiyorsa hardening uygulanmamıştır. `sshd -t`
syntax error vermiş olabilir — config'i tekrar kontrol et, sonra
`systemctl reload ssh`.

---

## 4. UFW firewall

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp     # SSH
ufw allow 80/tcp     # HTTP (Caddy — §10.3'te ayağa kalkacak)
ufw allow 443/tcp    # HTTPS
ufw enable           # "Command may disrupt existing ssh connections" → y
```

**Doğrula:**

```bash
ufw status verbose
# Status: active
# 22/tcp ALLOW IN Anywhere
# 80/tcp ALLOW IN Anywhere
# 443/tcp ALLOW IN Anywhere
```

> SSH portu 22'i değiştirmiyoruz (varsayılan, IDS / fail2ban
> yetiyor). UFW'nin `allow 22/tcp` satırı olmadan açıp kapanırsan
> kendini kilitlersin — `enable`'dan ÖNCE 22'i ekle, ki yukarıdaki
> sıralama zaten doğru.

---

## 5. fail2ban

```bash
# /etc/fail2ban/jail.local — ana config'i override eder
cat > /etc/fail2ban/jail.local <<'EOF'
[DEFAULT]
bantime  = 3600
findtime = 600
maxretry = 5
backend  = systemd

[sshd]
enabled = true
EOF

systemctl restart fail2ban
```

**Doğrula:**

```bash
fail2ban-client status sshd
# Status for the jail: sshd
# |- Filter
# |  |- Currently failed: 0
# |  |- Total failed: 0
# `- Actions
#    |- Currently banned: 0
```

> `bantime = 3600` (1 saat) ilk kurulum için makul. Saldırı volümü
> arttığında `[DEFAULT]` altına `bantime.increment = true` +
> `bantime.factor = 2` ekleyerek progressive ban'a geçilebilir.

---

## 6. Otomatik güvenlik güncellemeleri

```bash
dpkg-reconfigure -plow unattended-upgrades
# "Automatically download and install stable updates?" → Yes
```

**Doğrula:**

```bash
unattended-upgrades --dry-run --debug 2>&1 | tail -20
# "Allowed origins are: ['origin=Ubuntu,archive=noble-security', ...]"
# "No packages found that can be upgraded unattended" (veya pending listesi)
```

`/etc/apt/apt.conf.d/50unattended-upgrades` dosyasında varsayılan
olarak sadece security upgrade'ler aktif — bu doğru, bütün distro
upgrade'lerini otomatik yapmak istemiyoruz.

Otomatik reboot kapalı bırak; planlı bakım tercih edilir. İstersen:

```bash
# /etc/apt/apt.conf.d/50unattended-upgrades dosyasında:
# Unattended-Upgrade::Automatic-Reboot "false";   ← varsayılan
```

---

## 7. Docker + Docker Compose

```bash
# Docker official install script (apt repo + GPG key + paket kurulumu)
curl -fsSL https://get.docker.com | sh

# deploy kullanıcısını docker grubuna ekle (sudo'suz `docker ps` çalışsın diye)
usermod -aG docker deploy
```

**deploy oturumunda group apply için yeniden bağlan:**

```bash
exit       # mevcut root oturumundan çık
ssh deploy@<vps-ip>

# Test
docker ps                     # boş tablo (henüz container yok)
docker compose version        # v2.x.x
docker run --rm hello-world   # smoke test, sonra cleanup
```

> `docker compose` (v2 plugin) kullanıyoruz, `docker-compose`
> (v1 standalone) DEĞİL. Bütün proje compose dosyaları
> `docker compose` ile çalıştırılır.

---

## 8. Disk usage alarm script

Sunucuda monitoring (Sentry / Healthchecks.io / mail relay) henüz
yokken bile disk dolması erken yakalansın diye basit bir cron
script'i. Eşik aşıldığında her durumda `/var/log/disk-alert.log`'a
yazar; `mail` komutu varsa ek olarak admin'e e-posta dener.

```bash
sudo tee /usr/local/bin/disk-check.sh > /dev/null <<'EOF'
#!/bin/bash
# Disk kullanımı %80'i aştıysa /var/log/disk-alert.log'a yaz ve
# mümkünse mail dene. MTA yoksa script sessizce log'a yazıp çıkar.
# Daha sonra Healthchecks.io ping'i eklenirse, fail durumu da merkezi
# bir yerden görünür hale gelir.
set -euo pipefail

USAGE=$(df / | awk 'NR==2 {print $5}' | tr -d '%')
THRESHOLD=80
ALERT_EMAIL="${DISK_ALERT_EMAIL:-root}"

if [ "$USAGE" -gt "$THRESHOLD" ]; then
  MSG="Disk usage at ${USAGE}% on $(hostname) at $(date -Iseconds)"
  echo "$MSG" >> /var/log/disk-alert.log
  if command -v mail >/dev/null 2>&1; then
    echo "$MSG" | mail -s "Disk Alert: ${USAGE}%" "$ALERT_EMAIL" 2>/dev/null || true
  fi
fi
EOF
sudo chmod +x /usr/local/bin/disk-check.sh

# Cron — her gün 09:00 (saat dilimi: Europe/Istanbul, §1'de set edildi)
echo "0 9 * * * /usr/local/bin/disk-check.sh" | sudo crontab -
```

> Mail adresi `DISK_ALERT_EMAIL` env değişkeninden alınır; yoksa
> `root@localhost`'a gönderir. Mail relay kurulduğunda
> `/etc/cron.d/disk-check-env` ile değişken set edilebilir.

**Doğrula:**

```bash
# Script'i elle koş, hata vermemeli
sudo /usr/local/bin/disk-check.sh
# Eşik aşılmamışsa hiçbir çıktı yok, log dosyası yok — bu beklenen.

# Crontab kontrolü
sudo crontab -l
# 0 9 * * * /usr/local/bin/disk-check.sh
```

---

## 9. Final doğrulama checklist

§10 multi-project foundation'ı uyguladıktan sonra aşağıdaki komutları
çalıştır, çıktılarını dokümantasyon olarak sakla.

```bash
# Sistem bilgisi
hostnamectl
df -h /
free -h
uptime

# Docker
docker --version
docker compose version
docker ps

# Güvenlik
sudo ufw status verbose
sudo fail2ban-client status sshd
sudo unattended-upgrades --dry-run 2>&1 | tail -5

# Multi-project foundation
ls -la /opt/shared/
ls -la /etc/shared-postgres/
docker network ls | grep -E '(caddy-public|shared-db)'

# SSH erişim testi (lokal terminalden, sunucu DIŞINDA)
ssh root@<vps-ip>      # FAIL ettiğini gör
ssh deploy@<vps-ip>    # OK olduğunu gör
```

Checklist — sistem:

- [ ] `ssh root@vps` reddediliyor (Permission denied)
- [ ] `ssh deploy@vps` çalışıyor (key ile, şifre sormuyor)
- [ ] `docker ps` deploy user için sudo'suz çalışıyor
- [ ] `ufw status` → 22/80/443 active, default deny incoming
- [ ] `fail2ban-client status sshd` → enabled, currently banned: 0
- [ ] `unattended-upgrades --dry-run` → hata yok, security origin tanımlı
- [ ] Hostname: `app-server-1`, Timezone: `Europe/Istanbul`

Checklist — multi-project foundation:

- [ ] `/opt/shared/caddy/` ve `/opt/shared/postgres/` var, sahibi `deploy:deploy`
- [ ] `/etc/shared-postgres/postgres-root.env` var, mode 600 root:root
- [ ] `docker network ls` → `caddy-public` + `shared-db` listede
- [ ] `/opt/shared/caddy/docker-compose.yml` ve `Caddyfile` valid (`docker compose config`)
- [ ] `/opt/shared/postgres/docker-compose.yml` valid
- [ ] §10.6'daki yeni proje ekleme pattern'i okundu, anlaşıldı

---

## 10. Multi-project foundation

Sunucuda birden fazla proje çalışacak (production SaaS'lar, statik
siteler, ileride mail). Bu adımda paylaşılan altyapı (shared Caddy +
shared Postgres) ve klasör yapısı kurulur. Tasarım kararlarının
gerekçesi için `infra/multi-project-architecture.md`.

### 10.1. Klasör yapısı

```bash
# Proje kökleri (deploy-owned)
sudo mkdir -p /opt/shared/caddy/conf.d
sudo mkdir -p /opt/shared/postgres/init
sudo chown -R deploy:deploy /opt/shared

# .gitkeep ile boş conf.d dizinini görünür tut
touch /opt/shared/caddy/conf.d/.gitkeep

# Secrets dizinleri (root-only, mode 700 — başkası listeleyemesin)
sudo mkdir -p /etc/shared-postgres
sudo chmod 700 /etc/shared-postgres
sudo chown root:root /etc/shared-postgres
```

**Doğrula:**

```bash
ls -la /opt/shared/
# drwxr-xr-x deploy deploy ... caddy
# drwxr-xr-x deploy deploy ... postgres

ls -la /etc/shared-postgres/
# drwx------ root root  (henüz dosya yok)
```

### 10.2. Docker network'leri

İki external network oluştur. "External" demek: compose'ların kendi
yarattığı değil, host'ta önceden var olan ve birden fazla compose'un
join ettiği network'ler.

```bash
docker network create caddy-public
docker network create shared-db
```

**Network rollerine dair kural:**

| Network | Kim katılır | Açık port |
|---|---|---|
| `caddy-public` | Caddy + her projenin public-facing container'ları (web, api) | 80/443'ten dışa açık |
| `shared-db` | Shared Postgres + statik/küçük site projeleri | İçeride kapalı, dışarıya yok |
| `<proje>-internal` | Production SaaS'in kendi container'ları (kendi DB dahil) | İçeride kapalı |

Postgres container'ları **hiçbir public network'te değildir**;
yalnız `shared-db` veya `<proje>-internal` üzerinden erişilebilir.

**Doğrula:**

```bash
docker network ls
# NAME           DRIVER  SCOPE
# caddy-public   bridge  local
# shared-db      bridge  local
# bridge / host / none (Docker default'ları)
```

### 10.3. Shared Caddy stack

`/opt/shared/caddy/docker-compose.yml`:

```yaml
services:
  caddy:
    image: caddy:2-alpine
    container_name: caddy
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - ./conf.d:/etc/caddy/conf.d:ro
      - caddy_data:/data
      - caddy_config:/config
    networks:
      - caddy-public
    deploy:
      resources:
        limits:
          memory: 256M

networks:
  caddy-public:
    external: true

volumes:
  caddy_data:
  caddy_config:
```

`/opt/shared/caddy/Caddyfile`:

```caddy
{
    # Let's Encrypt için yöneticinin e-postası — kayıt onayı buraya gelir.
    # Geçerli, izlenen bir kutu olmalı; LE bu adresi sertifika expiry
    # uyarıları için de kullanır.
    email admin@<senin-domain>

    # Production'da `auto_https off` YAPMA — auto-TLS açık kalsın.
}

# Her proje conf.d altındaki kendi .conf dosyasını import eder.
# Yeni proje eklemek = yeni .conf dosyası + caddy reload.
import /etc/caddy/conf.d/*.conf
```

> **Caddyfile şablonundaki `admin@<senin-domain>`**'i gerçek bir
> adresle değiştir. Bu adres LE hesabına bağlanır; sonradan
> değiştirmek için Caddy'yi yeniden başlatman gerekir.

**Yazıp kaydettikten sonra**, Caddyfile'ı şimdilik validate et ama
**başlatma**:

```bash
cd /opt/shared/caddy
docker compose config > /dev/null && echo "compose OK"
```

`docker compose up -d` komutunu **bu adımda çalıştırma** — `conf.d/`
boşken Caddy ayağa kalkar ama hiçbir site servis etmez. İlk gerçek
proje config'i (`conf.d/<proje>.conf`) gelince başlatılır
(§10.6 pattern).

### 10.4. Shared Postgres stack

Yalnızca statik / küçük site projeleri için. Production SaaS'lar
kendi izole Postgres'lerini kullanır
(`infra/multi-project-architecture.md` Karar 1).

**Önce root credentials'ı oluştur:**

```bash
# Güçlü bir parola üret
PG_ROOT_PW=$(openssl rand -base64 32)

sudo tee /etc/shared-postgres/postgres-root.env > /dev/null <<EOF
POSTGRES_USER=postgres
POSTGRES_PASSWORD=${PG_ROOT_PW}
POSTGRES_DB=postgres
EOF

sudo chmod 600 /etc/shared-postgres/postgres-root.env

# Üretilen parolayı şifre yöneticine yaz; .env dosyasında zaten,
# ama bir password manager kayıtı geri yükleme senaryolarında işe yarar.
echo "Postgres root password: ${PG_ROOT_PW}"
unset PG_ROOT_PW
```

`/opt/shared/postgres/docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:17-alpine
    container_name: shared-postgres
    restart: unless-stopped
    env_file: /etc/shared-postgres/postgres-root.env
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init:/docker-entrypoint-initdb.d:ro
    networks:
      - shared-db
    # Port expose YOK — sadece shared-db network'ünden erişilir.
    deploy:
      resources:
        limits:
          memory: 1G
          cpus: '2'

networks:
  shared-db:
    external: true

volumes:
  postgres_data:
```

`/opt/shared/postgres/init/01-create-databases.sh` — şu an boş
ama yapı için yer tutucu (`init/` boş klasörse `volume mount`
sorun olmaz, ama `.gitkeep` benzeri bir dosya tutmak doğal).

```bash
cat > /opt/shared/postgres/init/01-create-databases.sh <<'EOF'
#!/bin/bash
# Postgres ilk başlatıldığında çalışan init script'i.
# Yeni proje eklemek için: §10.6'daki "statik site" pattern'ini takip et —
# her proje kendi DB'sini ad-hoc CREATE DATABASE ile oluşturur.
set -e
echo "shared-postgres initialized, ready for project DB creation"
EOF
chmod +x /opt/shared/postgres/init/01-create-databases.sh
```

**Compose dosyasını validate et ama başlatma:**

```bash
cd /opt/shared/postgres
docker compose config > /dev/null && echo "compose OK"
```

İlk site projesi gelene kadar Postgres'i çalıştırmak gereksiz
kaynak tüketimi. İlk projeyle birlikte ayağa kaldırılır.

### 10.5. Doğrulama

```bash
# Klasör yapısı
ls -la /opt/shared/
# total ...
# drwxr-xr-x deploy deploy caddy
# drwxr-xr-x deploy deploy postgres

ls -la /etc/shared-postgres/
# -rw------- root root postgres-root.env

# Network'ler
docker network ls | grep -E '(caddy-public|shared-db)'
# Her ikisi de listede

# Compose dosyaları valid
cd /opt/shared/caddy && docker compose config > /dev/null && echo "caddy compose OK"
cd /opt/shared/postgres && docker compose config > /dev/null && echo "postgres compose OK"

# Caddyfile syntax (image kullanarak validate, çalıştırmadan)
docker run --rm -v /opt/shared/caddy/Caddyfile:/etc/caddy/Caddyfile:ro \
  caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile
# "Valid configuration" mesajı görmelisin
```

### 10.6. Yeni proje ekleme pattern

Hangi kategori olduğunu önce belirle:

- **Production SaaS** (kendi Postgres ile): hassas veri, RLS,
  bağımsız version upgrade isteyen projeler.
- **Statik / küçük site** (shared Postgres ile): blog, portfolio,
  landing page, CMS-light.

#### Production SaaS deploy pattern

```bash
# 1. Klasör yapısı
sudo mkdir -p /opt/<proje>
sudo chown deploy:deploy /opt/<proje>

# 2. Secrets klasörü
sudo mkdir -p /etc/<proje>
sudo chmod 700 /etc/<proje>
sudo chown root:root /etc/<proje>
# /etc/<proje>/<proje>.env içine DATABASE_URL, JWT secrets vb.
# Mode 600, root:root.

# 3. Proje compose dosyasını /opt/<proje>/docker-compose.yml'a koy.
#    Compose dosyasında 2 network kullan:
#      - <proje>-internal  → kendi Postgres container'ı için
#      - caddy-public      → web/api container'ları Caddy'den görünmek için
#    İki network de external: false (compose kendi yaratır), AMA
#    caddy-public external: true ile join eder.

# 4. Caddy config ekle
sudo -u deploy nano /opt/shared/caddy/conf.d/<proje>.conf
# Örnek içerik:
#   app.<proje>.com, api.<proje>.com {
#     reverse_proxy <proje>-web:3000
#   }
# Bkz. Caddy docs: https://caddyserver.com/docs/caddyfile

# 5. Caddy ilk seferse başlat, değilse zero-downtime reload
cd /opt/shared/caddy
docker compose up -d            # ilk başlatma
# VEYA mevcut Caddy varsa:
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile

# 6. Proje stack'ini ayağa kaldır
cd /opt/<proje>
docker compose up -d

# 7. DNS — Cloudflare'de (veya hangi DNS provider) A kaydı:
#    app.<proje>.com → VPS IP, proxied
#    Caddy auto-TLS LE'den sertifika alır ve refresh'ler.
```

#### Statik / küçük site deploy pattern

```bash
# 1. Klasör yapısı
sudo mkdir -p /opt/<site>
sudo chown deploy:deploy /opt/<site>

# 2. Shared Postgres ayakta değilse bir kez ayağa kaldır
cd /opt/shared/postgres
docker compose ps -q postgres >/dev/null 2>&1 || docker compose up -d
# 5-10 sn bekle, healthcheck:
docker exec shared-postgres pg_isready -U postgres
# "accepting connections"

# 3. DB + user yarat
SITE_PW=$(openssl rand -base64 24)
docker exec -i shared-postgres psql -U postgres <<SQL
CREATE DATABASE <site>_prod;
CREATE USER <site>_app WITH ENCRYPTED PASSWORD '${SITE_PW}';
GRANT ALL ON DATABASE <site>_prod TO <site>_app;
SQL
echo "Site DB password: ${SITE_PW}  (şifre yöneticine yaz)"
unset SITE_PW

# 4. Secrets
sudo mkdir -p /etc/<site>
sudo chmod 700 /etc/<site>
sudo tee /etc/<site>/<site>.env > /dev/null <<EOF
DATABASE_URL=postgresql://<site>_app:<password-yukarıdaki>@shared-postgres:5432/<site>_prod
EOF
sudo chmod 600 /etc/<site>/<site>.env

# 5. Compose dosyasında 2 network:
#    - shared-db     → external, Postgres'e ulaşmak için
#    - caddy-public  → external, Caddy'den görünmek için

# 6-7-8. Caddy config + reload + stack başlatma — production SaaS pattern'i
#        ile aynı.
```

### 10.7. Resource limits — zorunlu

24 GB RAM'i kontrolsüz paylaşmak runaway memory leak'lerinde tüm
sunucuyu çökertir. **Her proje compose'unda `deploy.resources.limits`
zorunlu.**

Tipik dağılım (24 GB toplam, referans):

| Bileşen | Memory limit | CPU limit |
|---|---|---|
| `shared-caddy` | 256 MB | 1 vCPU |
| `shared-postgres` | 1 GB | 2 vCPU |
| Production SaaS (api + web + kendi postgres) | ~6 GB | 4 vCPU |
| Statik site (web container) | 512 MB | 1 vCPU |
| Sistem reserve | ~4 GB | — |

Toplam container limit hedefi: ~16-18 GB; geri kalan 6-8 GB
headroom (cache, log buffer, kernel).

`docker stats` ile gerçek kullanımı izleyebilirsin:

```bash
docker stats --no-stream
# CONTAINER    CPU %   MEM USAGE / LIMIT  ...
```

Bir proje sürekli limit'e dayanıyorsa, ya limit'i yükselt ya da
kodu profile et — **limit'i kaldırma**, kontrol mekanizmasını
değiştirme.

---

## 11. Sıkça yapılan hatalar (troubleshooting)

### Caddy başlamıyor

```bash
docker logs caddy
```

Yaygın sebepler: Caddyfile syntax hatası (validate adımı atlanmış),
port 80/443 zaten dolu. Port kontrolü:

```bash
sudo ss -tlnp | grep -E ':80|:443'
```

Eski bir webserver (apache2 / nginx) çalışıyor olabilir:

```bash
sudo systemctl disable --now apache2 nginx 2>/dev/null || true
```

### `docker network not found: caddy-public` (veya `shared-db`)

§10.2 atlanmış. Çözüm:

```bash
docker network create caddy-public
docker network create shared-db
```

### Shared Postgres'e bağlanılamıyor

Proje compose'una `shared-db` network'ü join edilmemiştir, ya da
`DATABASE_URL`'de hostname `shared-postgres` (container name) yerine
IP yazılmış. Container-to-container DNS Docker'ın yerleşik özelliği —
host adı container ismidir.

### Caddy reload sertifika kaybediyor

`caddy_data` volume'u silinmiş olabilir. Volume'ları KORU:

```bash
docker volume ls | grep caddy
# caddy_caddy_data, caddy_caddy_config
```

Bu volume'lar silindiyse Let's Encrypt rate limit'ine takılma riski
var (haftalık 50 sertifika / hesap). Yeni sertifikalar staging
environment'tan al, sonra production'a geç.

### Bir proje diğerini etkiliyor (yavaşlama / OOM)

Resource limits kontrol et:

```bash
docker stats --no-stream
```

Limit'i olmayan / aşırı tüketen container varsa compose'una
`deploy.resources.limits` ekle, restart et.

### deploy user'a yeni grup eklendiğinde sudo'suz docker çalışmıyor

`usermod -aG docker deploy`'dan sonra mevcut SSH oturumunda group
apply olmaz; çık ve tekrar bağlan (`exit; ssh deploy@...`).

---

## Geri dönüş planı (acil durum — sunucu erişimi kaybı)

1. **Contabo panel'inden VNC console** — root password ile
   kurtarma. Cloud panel → instance → "Console" / "VNC". Contabo
   email'inde ilk gönderilen geçici parolayı kullan; eğer
   değiştirildiyse Contabo support → reset.

2. **UFW'i geçici olarak kapat** (sadece kurtarma için):

   ```bash
   ufw disable
   ```

3. **SSH config'in son halini geri al:**

   ```bash
   rm /etc/ssh/sshd_config.d/99-hardening.conf
   systemctl reload ssh
   ```

4. **Erişim geri geldiğinde**: aynı runbook'u baştan uygula, ama her
   adımdan sonra YENİ session ile doğrula.

> Cron job, fail2ban veya unattended-upgrades **SSH erişimini
> doğrudan etkilemez**. Erişim kaybı genelde SSH config typo'su
> veya UFW yanlış sıralamasından gelir.
>
> Docker network silinmiş olsa bile SSH erişimini etkilemez —
> `docker network create caddy-public shared-db` ile yeniden
> oluşturulur, container'lar `--network` ile bağlanır.
