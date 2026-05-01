# Multi-project sunucu mimarisi

Bu doküman tasarım kararlarını ve "neden böyle yapıldı"yı açıklar.
Pratik adımlar için `infra/server-setup.md` runbook'una bak.

Hedef: **tek bir Contabo VPS 30**'da (8 vCPU / 24 GB RAM / 200 GB
NVMe veya 400 GB SSD) 3-7 farklı proje çalıştırabilmek. İmga.AI
production SaaS, yan projeler (blog, portfolio), ileride mail
sunucusu — hepsi aynı host, ama izolasyon ve operasyon disiplini
korunarak.

---

## Karar 1 — İmga'nın kendi Postgres'i, küçük siteler shared

### Sebepler

1. **Version upgrade riski.** Postgres 17 → 18 upgrade'i geldiğinde
   shared instance'ta tüm projeler birlikte upgrade edilmek
   zorunda. İmga RLS+FORCE kullanıyor, hassas — kendi takvimimizde
   upgrade etmek istiyoruz, başka projenin acil hot-fix'iyle
   sürüklenmek istemiyoruz.

2. **Performans izolasyonu (noisy neighbor).** İmga'nın analiz
   pipeline'ı bazen ağır query atar (review aggregate, ticket
   stats, BERT inference window'u). Aynı Postgres'te küçük blog'un
   bir search query'si yavaşlayabilir, ya da tam tersi blog'un
   N+1'i İmga'nın p99 latency'sini bozabilir. Ayrı Postgres'te
   her proje kendi connection pool, work_mem, shared_buffers
   limiti ile yaşar.

3. **Backup granularity.** `pg_dump` tek DB için çalışır ama PITR
   (Point-in-Time Recovery) instance seviyesinde. İmga'yı 1 saat
   öncesine geri almak istediğinde shared instance'ta diğer
   projeleri de geriye almış olursun. Ayrı instance'larda her
   projenin kendi WAL stream'i, kendi snapshot'ı var.

4. **Compliance / sertifikasyon yolu.** İlerde KVKK denetimi
   gelirse "İmga müşteri verileri başka projelerle aynı DB
   instance'ında değildir" demek lazım. Mimariyi gün 1'de doğru
   kurmak, sonradan geri dönmekten kolay.

### Hangi proje hangi kategoride?

| Kategori | Postgres modeli | Hangi projeler |
|---|---|---|
| Production SaaS | Kendi Postgres, kendi `<proje>-internal` network | İmga.AI; gelecek hassas / RLS / multi-tenant SaaS'lar |
| Statik / küçük site | Shared Postgres (`shared-db` network) | Blog, portfolio, kurumsal landing, küçük CMS-light siteler |

Sınır net değilse: emin değilsen "kendi Postgres" tarafını seç —
sonradan ayrı instance'a taşımak shared'a taşımaktan zordur.

---

## Karar 2 — Tek Caddy, conf.d pattern

Her proje için ayrı reverse proxy çalıştırmak yerine **tek Caddy +
`conf.d/` import pattern**.

### Sebepler

- **Tek 80/443 portu.** Linux'ta tek process root-priv'siz portu
  bind etmiyor; her proje kendi reverse proxy'sini istese host
  network kullanmak zorunda kalır, kompleksite ve port çakışması
  artar. Tek Caddy bu işi tek elden yapar.
- **Tek TLS yönetimi.** Auto-TLS sertifika depolaması (`caddy_data`
  volume) tek yerde. Renewal, rate limit hesabı, OCSP cache
  ortak. Çoklu proxy modelinde her biri kendi LE hesabını kurardı.
- **Zero-downtime reload.** Yeni proje eklerken `caddy reload`
  yapmak yeterli — başka container'lar etkilenmiyor. Tek-monolitik
  config dosyasını editlemek yerine `conf.d/<proje>.conf`
  yaratmak/silmek değişiklik sınırını net çiziyor.
- **Operasyonel basitlik.** `docker logs caddy` tek yerden tüm
  trafiği gösterir. Health endpoint'leri, metrik export'u tek
  yerden.

### Maliyet

- Caddy down olursa **tüm projeler down**. Tek nokta-failure.
  Ama: Caddy konteyner restart'ı saniyeler, `restart: unless-stopped`
  ile kurtarma otomatik. Multi-instance HA Sprint 9+ konusu
  (load balancer önüne 2 Caddy gerekirse, ama bu tek-VPS senaryosu
  için over-engineering).

---

## Karar 3 — Network izolasyonu (3 katman)

Üç Docker network seviyesi:

```text
caddy-public         (external)  — Caddy ↔ public-facing container'lar
shared-db            (external)  — shared Postgres ↔ küçük site projeleri
<proje>-internal     (compose-local) — proje içi container'lar (kendi DB dahil)
```

### Public-facing container nasıl davranır

Bir production SaaS'in `web` ve `api` container'ları **iki network'e
de** bağlanır:

- `<proje>-internal` → kendi DB'sine ulaşmak için
- `caddy-public` → Caddy'den HTTP isteklerini alabilmek için

Postgres container'ı **sadece** `<proje>-internal`'a bağlı. Caddy
ve diğer projeler ona ulaşamaz.

### Statik site farkı

Statik site `web` container'ı:

- `shared-db` → `shared-postgres`'e ulaşmak için
- `caddy-public` → Caddy'den isteğe ulaşılabilir olmak için

Burada `<site>-internal` yok çünkü tek container var (web), izole
bir intranet'e gerek yok.

### Net sonuç

İmga'nın Postgres'ine başka proje **erişemez**. Caddy bile
göremez (zaten ihtiyacı yok — uygulama sunucusuna proxy'liyor,
DB'ye değil).

---

## Karar 4 — Resource limits zorunlu

24 GB RAM kontrolsüz paylaşılırsa runaway memory leak'lerinde tüm
sunucu çöker. **Her proje compose'unda `deploy.resources.limits`
zorunlu.** Bu kural tek başına en kritik production hijyen
maddesidir.

### Tipik dağılım (referans)

| Bileşen | Memory | CPU | Not |
|---|---|---|---|
| `shared-caddy` | 256 MB | 1 | Reverse proxy, çok az RAM yer |
| `shared-postgres` | 1 GB | 2 | Küçük siteler için yeterli |
| Production SaaS (api+web+postgres) | 6 GB | 4 | İmga için makul |
| Statik site | 512 MB | 1 | Next.js static export ya da küçük SSR |
| Sistem reserve | ~4 GB | — | Kernel, log buffer, OS cache |

### İhlal durumu

Container limit'e dayanırsa:

- Memory limit'i aşarsa → OOM kill (Docker default `oom-kill-disable=false`).
- CPU limit'e dayanırsa → throttle (yavaşlar, ama düşmez).

Limit'e sürekli dayanan proje varsa **limit'i kaldırma**, kodu
profile et veya limit'i gerekçeli yükselt. `docker stats
--no-stream` izleme aracı.

---

## Karar 5 — Mail sunucusu Sprint 9+ (transactional için 3rd party)

İlk başta self-hosted mail sunucusu (Mailcow / Postfix / docker-mailserver)
**kurmuyoruz**.

### Sebepler

1. **IP reputation.** Yeni VPS'in IP'si herhangi bir mail
   reputation listesinde yok — ama spam blokları çoğunlukla
   "yeni IP" = "şüpheli" varsayar. Transactional mail (davet
   linki, password reset) ANINDA çalışmalı; reputation kazanmak
   haftalar alır.
2. **DKIM / SPF / DMARC kurulum yükü.** Self-hosted mail için bu
   üç DNS kaydını doğru kurmak + her domain için ayrı DKIM key
   üretip publish etmek + bounce handling yazmak — Sprint 8 için
   over-scope.
3. **Compliance riski.** PII içeren mail (kullanıcı email
   adresleri) self-host edildiğinde KVKK uyumu için ek dokümantasyon
   gerekir.

### Şimdilik: 3rd party transactional mail

[Resend](https://resend.com), [Postmark](https://postmarkapp.com),
veya [AWS SES](https://aws.amazon.com/ses/) — hepsi aylık 1-3K
mail için ücretsiz tier'da yetiyor. API key ile entegrasyon, IP
reputation onların sorunu.

### İleride self-host

Kendi mail sunucusu Sprint 9+'da Mailcow ile kurulur. Domain
`mail.imga.ai` (veya benzeri), ayrı sunucuda — ana app sunucusunun
IP reputation'ını mail'le karıştırmamak için.

---

## Yeni proje eklerken kontrol listesi

Bu listeyi her yeni proje için doldur:

- [ ] Kategori belirlendi (production SaaS / statik site)
- [ ] `/opt/<proje>/` klasörü oluşturuldu (deploy:deploy)
- [ ] `/etc/<proje>/` secrets klasörü oluşturuldu (root-only, mode 700)
- [ ] Compose dosyasında uygun network'ler tanımlı
  - Production SaaS: `<proje>-internal` + `caddy-public`
  - Statik site: `shared-db` + `caddy-public`
- [ ] **Resource limits** (memory + cpu) belirlendi ve compose'a yazıldı
- [ ] Caddy `conf.d/<proje>.conf` oluşturuldu (reverse_proxy
      direktifi ile)
- [ ] DNS kayıtları Cloudflare'de (subdomain → VPS IP, proxied)
- [ ] Caddy reload çağrıldı (`docker exec caddy caddy reload --config /etc/caddy/Caddyfile`)
- [ ] Stack ayağa kalktı, smoke test yapıldı (HTTP 200, TLS aktif)
- [ ] Backup stratejisine eklendi (DB dump cron + restic destination)
- [ ] Monitoring'e eklendi
  - Uptime Robot endpoint
  - Sentry projesi (sadece production SaaS için)

Bir madde eksikse o madde halledilmeden proje "production'a hazır"
sayılmaz.

---

## Değişiklik kararını ne tetikler?

Bu karar dokümanındaki maddeleri değiştirme **gereği** şu durumlarda
doğar:

| Karar | Yeniden değerlendirilir... |
|---|---|
| 1 (Postgres modeli) | İmga'nın yükü tek 24GB host'u zorlamaya başlarsa (multi-VPS gündeme gelir, ayrı DB host'u doğal). |
| 2 (Tek Caddy) | Tek Caddy SLO'yu karşılayamazsa veya WAF / DDoS koruması Cloudflare üstünde yetmezse. |
| 3 (Network izolasyonu) | Yeni bir proje shared Postgres'ten "kendi" Postgres'ine geçişi tetiklerse. |
| 4 (Resource limits) | Tipik dağılım tablosundaki sayılar gerçek kullanım profili çıkınca güncellenir. |
| 5 (Mail) | Aylık mail volume'u 10K+'a çıkarsa veya hassas PII içeren mail (örn. müşteri verisi export'u) self-host gerektirirse. |

Her değişiklikte bu doküman güncellenir, runbook (`server-setup.md`)
gerekiyorsa beraber. İkisi tek doğruluk kaynağı; birinde yazıp
diğerinde unutmak operasyonel borç birikimi.
