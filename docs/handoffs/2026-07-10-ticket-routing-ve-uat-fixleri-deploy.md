# Deploy Prompt — UAT Düzeltmeleri + Upload UX + Dashboard Filtreleri + Ticket Yönlendirme

**Tarih:** 2026-07-10 · **Yazar:** local-agent → server-agent · **Hedef commit:** `7749a34` (main HEAD)
**Kapsam:** HEM `api` HEM `web`. **YENİ MIGRATION: 0036.** Yeni arka plan cron'ları api-worker'da.
**Doğrulama (local):** backend test compose → **658 passed, 2 skipped** · frontend `tsc --noEmit` → **0 hata**.

## Ne geliyor

- **core `eba6136`:** İkincil Tetikleyici (tier2) artık güçlü pozitif cümleyi negatife çevirmiyor (UAT HATA-02 — yanlış oto-ticket kökü).
- **api `fbdd2fc`:** bozuk xlsx 400 + preview log KeyError fix + text_column otomatik çözümleme (HATA-01).
- **api `79f0532`:** executive overview'a `date_from/date_to/batch_job_id` filtreleri.
- **api `f3204f9`:** **Migration 0036** — global `belirsiz` kategorisi (HATA-03) + `ticket_routing_rules` + `email_outbox`. Kategori bazlı otomatik atama + e-posta bildirimi (açılış + SLA ihlali); arq cron'ları: `email_outbox_tick` (2 dk), `sla_breach_tick` (15 dk). SMTP env yoksa e-postalar kuyrukta bekler (kod tam çalışır).
- **web `ef26fec`:** yükleme sihirbazı revizeleri (alanlar kalktı, kopya uyarısı gizli, kalanlar gri, akan progress bar, kapalı select Türkçe etiket, 401 refresh, NPS mesajı, rozet renkleri, ForbiddenNotice bağlamı, davet linki, ham enum temizliği).
- **web `8a71316`:** ana sayfada batch + tarih (datepicker) filtresi — tüm kartlar filtreye göre; dev memnuniyet barı.
- **web `a74752c`:** Ayarlar → Ticket Yönlendirme sayfası (kural CRUD + outbox listesi).

## Deploy

```bash
cd /opt/imga && git pull origin main            # 7749a34
COMPOSE=/opt/imga/infra/imga/production/docker-compose.yml
sudo docker compose -f $COMPOSE build api web
sudo docker compose -f $COMPOSE up -d api api-worker web   # api-worker: yeni cron'lar
# *** MIGRATION ŞART (0035 -> 0036) ***
sudo docker compose -f $COMPOSE exec api alembic upgrade head
```

## SMTP kurulumu (e-posta bildirimlerini aktifleştirmek için — deploy'dan bağımsız yapılabilir)

Sunucuda mailcow kurulu (mail.vdd-tech.com.tr, @imga.ai). Yapılacaklar:
1. Mailcow admin'den bir gönderim hesabı oluştur (öneri: `no-reply@imga.ai` ya da `tickets@imga.ai`) + SMTP şifresi.
2. `/etc/imga/production/api.env`'e ekle (worker container'ı da aynı env dosyasını okuyorsa yeter; ayrıysa oraya da):
   ```
   IMGA_SMTP_HOST=mail.vdd-tech.com.tr
   IMGA_SMTP_PORT=587
   IMGA_SMTP_USERNAME=no-reply@imga.ai
   IMGA_SMTP_PASSWORD=<mailcow şifresi>
   IMGA_SMTP_FROM=no-reply@imga.ai
   IMGA_SMTP_FROM_NAME=İmga
   IMGA_APP_BASE_URL=https://app.imga.ai
   ```
3. `sudo docker compose -f $COMPOSE up -d api api-worker` (env yeniden okunsun).
4. SMTP tanımlanana kadar: e-postalar `email_outbox`'ta `pending` bekler; Ayarlar → Ticket Yönlendirme sayfasının altındaki listede görünür. Env eklenince cron 2 dk içinde gönderir.

## Smoke

1. **Migration:** `SELECT code, label_tr FROM categories WHERE tenant_id IS NULL AND code='belirsiz';` → 1 satır. `\dt` içinde `ticket_routing_rules`, `email_outbox`.
2. **Yükleme sihirbazı:** dosya seç → Adım 2'de Metin/Kaynak inputları YOK; kopyalı dosyada kopya uyarısı YOK (yalnız boş-hücre uyarısı, gri tonda); yükleme sırasında progress bar sürekli akıyor; tamamlanınca "Bu Yüklemenin Analizlerini Gör" → ana sayfa `?batch_job_id=...` filtreli açılıyor.
3. **Ana sayfa filtreleri (F5 smoke ZORUNLU):** yükleme seç → tüm kartlar daralıyor → F5 → seçim korunuyor; özel tarih aralığı gir → preset temizleniyor; "Filtreleri temizle" çalışıyor. Memnuniyet barı büyük, segment içi yüzdeler okunuyor.
4. **Ticket Yönlendirme:** Ayarlar → Ticket Yönlendirme → kural ekle (örn. kargo → kendi e-postan + kendine atama) → Manuel Analiz'de negatif kargo yorumu (Yarı otomatik modda) → ticket otomatik atanmış olmalı + sayfadaki outbox listesinde 'ticket_opened' kaydı (SMTP tanımlıysa 2 dk içinde gerçek e-posta).
5. **Belirsiz promote:** alakasız metin analiz et → "Yine de Ticket Aç" → artık ticket açılıyor (kategori "Belirsiz").
6. **tier2 fix:** "Kargom çok hızlı geldi, harika hizmet." → POZITIF, ticket YOK.
7. **Bozuk dosya:** uzantısı .xlsx yapılmış bir txt yükle → kırmızı anlaşılır hata (500 değil).

## Rollback

- Kod: 7 feature commit'ini revert + `build api web` + `up -d api api-worker web`.
- Migration 0036 additive; `alembic downgrade 0035` — DİKKAT: 'belirsiz' kategorisine bağlanmış ticket varsa downgrade'deki DELETE RESTRICT'e takılır (bilinçli koruma); önce o ticket'lar başka kategoriye taşınmalı.

## Raporla

Migration çıktısı + smoke sonuçları (özellikle 4. madde: atama + outbox + varsa gerçek e-posta teslimi). Kırmızı → tam çıktı, local-agent düzeltir.
