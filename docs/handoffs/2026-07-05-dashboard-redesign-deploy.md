# Deploy Prompt — Ana Sayfa Yeniden Tasarımı + Yetki Bazlı Ekranlar · api + web

**Tarih:** 2026-07-05 · **Yazar:** local-agent → server-agent · **Hedef commit:** `0d5de4a` (main HEAD)
**Kapsam:** HEM `api` HEM `web` image'ı. **MIGRATION YOK** (yalnız additive response alanı + guard değişikliği).

## Ne geliyor

- **api `b443b25`** — executive overview'a `last_data_at` (son veri girişi; 24 saat kuralının veri kaynağı). Additive, kırıcı değil.
- **api `83733ee`** — viewer salt-okuma sıkılaştırması: `POST /tenants/me/analyze` ve `PATCH /tenants/me/trend-alerts/{id}` viewer'a artık **403** (tenant_admin + analyst sürüyor). Bilinçli dokunulmayanlar commit mesajında.
- **web `d349ebd`** — C-level ana sayfa yeniden tasarımı:
  - Trend rozetinde ok ikonu yok; memnuniyet skoru + NPS'e "nasıl hesaplanır?" tooltip'leri.
  - Hero altında dönem filtresi: **Son 3 Ay / Son 6 Ay / Tüm Zamanlar** (`?window=3m|6m`, URL-state).
  - Yeni chart'lar: **NPS Dağılımı** (Destekçi/Pasif/Kötüleyen + skor + kapsam) ve **Kategori Bazlı Duygu Dağılımı** (yatay yığılmış %100 barlar; dilim → /reviews deep-link).
  - **24 saat kuralı:** son 24 saatte veri yüklenmemişse (veya hiç yoksa) yükleme alanı sayfanın en üstünde.
  - Hero'da gradyanlı **SWOT Analizi** butonu → `/strategy?tab=swot`.
- **web `0d5de4a`** — yetki bazlı ekranlar: `RequireRole` sayfa korumaları (7 settings alt sayfası + 4 admin/webhook sayfası → admin; 3 analiz/yükleme sayfası → write), sidebar rol filtresi (viewer Veri Yükle + Ayarlar'ı görmez; **YÖNETİM bölümü artık tenant_admin'e de görünür**, Kurumlar super-admin'de kalır), FAB yükleme kısayolu yalnız yazma yetkili rollere.

**Doğrulama (local):** backend `:5433` → **647 passed, 2 skipped** (2 yeni viewer-403 testi dahil); frontend `tsc --noEmit` → **0 hata**.

## Deploy (api + web birlikte; migration YOK)

```bash
cd /opt/imga && git pull origin main            # 0d5de4a
COMPOSE=/opt/imga/infra/imga/production/docker-compose.yml
sudo docker compose -f $COMPOSE build api web
sudo docker compose -f $COMPOSE up -d api web
# alembic GEREKMEZ — bu deploy'da migration yok (HEAD hâlâ 0035).
```

## Doğrulama (deploy sonrası smoke)

1. **Ana sayfa:** hero geliyor, trend rozetinde ok ikonu YOK, memnuniyet yüzdesinin yanındaki bilgi ikonuna hover → hesap açıklaması.
2. **Dönem filtresi (F5 smoke — ZORUNLU, url-state-patterns.md):** "Son 3 Ay" seç → URL `?window=3m` → **F5** → seçim korunur → back button önceki seçime döner → URL'yi yeni sekmeye yapıştır → aynı görünüm.
3. **Chart'lar:** NPS Dağılımı kartı sayı+oranlarla dolu; Kategori Bazlı Duygu Dağılımı barları çiziliyor; bir dilime tıkla → /reviews doğru kategori+duygu filtresiyle açılıyor.
4. **24 saat kuralı:** son 24 saatte verisi olmayan kurumda yükleme alanı sayfanın en üstünde; taze veri yükleyince sonraki yüklemede normale döner.
5. **SWOT butonu:** hero'daki mor gradyanlı buton `/strategy?tab=swot` açıyor.
6. **Yetki:** viewer hesabıyla → sidebar'da Veri Yükle/Ayarlar yok; `/analyze/upload` URL'si ForbiddenNotice; `POST /tenants/me/analyze` → 403. tenant_admin hesabıyla → sidebar'da YÖNETİM bölümü (LLM Denetimi vb.) görünüyor, Kurumlar yok.
7. `GET /tenants/me/executive/overview` yanıtında `last_data_at` dolu.

## Rollback

Migration yok — düz revert yeterli:
`git revert 0d5de4a d349ebd 83733ee b443b25` → `build api web` → `up -d api web`.
Yalnız web sorunluysa: iki web commit'ini revert edip sadece `web` rebuild.

## Notlar

- Viewer kullanan gerçek kurum varsa 403 değişikliği duyurulmalı (manuel analiz + trend-alert kapatma artık analist işi).
- Dokümante minör kalanlar (i18n handoff'undaki liste) hâlâ geçerli; bu deploy'a dahil değil.

## Raporla

Smoke sonuçları (özellikle F5 dönem-filtresi testi + viewer 403'leri). Kırmızı olursa tam çıktı → local-agent düzeltir.
