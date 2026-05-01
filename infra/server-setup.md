# Sunucu kurulum runbook'u — Alt-Faz 8.1

Hedef: Contabo VPS 30 (Ubuntu 24.04) üzerinde production-ready bir
host hazırlamak. Bu doküman bir defa çalıştırılır; kurulum boyunca
her adımın sonunda doğrulama komutu verilir, çıktıyı tutmak gelecek
sunucu kurulumlarında karşılaştırma referansı olur.

> **Önemli güvenlik notu — kilitlenmemek için:**
> SSH hardening ve UFW adımlarında MEVCUT root SSH oturumunu
> KAPATMA. Yeni bir terminalden `ssh deploy@<ip>` ile bağlanıp test
> et. Eğer yeni oturum açılmıyorsa, hâlâ açık olan eski oturumdan
> son değişikliği geri al ve neden başarısız olduğunu çöz.

> **Manuel adımlar:** Bu alt-faz'ın tamamı sunucuda elle çalışır.
> Asistanın repo tarafında yapacağı tek şey bu runbook + 8.2
> adımında gelecek `docker-compose.prod.yml` / `Caddyfile`. VPS'e
> bağlanıp aşağıdaki komutları sırayla çalıştır.

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

# Hostname
hostnamectl set-hostname imga-prod
```

**Doğrula:**

```bash
hostnamectl       # Static hostname: imga-prod, Time zone: Europe/Istanbul
df -h /           # Boş alan kontrol
free -h           # RAM
```

Bu çıktıları bir yere kaydet — final raporda paylaşılacak.

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
ufw allow 80/tcp     # HTTP (Caddy 8.2'de)
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

> SSH portu 22'i değiştirmiyoruz (port-knocking gibi shenanigans
> Sprint 9'a kaldı). UFW'nin `allow 22/tcp` satırı olmadan açıp
> kapanırsan kendini kilitlersin — `enable`'dan ÖNCE 22'i ekle, ki
> spec sıralaması zaten doğru.

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

> `bantime = 3600` (1 saat) MVP için yeterli. Sprint 9'da
> progressive ban (`bantime.increment = true`) düşünülebilir.

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
> (v1 standalone) DEĞİL. Tüm `infra/docker-compose.prod.yml` komutları
> `docker compose` ile çalıştırılacak.

---

## 8. Disk usage alarm script (Sprint 8.5'e kadar mail edemeyecek, sadece log atacak)

```bash
sudo tee /usr/local/bin/disk-check.sh > /dev/null <<'EOF'
#!/bin/bash
# Disk kullanımı %80'i aştıysa /var/log/disk-alert.log'a yaz ve mail dene.
# Sprint 8.5'te Sentry / Uptime Robot kurulunca bu script Healthchecks.io
# ping'i ekleyecek; o zamana kadar log dosyası tek doğruluk kaynağı.
set -euo pipefail

USAGE=$(df / | awk 'NR==2 {print $5}' | tr -d '%')
THRESHOLD=80

if [ "$USAGE" -gt "$THRESHOLD" ]; then
  MSG="Disk usage at ${USAGE}% on $(hostname) at $(date -Iseconds)"
  echo "$MSG" >> /var/log/disk-alert.log
  # Mail isteğe bağlı — MTA yoksa sessizce başarısız olur
  if command -v mail >/dev/null 2>&1; then
    echo "$MSG" | mail -s "Disk Alert: ${USAGE}%" admin@imga.ai 2>/dev/null || true
  fi
fi
EOF
sudo chmod +x /usr/local/bin/disk-check.sh

# Cron — her gün 09:00 (saat dilimi: Europe/Istanbul, Adım 1'de set edildi)
echo "0 9 * * * /usr/local/bin/disk-check.sh" | sudo crontab -
```

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

Aşağıdaki komutları çalıştır, çıktılarını rapor için yapıştır:

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

# SSH erişim testi (lokal terminalden, sunucu DIŞINDA)
ssh root@<vps-ip>      # FAIL ettiğini gör
ssh deploy@<vps-ip>    # OK olduğunu gör
```

Checklist:

- [ ] `ssh root@vps` reddediliyor (Permission denied)
- [ ] `ssh deploy@vps` çalışıyor (key ile, şifre sormuyor)
- [ ] `docker ps` deploy user için sudo'suz çalışıyor
- [ ] `ufw status` → 22/80/443 active, default deny incoming
- [ ] `fail2ban-client status sshd` → enabled, currently banned: 0
- [ ] `unattended-upgrades --dry-run` → hata yok, security origin tanımlı
- [ ] Hostname: `imga-prod`, Timezone: `Europe/Istanbul`

---

## 10. Sprint 8.2 öncesi alan hazırlığı

Sıradaki alt-faz `infra/docker-compose.prod.yml` ve `Caddyfile`'ı
sunucuya yerleştirecek. Şimdiden alanı oluştur:

```bash
sudo mkdir -p /opt/imga
sudo chown deploy:deploy /opt/imga

# Secrets dizini (root-only, 8.2'de doldurulacak)
sudo mkdir -p /etc/imga
sudo chmod 700 /etc/imga
sudo chown root:root /etc/imga
```

Production env dosyaları 8.2 başında repo şablonundan üretilecek.

---

## Geri dönüş planı (acil durum)

Sunucu erişimi kaybolursa:

1. **Contabo panel'inden VNC console** — root password ile kurtarma
   (Contabo email'inde ilk gönderilen geçici parolayı kullan; eğer
   değiştirildiyse Contabo support → reset).
2. UFW'i geçici olarak kapat: `ufw disable` (sadece kurtarma için).
3. SSH config'in son halini geri al:
   ```bash
   rm /etc/ssh/sshd_config.d/99-hardening.conf
   systemctl reload ssh
   ```
4. Tekrar ayağa kalkınca aynı runbook'u baştan uygula, ama her
   adımdan sonra YENI session ile doğrula.

> Cron job, fail2ban veya unattended-upgrades **SSH erişimini
> doğrudan etkilemez**. Erişim kaybı genelde SSH config tipo'su veya
> UFW yanlış sıralamasından gelir.

---

## Sonraki adım

Bu runbook'u sırayla çalıştır. Her adımdaki **Doğrula** kısmını
geç. Bittiğinde §9'daki final checklist'i ve aşağıdaki komutların
çıktılarını rapora ekle:

```
hostnamectl
df -h /
free -h
docker --version
docker compose version
sudo ufw status verbose
sudo fail2ban-client status sshd
```

Asistan bu çıktılarla 8.1'i kapatıp 8.2 (DNS Cloudflare'e taşıma +
Caddy + docker-compose.prod.yml) iş paketine geçer.
