# İmga.AI — Kullanıcı Kılavuzu

Bu doküman İmga.AI'yi hiç kullanmamış birinin her sayfayı, her butonu, her durumu anlaması için hazırlandı. Geliştirici dokümanı değil — kullanıcı dokümanı. Resim yok, sadece anlatı + tablolar + akışlar.

**Hedef kitle:** Tenant yöneticileri, müşteri hizmetleri analistleri, izleyici (raporlama) kullanıcıları, ve İmga.AI'yi kuran süper-yöneticiler.

**Üretim adresleri:** [app.imga.ai](https://app.imga.ai) (canlı), [staging.imga.ai](https://staging.imga.ai) (test).

---

## İçindekiler

- [Bölüm 1 — Mental Model](#bölüm-1--mental-model)
- [Bölüm 2 — Sayfa Sayfa Rehber](#bölüm-2--sayfa-sayfa-rehber)
- [Bölüm 3 — Rol Matrisleri](#bölüm-3--rol-matrisleri)
- [Bölüm 4 — Akış Senaryoları](#bölüm-4--akış-senaryoları)
- [Bölüm 5 — Üretim Smoke Test](#bölüm-5--üretim-smoke-test)

---

# Bölüm 1 — Mental Model

İmga.AI 5 temel kavramın etrafında kuruludur: **tenant**, **kullanıcı (rol)**, **ticket**, **review**, **comment**. Bunları anlarsan ürünün geri kalanı sürpriz olmaz.

## Tenant — şirket / proje sınırı

Tenant, **müşteri** demektir. Bir SaaS müşterisi (örn. "Acme Inc."), tüm verisi (kullanıcılar, ticket'lar, kategoriler, ayarlar) o tenant'a aittir. Bir kullanıcı birden fazla tenant'ta üye olabilir; tenant'lar birbirinin verisini göremez (Postgres seviyesinde RLS ile zorlanır).

Pratik anlamı:
- Tenant A'nın yöneticisi Tenant B'nin ticket'larını **göremez**.
- Bir kullanıcı Acme + Beta'da üyeyse, sidebar'daki "tenant switcher" ile hangi tenant bağlamında çalıştığını seçer.
- Süper-yönetici (`is_super_admin`) hesabı tenant-üstü; tüm tenant'ları yönetebilir.

## Kullanıcı + 4 rol

Sistemde 4 rol var:

| Rol | Açıklama | Tipik kullanım |
|---|---|---|
| **Süper-yönetici** | `is_super_admin=true`. Tüm tenant'ları yönetebilir. Tenant'tan bağımsız. | İmga.AI ekibi, kurulum personeli |
| **Yönetici** (`tenant_admin`) | Bir tenant içinde tam yetki. Davet gönderme, ayar değiştirme, her ticket'ı işleme. | Müşteri firmasının içerideki ürün lideri |
| **Analist** (`analyst`) | Ticket üzerinde çalışır: claim, çöz, yorum yaz, müşteriye yanıt. Ayar değiştiremez. | Müşteri hizmetleri ekibi |
| **İzleyici** (`viewer`) | Sadece okuyabilir + iç not yazabilir. Ticket state'i değiştiremez, müşteriye yanıt yazamaz. | Üst yönetim, raporlama, paydaş |

Bir kullanıcı **farklı tenant'larda farklı rollere** sahip olabilir. Acme'de yönetici, Beta'da izleyici olabilir. Aktif rol, JWT'deki `active_tenant_id` ile belirlenir; tenant switch yapılınca rol de değişir.

## Ticket — şikayet kaydı

Ticket, **bir müşteri şikayetinin** (genelde negatif yorumun) ürün içindeki temsilidir. Her ticket'ın bir state'i (durumu), önceliği, kategorisi ve atanmış bir analisti olabilir.

### State machine — 6 durum

```
                    ┌──────────────────┐
                    │       OPEN       │ Açık (yeni gelmiş, kimse el atmadı)
                    └────────┬─────────┘
                             │ üstlen
                             ▼
                    ┌──────────────────┐
              ┌────►│   IN_PROGRESS    │ İlerlemekte (analist çalışıyor)
              │     └────────┬─────────┘
       müşteri│              │ çöz
       cevabı │              │
              │              ▼
       ┌──────┴──────────┐   ┌─────────────┐
       │PENDING_CUSTOMER │   │   RESOLVED  │ Çözüldü (N gün sonra otomatik kapanır)
       │ (müşteri        │   └────┬────────┘
       │  bekleniyor)    │        │ kapat
       └─────────────────┘        ▼
                                  ┌──────────────────┐
                                  │      CLOSED      │ Kapatıldı (terminal)
                                  └──────────────────┘

       İptal hattı (her aktif state'ten):
       OPEN → CANCELLED
       IN_PROGRESS → CANCELLED (sadece yönetici)

       Geri açma (sınırlı zaman penceresi içinde):
       CLOSED → OPEN (yönetici)
       CANCELLED → OPEN (yönetici)
       RESOLVED → IN_PROGRESS (regresyon)
```

**Türkçe durum etiketleri** (UI'da göreceğin):
- `open` → **Açık**
- `in_progress` → **İlerlemekte**
- `pending_customer` → **Müşteri Bekleniyor**
- `resolved` → **Çözüldü**
- `closed` → **Kapatıldı**
- `cancelled` → **İptal**

**Önemli kurallar:**
- **CANCELLED için iptal sebebi zorunlu**: false_positive, duplicate, spam, off_topic, other.
- **Kapatılmış ticket'ı geri açmak zaman pencereli**: tenant ayarındaki `ticket_reopen_window_days` (varsayılan 30 gün) dolduktan sonra reopen edilemez; bunun yerine "linked ticket" açılır (Sprint 8 sonrası gelecek).
- **Çözüldü → tekrar IN_PROGRESS (regresyon)** da pencereli: `resolved_regression_window_days` (varsayılan 7 gün).

### Öncelik (priority)
- `low` → **Düşük**
- `normal` → **Normal** (varsayılan)
- `high` → **Yüksek**
- `urgent` → **Acil**

## Review — analiz kaydı

Review, **bir metnin analiz edildiği anın kaydı**. Ticket'tan farkı: ticket bir iş kaydı, review ise bir gözlem kaydı.

Her `/tenants/me/analyze` çağrısı bir review row'u yazar. Review:
- Metnin kendisi
- Sentiment skoru ve etiketi (NEGATİF / NÖTR / POZİTİF)
- Sınıflandırılmış kategori + güven skoru
- Otomasyon modu **anlık fotoğrafı** (review yazıldığı anın modu)
- "Bridge kararı" — bu review'un bir ticket'a dönüşüp dönüşmediği (5 branch)
- İlişkili ticket_id (varsa)

Her review eninde sonunda **bir karar** üretir, bunu §[Auto-ticket bridge](#auto-ticket-bridge) bölümünde anlatıyoruz.

## Comment — yorum / iç not / müşteri yanıtı

Bir ticket'a yapılan yorum. **İki tip:**

| Tip | Görünür | Tipik kullanım |
|---|---|---|
| **İç not** (`internal_note`) | Sadece tenant ekibi | "Müşteriyi aradım, telefon açmadı" |
| **Müşteri yanıtı** (`customer_reply`) | İlerde müşteriye gönderilecek metin | "Sayın müşterimiz, talebiniz alınmıştır..." |

**Önemli:**
- **VIEWER** sadece iç not yazabilir; müşteri yanıtı seçeneği UI'da görünmez.
- **CLOSED veya CANCELLED** ticket'a müşteri yanıtı yazılamaz (iç not yazılabilir — post-mortem için).
- **Silme yok, arşivleme var.** Bir yorum arşivlenince üzeri çizili görünür ama timeline'da kalır (tarihçe bozulamaz).
- Yazar kendi yorumunu arşivleyebilir; tenant yöneticisi her yorumu arşivleyebilir.

## Auto-ticket bridge — 5 karar

`/tenants/me/analyze` çağrılınca arka uç şu karar ağacını çalıştırır (sırayla):

```
1. primary_category == "belirsiz"?  → SKIPPED_BELİRSİZ
2. otomasyon modu == manuel?         → SKIPPED_MODE
3. eşik tutmadı mı?                  → SKIPPED_THRESHOLD
   (semi_auto: confidence ≤ 0.7 VEYA sentiment ≥ -0.5)
   (full_auto: sentiment ≥ 0)
4. son 24 saatte aynı metin ticket'a dönüşmüş mü? → SKIPPED_DEDUP
5. yukarıdakilerin hiçbiri yoksa     → CREATE
```

**5 karar dalı, kullanıcının ne göreceği:**

| Karar | Görsel | Türkçe başlık | Anlamı |
|---|---|---|---|
| `create` | ✅ yeşil | "Otomatik bilet açıldı" | Yeni ticket açıldı, link verilir |
| `skipped_dedup` | ℹ️ mavi | "Aynı metin son 24 saatte zaten analiz edildi" | Mevcut ticket'a yönlendirme linki verilir |
| `skipped_mode` | ℹ️ mavi | "Otomasyon modu manuel — bilet açılmadı" | Settings'ten mod değiştirmen gerekir |
| `skipped_threshold` | ℹ️ mavi | "Eşik altı — bilet açılmadı" | Sentiment / confidence düşük; manuel inceleme önerilir |
| `skipped_belirsiz` | ℹ️ mavi | "Kategori belirsiz — manuel sınıflandırma gerekli" | Sınıflandırıcı emin olamadı |

## Automation modes — 3 seviye

| Mod | Davranış | Kullanım |
|---|---|---|
| **Manuel** | `/analyze` sadece sentiment + kategori döner. Hiç bilet açılmaz. | Önce algoritmayı tanımak isteyen ekipler |
| **Yarı otomatik** (semi_auto) | Yüksek güvenli + yüksek negatif yorumlar otomatik bilet açar (confidence > 0.7 VE sentiment < -0.5). Diğerleri SKIPPED_THRESHOLD. | Tipik üretim ayarı |
| **Tam otomatik** (full_auto) | Sentiment < 0 olan her yorum bilet açar. Pozitif veya nötr olanlar atlanır. | Yüksek volüm, hızlı triage isteyen ekipler |

Mod sadece tenant yöneticisi tarafından `/settings`'ten değiştirilir.

---

# Bölüm 2 — Sayfa Sayfa Rehber

Her sayfa için: URL, kim erişebilir, ne içerir, ne yapabilirsin.

## /login — Giriş

**URL:** `/login` (public, auth gerekmez).
**Kim erişebilir:** Herkes.

**Sayfada ne var:**
- "imga.ai" başlığı + "Hesabınıza giriş yapın" alt başlığı
- E-posta input
- Şifre input (gözle/gizle butonu)
- "Giriş Yap" submit butonu

**Hata durumları:**
- Yanlış parola → "Giriş başarısız" toast'u, sayfada kal.
- Hesap deaktif → aynı mesaj (saldırgana hangi e-postaların aktif olduğunu sızdırmamak için).

**Sonraki adım:** Başarılı giriş → `/` (dashboard) yönlendirilir.

---

## / — Panel (Dashboard)

**URL:** `/`
**Kim erişebilir:** Tüm tenant üyeleri (yönetici / analist / izleyici).

**Sayfada ne var:**

1. **Karşılama satırı** — "Merhaba, {ad}", altında aktif tenant adı (örn. "Acme Inc.").

2. **4 metric kart** (üstte yan yana):
   - **Açık ticket** — Açık + İlerlemekte + Müşteri Bekleniyor toplamı.
   - **Bugün açılan** — Gün içinde 00:00'dan beri açılan ticket sayısı.
   - **Yüksek öncelik** — Aktif (kapatılmamış) yüksek/acil öncelikli ticket sayısı.
   - **Son 7 günde çözülen** — RESOLVED/CLOSED durumuna geçen ticket sayısı (son 7 gün).

3. **Kategori dağılımı grafiği** (sol alt) — Bar chart, ilk 5 kategori, ticket sayısına göre azalan.

4. **Son ticket'lar tablosu** (sağ alt) — En son güncellenen 5 ticket (başlık + kategori + durum badge + son güncelleme).
   - "Tümünü gör →" linkiyle `/tickets` sayfasına gidilir.

**Tipik kullanım:** Sabah açıp queue'nun durumunu hızlıca görmek. Açık + Yüksek öncelik kartlarına bakıp önceliği belirlemek. Kategori grafiğinden hangi alanda yoğunluk var anlamak.

---

## /tickets — Ticket listesi

**URL:** `/tickets` (filtre parametreleri URL'de: `?state=open,in_progress&priority=high...`)
**Kim erişebilir:** Tüm tenant üyeleri.

**Sayfada ne var:**

1. **Başlık + sayaç** — "Ticket'lar — X gösteriliyor / toplam Y".

2. **Filtre çubuğu** — 4 dropdown:
   - **Durum** — Açık / İlerlemekte / Müşteri Bekleniyor / Çözüldü / Kapatıldı / İptal (çoklu seçim, virgüllü URL)
   - **Öncelik** — Acil / Yüksek / Normal / Düşük (çoklu seçim)
   - **Kategori** — tenant kategorileri (çoklu seçim)
   - **Atanan** — "Bana atananlar" / "Atanmamış" / "Herkes"
   - "Filtreleri temizle" butonu (en az bir filtre aktifse görünür)

3. **Ticket tablosu** — Sütunlar:
   - Başlık (linkli, /tickets/[id]'ye gider)
   - Kategori
   - Durum badge
   - Öncelik badge
   - Atanan
   - Son güncelleme

4. **"Daha fazla göster" butonu** — Sayfanın altında, son sayfaya gelmediğinden gelir. Her tıkta sonraki 100 ticket eklenir.

**URL paylaşılabilir:** Filtreleri uygulayıp URL'yi kopyalarsan, başkası aynı filtreli görünümü açar.

**Tipik kullanım:**
- "Bana atananları göreyim" → Atanan: Bana atananlar.
- "Yüksek öncelikli açıkları göreyim" → Öncelik: Acil + Yüksek, Durum: Açık + İlerlemekte.

---

## /tickets/[id] — Ticket detayı

**URL:** `/tickets/{id}` (örn. /tickets/9c45a2f1-...)
**Kim erişebilir:** Tüm tenant üyeleri.

**Sayfa düzeni** — Ana kolon (sol, geniş) + yan panel (sağ, 320px).

### Ana kolon (sol)

1. **Geri linki** ("← Ticket listesi") + sayfa başlığı (ticket adı).
2. **Özet** (varsa, italik gri).
3. **Action Bar** — Role + state'e göre değişen butonlar (aşağıda detaylı).
4. **Geçmiş (Timeline)** — Kronolojik olay listesi; 3 tip event:
   - **Durum geçişi** — "Açıldı" / "İlerlemekte → Çözüldü" gibi
   - **Yorum** — yazar avatarı + tip badge (İç not / Müşteri yanıtı) + içerik
   - **Atama değişikliği** — "Alice → Bob" (Sprint 7.7.2 sonrası)
   - Arşivlenmiş yorumlar üzeri çizili + "Arşivlenmiş" badge ile görünür.
5. **Yorumlar** — Mevcut yorumlar listesi + yorum yazma formu.

### Yan panel (sağ)

- **Durum** badge
- **Öncelik** badge
- **Kategori**
- **Atanan** — dropdown (combobox), kullanıcı seçilebilir
- **İptal sebebi** (sadece state=cancelled için görünür)
- **Açılış / Çözüm / Kapanış / Müşteri yanıtı** zaman damgaları (varsa)

### Action Bar — state'e göre butonlar

State'e göre hangi action'ların görüneceği aşağıdadır. **Rol uygunsuzsa buton hiç görünmez.**

| Mevcut state | Görünen action butonları (sıralı) |
|---|---|
| OPEN | Üstlen (analist/yönetici) · İptal et (analist/yönetici) |
| IN_PROGRESS | Çöz · Müşteri Bekle · Bırak (kendi ticket'ın için) · İptal et (yalnız yönetici) |
| PENDING_CUSTOMER | Devam et · Çöz |
| RESOLVED | Kapat · Yeniden Aç (regresyon — 7 gün içinde) |
| CLOSED | Yeniden Aç (yalnız yönetici, 30 gün içinde) |
| CANCELLED | İptali Geri Al (yalnız yönetici, 30 gün içinde) |

**İptal et** butonu seçilince modal açılır:
- Sebep dropdown'ı (false_positive / duplicate / spam / off_topic / other)
- "İptal et" butonu (sebep seçilmeden gönderilemez)

**Yeniden Aç** zaman penceresi dolmuşsa 409 hatası alınır; ekran "linked ticket aç" hint'i gösterir (Sprint 8 sonrası gelecek).

### Atama dropdown — kullanıcı seçimi

Sağ paneldeki "Atanan" satırı bir combobox'tır:
- "Atanmamış" özel option (en üstte) — atamayı temizler
- Tenant üyeleri (full_name + email + rol badge ile)
- "Sen" badge'i (giriş yapmış kullanıcının kendi satırında)
- Ara kutusuna isim/email yazılabilir
- **Yetki:**
  - Yönetici → herkesi atayabilir
  - Analist → sadece kendisini atayabilir/bırakabilir
  - İzleyici → dropdown disabled

### Yorum yazma formu

- **Textarea** (8000 karakter limit)
- **Tip seçici** (RadioGroup):
  - "İç not" (varsayılan)
  - "Müşteri yanıtı" — VIEWER görmez; CLOSED/CANCELLED'da disabled (tooltip: "Kapalı ticket'a yanıt yazılamaz")
- "Gönder" butonu — body boş olduğunda disabled

### Yorum listesi her satır

- Avatar (ad initial'ı)
- Yazar adı + tip badge + zaman ("2 saat önce")
- Yorum metni
- "Arşivle" butonu — yazar veya yöneticiye görünür; arşivlenmiş ise gizli
- Arşivlenmiş yorum: opaque %60, üzeri çizili, "Arşivlenmiş" badge

**"Arşivle"** butonuna tıklayınca **AlertDialog** açılır: "Bu yorum arşivlenecek ve geri alınamaz." Onaylayınca soft-delete uygulanır.

---

## /settings — Ayarlar

**URL:** `/settings`
**Kim erişebilir:** **Sadece tenant yöneticisi.** Analist / izleyici "Yetkiniz yok" sayfası görür.

**Sayfada ne var:**

1. **Otomasyon modu formu** — RadioGroup:
   - Manuel
   - Yarı otomatik
   - Tam otomatik
   - "Kaydet" butonu (seçim değişti mi takip eder)

2. **Kategori listesi (global)** — 8 sistem kategorisi (kargo, iade, faturalama, ürün kalitesi, müşteri hizmetleri, vb.). Her birinin yanında **enable/disable switch'i** var. Kapalı kategori `/analyze` sınıflandırma havuzundan dışlanır.

3. **Özel kategoriler bölümü:**
   - Mevcut özel kategoriler listesi (kod + label_tr + label_en + arşivli badge)
   - "Yeni özel kategori" butonu → modal:
     - Kod (regex: küçük harf, rakam, alt çizgi; örn. "vip_complaint")
     - Türkçe etiket
     - İngilizce etiket (opsiyonel)
     - Açıklama (opsiyonel)
   - Her özel kategori sıralı: [Düzenle] / [Arşivle] butonları
   - Arşivlenmiş özel kategoriler grileşir, üst kısımda "Arşivli" başlığı altında listelenir

**Önemli kural:** Özel kategori kodu, global kategori kodlarıyla **aynı olamaz** (kargo, iade, vb. sistem kodlarıdır, korumalı).

---

## /analyze — Manuel analiz

**URL:** `/analyze`
**Kim erişebilir:** Tüm tenant üyeleri.

**Sayfada ne var:**

1. **Başlık** — "Yorum Analiz Et"
2. **Açıklama** — "Müşteri yorumunu yapıştır, sentiment + kategori analizi al. Tenant otomasyon modu uygunsa ticket otomatik açılır."
3. **Form:**
   - "Yorum metni" textarea (autosize, 1-10000 karakter)
   - Karakter sayacı altta sağda (örn. "120 / 10000")
   - "Analiz Et" butonu — boş textarea iken disabled
   - Submit anında textarea + buton disabled olur, butonda "Analiz ediliyor..." spinner görünür
4. **Sonuç kartı** (analiz başarılı olunca görünür):
   - **"Analiz Sonucu"** başlığı
   - **Sentiment** badge (NEGATİF kırmızı / NÖTR gri / POZİTİF yeşil) + skor (-1.0 .. +1.0)
   - **Kategori** badge + güven %
   - **SLA tespiti** (varsa, örn. "SLA Aşımı (5 Gün > 3)")
   - **Özet** (varsa)
5. **Karar kartı** (5 dal — bkz. Mental Model):
   - `create` → Yeşil success card + **"Yeni bilete git →"** butonu
   - `skipped_dedup` → Mavi info card + **"Mevcut bilete git →"** butonu
   - `skipped_mode` → Mavi info card, butonsuz; öneri: "Settings'ten otomasyon modunu değiştir"
   - `skipped_threshold` → Mavi info card; metni manuel inceleyebilirsin
   - `skipped_belirsiz` → Mavi info card; manuel sınıflandırma gerekli

**Tipik kullanım:**
- Ekipte gelen bir yorum üzerinde "bu ticketlık mı?" diye hızlı kontrol.
- Otomasyon eşiklerinin nasıl çalıştığını görmek için test yorumları geçmek.

---

## /invite/[token] — Davet kabul

**URL:** `/invite/{token}` (public, auth gerekmez).
**Kim erişebilir:** Herkes (token kendi yetkisi).

Davet linkiyle gelen kullanıcı 3 farklı durumdan biriyle karşılaşır:

### Durum 1 — Yükleniyor

Skelet (4 satır gri çizgi). Backend `/invitations/{token}/preview` çağrısının sonucu beklenirken görünür.

### Durum 2 — Geçersiz / süresi dolmuş token

- ⚠️ ShieldAlert ikonu (kırmızı)
- "Bu davet geçersiz veya süresi dolmuş" başlığı
- "Lütfen tenant yöneticinizle iletişime geçip yeni bir davet isteyin." metni
- "Giriş ekranına dön" butonu → /login

### Durum 3 — Geçerli davet

**Üst blok (PreviewHeader):**
- 🏢 Building2 ikonu + tenant adı (örn. "Acme Inc.")
- Rol badge (Yönetici / Analist / İzleyici)
- ✉️ "Davet edilen: alice@example.com"
- 📅 "Geçerlilik: 7 gün" / "Geçerlilik: bitti" (expires_at'a göre)

**Alt form** — backend'in `email_exists` field'ına göre:

#### `email_exists=false` — Yeni hesap formu (NewUserAcceptForm)

- Tam Adınız input (1-255 char)
- Şifre input (≥ 8 char)
- Şifre Tekrar input
- "Daveti Kabul Et" butonu

Submit → backend `/invitations/{token}/accept` çağrısı → token döner → frontend localStorage'a yazar → `/`'a yönlendirir.

#### `email_exists=true` — Mevcut hesap formu (ExistingUserAcceptForm)

- E-posta (sabit, davet edilen email)
- Şifre input — bu hesabın MEVCUT şifresi (re-auth)
- "Hesabımla Daveti Kabul Et" butonu

İki alt-durum:
- **Kullanıcı zaten giriş yapmışsa** ve davet edilen email farklıysa: Amber uyarı kartı görünür ("Şu an {x@x.com} olarak giriş yapmışsınız. Davet {y@y.com}'a geldi.")
- **Yanlış parola** → "Geçersiz parola" hata toast'u
- **Email mismatch** (login email ≠ invited email) → 403 + uyarı mesajı

Submit → `/invitations/{token}/accept-existing` → yeni token pair → switchTenant → `/`.

---

## /admin/tenants — Süper-yönetici tenant yönetimi

**URL:** `/admin/tenants`
**Kim erişebilir:** **Sadece süper-yönetici** (`is_super_admin=true`). Diğerleri "Yetkiniz yok".

**Sayfada ne var:**

1. **Başlık** — "Tenant'lar" (Building2 ikonu eşliğinde)
2. **"Yeni Tenant" butonu** sağ üstte
3. **Tenant tablosu:**
   - İsim (yazılı)
   - Slug (font-mono, küçük gri — URL'de görünen)
   - Plan badge (Deneme / Başlangıç / Kurumsal / Enterprise)
   - Otomasyon badge (Manuel / Yarı otomatik / Tam otomatik)
   - Oluşturulma tarihi
   - Aksiyon butonları: [Düzenle] / [Davet] / [Sil]
4. **Empty state** (henüz tenant yoksa) — Building2 ikonu + "Henüz tenant yok" + büyük "Yeni Tenant" CTA

### Modal'lar

#### "Yeni Tenant" modal

- İsim input
- Slug input (isim girince otomatik üretilir, manuel düzenlenebilir; geçersiz karakter varsa kırmızı uyarı: "Sadece küçük harf, rakam, tire")
- Plan dropdown
- Otomasyon dropdown
- "İlk admin daveti gönder" toggle:
  - Açıkken: e-posta + tam ad input'ları görünür
- "Vazgeç" / "Oluştur" butonları

Başarılıysa 2 senaryo:
- İlk admin verilmemiş → toast "Tenant oluşturuldu", modal kapanır
- İlk admin verilmiş → modal **success view'a swap eder**:
  - ✓ "Tenant oluşturuldu" başlığı
  - "İlk admin için davet linki hazır. Bu link sadece **tek sefer** gösterilir — modal'ı kapatmadan paylaş."
  - Davet linki (read-only kod kutusu) + "Kopyala" butonu
  - "Tamam, paylaştım" butonu

⚠️ **Davet token'ı kapatıldıktan sonra geri gösterilemez.** Mutlaka kopyala.

#### "Düzenle" modal

- İsim (mutable)
- Slug (read-only, "Değişmez" hint'iyle)
- Plan dropdown (mutable)
- Otomasyon dropdown (mutable)
- "Kaydet" — değişiklik yoksa modal kapanır

#### "Davet" modal

- E-posta input
- Rol dropdown (Yönetici / Analist / İzleyici)
- "Davet oluştur" → backend success → modal **InviteLinkBlock**'a swap eder:
  - "Davet hazır" başlığı
  - Davet linki + Kopyala butonu
  - "Tamam"

#### "Sil" modal — AlertDialog (destructive)

- "{Tenant Adı}'ı sil" başlığı
- "Bu tenant'ı silmek üzeresin. Tüm verisi soft-delete edilir; gerekirse veritabanı seviyesinde geri yüklenebilir."
- "Vazgeç" / "Sil" butonları (Sil kırmızı)

Soft-delete: `deleted_at` field'ı set edilir, ticket'lar/users **kalır** (cascade yok). Kullanıcılar artık o tenant'ı switcher'da göremez.

---

## AppShell — Kenar çubuğu, tenant switcher, kullanıcı menüsü

Tüm authenticated sayfalarda ortak.

### Sidebar (kenar çubuğu)

**Sol kenarda dikey nav.** Desktop'ta 240px genişlik (toggle ile 60px daralabilir), mobile'da Sheet (overlay).

**Üst kısım** — Tenant Switcher.
**Orta** — Nav linkleri:
- Panel (`/`)
- Ticket'lar (`/tickets`)
- Analiz (`/analyze`)
- Ayarlar (`/settings`)

**YÖNETİM bölümü** (sadece süper-yönetici görür — non-admin'lerde DOM'da bile yok):
- Tenant'lar (`/admin/tenants`)

**Alt kısım** — User Menu.

### Tenant Switcher

Sidebar'ın en üstünde. Mevcut aktif tenant adı + ChevronDown ikonu. Tıklayınca dropdown açılır:

- Aktif tenant satırında ✓ checkmark
- Diğer tenant'lar listesi (her birinde rol etiketi alta küçük gri)
- ">1 tenant varsa" arama kutusu en üstte
- "+ Yeni davet kabul et" satırı en altta — modal açar:
  - "Davet token'ınızı girin" input
  - Token girip "Kabul Et" → token tabanlı flow başlar (zaten giriş yapmış kullanıcı için doğrudan accept-existing path)

Tenant değişimi:
- Frontend `/auth/switch-tenant` çağırır
- Yeni JWT döner (yeni `active_tenant_id` + role ile)
- Tüm cache invalidate olur (TanStack Query)
- Sayfa yenilenir, yeni tenant'ın verisini gösterir

### User Menu

Sidebar'ın en altında. Avatar (2 harfli initials, full_name'den çıkar) + dropdown:
- Üstte: ad + e-posta
- "Çıkış yap" → logout flow → `/login`

---

# Bölüm 3 — Rol Matrisleri

## Sayfaya erişim

| Sayfa | Süper-yönetici | Yönetici | Analist | İzleyici | Public (auth yok) |
|---|---|---|---|---|---|
| `/login` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `/` (panel) | ✓ | ✓ | ✓ | ✓ | ✗ |
| `/tickets` | ✓ | ✓ | ✓ | ✓ | ✗ |
| `/tickets/[id]` | ✓ | ✓ | ✓ | ✓ | ✗ |
| `/settings` | ✓ | ✓ | ✗ | ✗ | ✗ |
| `/analyze` | ✓ | ✓ | ✓ | ✓ | ✗ |
| `/invite/[token]` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `/admin/tenants` | ✓ | ✗ | ✗ | ✗ | ✗ |

## Ticket transitions (state machine ROLE_MATRIX)

| Geçiş | Yönetici | Analist | İzleyici | Sistem |
|---|---|---|---|---|
| OPEN → IN_PROGRESS (üstlen) | ✓ | ✓ | ✗ | ✗ |
| OPEN → CANCELLED (iptal) | ✓ | ✓ | ✗ | ✗ |
| IN_PROGRESS → OPEN (bırak) | ✓* | ✓** | ✗ | ✗ |
| IN_PROGRESS → PENDING_CUSTOMER | ✓ | ✓ | ✗ | ✗ |
| IN_PROGRESS → RESOLVED | ✓ | ✓ | ✗ | ✗ |
| IN_PROGRESS → CANCELLED | ✓ | ✗ | ✗ | ✗ |
| PENDING_CUSTOMER → IN_PROGRESS | ✓ | ✓ | ✗ | ✗ |
| PENDING_CUSTOMER → RESOLVED | ✓ | ✓ | ✗ | ✗ |
| PENDING_CUSTOMER → CLOSED | ✗ | ✗ | ✗ | ✓ (auto-close) |
| RESOLVED → CLOSED | ✓ | ✓ | ✗ | ✗ |
| RESOLVED → IN_PROGRESS (regresyon, 7d) | ✓ | ✓ | ✗ | ✗ |
| CLOSED → OPEN (reopen, 30d) | ✓ | ✗ | ✗ | ✗ |
| CANCELLED → OPEN (uncancel, 30d) | ✓ | ✗ | ✗ | ✗ |

\* Yönetici her zaman bırakabilir (kendi ticket'ı veya başkasının).
\** Analist sadece **kendi** ticket'ını bırakabilir; başkasının atamasını kaldıramaz.

**Süper-yönetici** her zaman tüm transitionları yapabilir (override).

## Comments

| Eylem | Yönetici | Analist | İzleyici |
|---|---|---|---|
| İç not yaz | ✓ | ✓ | ✓ |
| Müşteri yanıtı yaz (Açık/İlerlemekte/Müşteri Bekleniyor/Çözüldü'de) | ✓ | ✓ | ✗ |
| Müşteri yanıtı yaz (CLOSED/CANCELLED'da) | ✗ | ✗ | ✗ |
| Kendi yorumunu arşivle | ✓ | ✓ | ✓ |
| Başkasının yorumunu arşivle | ✓ | ✗ | ✗ |

## Settings + Admin

| Eylem | Süper-yönetici | Yönetici | Diğerleri |
|---|---|---|---|
| Otomasyon modu değiştir | ✓ | ✓ | ✗ |
| Global kategori toggle | ✓ | ✓ | ✗ |
| Özel kategori CRUD | ✓ | ✓ | ✗ |
| Tenant CRUD | ✓ | ✗ | ✗ |
| Davet gönderme (kendi tenant'ında) | ✓ | ✓ | ✗ |
| Davet gönderme (başka tenant) | ✓ | ✗ | ✗ |

---

# Bölüm 4 — Akış Senaryoları

Birinci kişi anlatımıyla, adım adım, hangi UI elemanını kullandığın belirtilerek.

## Senaryo 1 — Yeni tenant kurma (süper-yönetici)

**Sen:** İmga.AI'nin süper-yöneticisisin. Yeni müşteri Acme Inc. için bir tenant kurman lazım.

1. `/admin/tenants` sayfasına git (sidebar → YÖNETİM → Tenant'lar).
2. Sağ üst "Yeni Tenant" butonuna tıkla.
3. Modal'da:
   - İsim: "Acme Inc."
   - Slug otomatik dolacak: "acme-inc" (istersen "acme" yapabilirsin, sadece küçük harf + rakam + tire)
   - Plan: Deneme
   - Otomasyon: Yarı otomatik
   - "İlk admin daveti gönder" toggle'ı **aç**
   - E-posta: alice@acme.com
   - Tam Ad: Alice Smith
4. "Oluştur" butonuna bas.
5. Modal yeşil ✓ ile success view'a geçer. Davet linkini görüyorsun:
   `https://app.imga.ai/invite/aBcD1234...`
6. **"Kopyala" butonuna tıkla.** Linki Alice'e e-posta veya Slack'le gönder.
7. "Tamam, paylaştım" → modal kapanır.
8. Tenant tablosunda Acme Inc. satırı görünüyor. Plan/Otomasyon badge'leri yerinde.

**Alice tarafında:**

1. Linki tıklıyor → `/invite/aBcD1234...` açılıyor.
2. PreviewHeader: "Acme Inc." + "Yönetici" badge + e-postası.
3. Yeni hesap formu (email_exists=false): Tam Adınız + Şifre + Şifre Tekrar.
4. Doldurup "Daveti Kabul Et" → otomatik giriş yapıp `/`'a yönlendiriliyor.

Tenant kuruldu, ilk yönetici giriş yaptı. Sayfada 4 metric kartı 0'larla görünür (henüz veri yok).

---

## Senaryo 2 — Bir analist günlük olarak ne yapar

**Sen:** Bob, Acme Inc.'in analistsin. Müşteri hizmetleri ekibinde çalışıyorsun.

### Sabah açılışı

1. `/login` → e-posta + şifre → `/` (panel) açılır.
2. **Metric kartlara bak:**
   - Açık ticket: 12 (tüm aktif ticket'lar)
   - Bugün açılan: 3
   - Yüksek öncelik: 4
   - Son 7 gün çözülen: 18 → ekibin ortalama hızı.

### Yüksek öncelikli işleri sıraya alma

3. Sidebar → Ticket'lar → `/tickets`
4. Filtre çubuğu:
   - Atanan: "Bana atananlar" → kendi listene bak
   - Eğer boşsa → "Atanmamış" + Öncelik: "Acil"+"Yüksek" filtreyle
5. Tablodan üstten ilkini seç → `/tickets/{id}` detay sayfası

### Bir ticket'ı çözmek

6. Detay sayfası açıldı. Şu an OPEN durumunda, sana atanmamış.
7. Action Bar'da **"Üstlen"** butonuna bas → durum IN_PROGRESS olur, sana atanır, toast: "Üstlen işlemi tamamlandı".
8. Müşteri iletişim bilgisini ticket özetinden okuyup ara/email'le.
9. **Yorumlar bölümünde** iç not bırak: "Müşteriyi aradım, kargo şirketi takip numarasını paylaştı"
   - Tip: İç not (varsayılan)
   - "Gönder"
10. Müşteriye yanıt yaz:
    - Tip: Müşteri yanıtı (radio'yu değiştir)
    - Body: "Sayın müşterimiz, kargo bilgilerinizi paylaşıyoruz: ..."
    - "Gönder"
11. Sorun çözüldüğünde Action Bar'da **"Çöz"** butonuna bas → durum RESOLVED.
12. 7 gün sonra otomasyon worker'ı ticket'ı CLOSED'a düşürür (manuel kapatmana gerek yok).

### Müşteriden bilgi bekleyen durum

Eğer müşteri sana cevap göndermek için zaman istediyse:
- Action Bar'da **"Müşteri Bekle"** → durum PENDING_CUSTOMER.
- Müşteri cevap verince **"Devam et"** → IN_PROGRESS.
- Veya direkt **"Çöz"**.

### Yanlış üstlendin

Action Bar'da **"Bırak"** → durum tekrar OPEN, atama temizlenir. Başka analist üstlenebilir.

⚠️ Sadece **kendi üstlendiğin** ticket'ı bırakabilirsin. Başkası üstlendiyse "Bırak" butonu görünmez (yöneticiye görünür).

---

## Senaryo 3 — Manuel analiz (5 karar dalı için ne görünür)

**Sen:** Tenant ayarın **Yarı otomatik** modda. `/analyze` sayfasını test ediyorsun.

### 1. Bir kargo şikayetini analiz et

Textarea: "Kargom 5 gündür gelmedi, takip numarası da çalışmıyor. Çok kötü bir hizmet."

→ "Analiz Et" → 1-3 saniye → Sonuç:
- Sentiment: **NEGATİF (-0.8)**
- Kategori: **kargo (87%)**
- Karar kartı: ✅ **"Otomatik bilet açıldı"** (yeşil) → "Yeni bilete git →"
- Tıklayınca yeni ticket'ın detay sayfası açılır.

### 2. Aynı metni 1 saat sonra tekrar yapıştır

Aynı metin, "Analiz Et" tekrar.

→ Sonuç:
- Sentiment + Kategori aynı.
- Karar kartı: ℹ️ **"Aynı metin son 24 saatte zaten analiz edildi"** (mavi) → "Mevcut bilete git →"
- Tıklayınca aynı ticket'a gider.

### 3. Pozitif yorum dene (Tam otomatik modda)

Önce `/settings` → Otomasyon: Tam otomatik → Kaydet.

`/analyze` → "Kargom çok hızlı geldi, harika hizmet"

→ Sonuç:
- Sentiment: **POZİTİF (+0.85)**
- Kategori: kargo
- Karar kartı: ℹ️ **"Eşik altı — bilet açılmadı"** + decision_reason "full_auto_non_negative".

### 4. Belirsiz yorum

`/analyze` → "Bugün hava çok güzel, sahile gittim"

→ Sonuç:
- Sentiment: NÖTR
- Kategori: **belirsiz (0%)**
- Karar kartı: ℹ️ **"Kategori belirsiz — manuel sınıflandırma gerekli"**

### 5. Manuel modda

`/settings` → Manuel → Kaydet.

`/analyze` → herhangi bir negatif yorum

→ Sonuç:
- Sentiment + Kategori normal döner.
- Karar kartı: ℹ️ **"Otomasyon modu manuel — bilet açılmadı"** + öneri "Settings'ten otomasyon modunu değiştirin".

---

## Senaryo 4 — Multi-tenant kullanıcı geçişi

**Sen:** Bob. Acme'de analistsin, kardeş şirket Beta'da izleyici (raporlama için).

1. Login yaptın, varsayılan tenant Acme açıldı (`active_tenant_id` JWT'de Acme).
2. Sidebar üstündeki tenant switcher'a tıkla → Dropdown:
   - ✓ Acme Inc. (analyst)
   - Beta Co. (viewer)
   - + Yeni davet kabul et
3. Beta Co. üstüne tıkla → toast "Beta Co.'ya geçildi" → sayfa yenilenir.
4. Şimdi sidebar'da:
   - **Ayarlar** linki **görünür** ama sayfada "Yetkiniz yok" çıkar (izleyici için).
   - `/tickets` Beta'nın ticket'larını gösterir.
   - `/admin/tenants` görünmez (sadece süper-yönetici için).
5. Acme'ye geri dönmek için tekrar switcher → Acme Inc.

Davet token'ı aldıysan ve ekstra bir tenant'a daha katılmak istiyorsan:

1. Switcher → "+ Yeni davet kabul et" → modal açılır.
2. Token kutusuna yapıştır → "Kabul Et".
3. Mevcut hesap olduğun için arka plan `/invitations/{token}/accept-existing` yolundan ilerler — şifren tekrar istenir.
4. Başarılı → switcher otomatik yeni tenant'a geçer.

---

## Senaryo 5 — Otomasyon ayarlarını değiştirme

**Sen:** Acme yöneticisi. Şu an Manuel mod. Yarı otomatiğe geçirmek istiyorsun.

1. Sidebar → Ayarlar → `/settings`
2. "Otomasyon modu" başlığı altında 3 radio:
   - ⚪ Manuel (seçili)
   - ⚪ Yarı otomatik
   - ⚪ Tam otomatik
3. "Yarı otomatik" radio'ya tıkla → "Kaydet" butonu enable olur (değişiklik var).
4. "Kaydet" → toast "Otomasyon modu güncellendi", radio durumu ✓ Yarı otomatik.
5. Etki: artık `/analyze`'a gelen high-confidence + high-negative yorumlar otomatik bilet açacak.

### Bir global kategoriyi devre dışı bırak

Diyelim "iade" kategorisini şu an kullanmak istemiyorsun (henüz iade ekibi yok).

1. Aynı sayfada "Global kategoriler" listesini gör.
2. iade satırının yanındaki switch'i **kapat**.
3. Sayfa otomatik kaydeder, toast "Kategori güncellendi".
4. Etki: `/analyze` sınıflandırırken iade'yi havuzdan çıkarır; iade-tipi yorumlar muhtemelen "belirsiz"e düşer.

### Özel kategori ekle

Tenant'a özgü "VIP müşteri şikayeti" kategorisi açmak istiyorsun.

1. "Yeni özel kategori" butonuna bas.
2. Modal:
   - Kod: `vip_complaint` (sadece a-z, 0-9, _)
   - Türkçe etiket: "VIP Müşteri Şikayeti"
   - İngilizce etiket: "VIP Complaint"
   - Açıklama: "VIP müşteriden gelen, öncelikli ele alınması gereken şikayetler"
3. "Oluştur" → liste yenilenir, yeni satır görünür.
4. Backend bunu sınıflandırma havuzuna ekler (tenant'a özel olarak).

---

# Bölüm 5 — Üretim Smoke Test

Sprint 8.2 sonunda canlı production deploy doğrulandığında bu test'i yapacaksın. Her adım belirli bir bileşeni test eder; kırılma noktaları ne anlama geldiği aşağıda.

## 1. Login + dashboard yükleme

**Adım:** `https://app.imga.ai/login` aç. admin@imga.ai + parolanı gir.

**Beklenen:**
- Form submit → `/` (panel) açılır.
- "Merhaba, Süper Admin" karşılama satırı.
- 4 metric kart 0'larla görünür (yeni tenant, veri yok).

**Sorun çıkarsa:**
- 401 hatası → parola yanlış (yeniden dene) ya da JWT secret farklı (`/etc/imga/production/api.env`'i kontrol et).
- 500 hatası → API container down ya da Postgres bağlantısı kopuk; sunucuda `docker compose logs api` bak.
- Beyaz sayfa → web container'ı down ya da Caddy reverse_proxy çözemiyor.

## 2. Süper-yönetici sidebar görünürlüğü

**Adım:** Sidebar'a bak.

**Beklenen:**
- Üst grup: Panel / Ticket'lar / Analiz / Ayarlar.
- "YÖNETİM" başlığı + altında "Tenant'lar" satırı görünür.

**Sorun çıkarsa:**
- "YÖNETİM" görünmüyor → JWT'de `is_super_admin=false` (kullanıcı yanlış kişi).
- Süper-yönetici olduğun halde nav item çıkmıyor → frontend cache (Ctrl+Shift+R refresh).

## 3. Yeni tenant oluşturma

**Adım:** `/admin/tenants` → "Yeni Tenant" → form doldur (İlk admin daveti aç) → Oluştur.

**Beklenen:**
- Modal success view'a swap eder.
- Davet linki görünür (`https://app.imga.ai/invite/...`).
- Tenant tablosuna yeni satır eklenir.

**Sorun çıkarsa:**
- 409 (slug taken) → farklı slug seç.
- 403 → süper-yönetici değilsin.
- Davet linki dönmüyor → backend `initial_admin` block'unda hata; logları kontrol.

## 4. Davet linkinden hesap açma

**Adım:** Davet linkini kopyala. **Gizli (incognito) sekmede** aç.

**Beklenen:**
- `/invite/{token}` sayfası açılır.
- Tenant adı + rol + invitee email görünür.
- "Yeni hesap formu" çıkar (email_exists=false varsayımı).
- Form doldur (Tam Ad + 2 şifre) → "Daveti Kabul Et" → `/` panel'e yönlendir.

**Sorun çıkarsa:**
- "Bu davet geçersiz veya süresi dolmuş" → token yanlış kopyalandı veya 7 gün geçti.
- 422 → şifre 8 karakterden kısa.
- 403 sonra → email_exists=true ama formda new-user göründü; preview response'unda field eksik (Sprint 7.5.5 amendment'ı uygulanmamış).

## 5. Yeni tenant'a switch

**Adım:** Yeni hesabınla giriş yap. Tenant switcher'a bak.

**Beklenen:**
- Tek tenant göründüğü için switcher minimal: aktif tenant adı + ChevronDown.
- Tıklayınca dropdown'da "+ Yeni davet kabul et" satırı (tek satır, ✓ markı yok).

## 6. Manuel analiz testi

**Adım:** `/analyze` → textarea'ya "Kargom 5 gündür gelmedi, takip numarası da çalışmıyor" yapıştır → Analiz Et.

**Beklenen:**
- 1-3 saniye sonra Sonuç kartı: NEGATİF, kargo kategorisi.
- Karar kartı: 5 daldan biri (yeni tenant Yarı otomatik default'unda muhtemelen "Otomatik bilet açıldı" yeşil card).

**Sorun çıkarsa:**
- 30+ saniye yanıt yok → BERT model cold start; Backend container `start_period: 120s` boyunca pending olabilir (ilk istek). Tekrar dene.
- Decision card hiç çıkmıyor → response shape sorunu; network tab'a bak.
- 422 → text 1 char altında veya 10000 üstünde.

## 7. Yeni ticket detayı + yorum + arşiv

**Adım:** Açılan ticket'ı tıkla (Yeni bilete git). `/tickets/{id}` aç.

**Beklenen:**
- Title: "Kargom 5 gündür gelmedi..."
- Side panel: Açık badge, kargo kategorisi, atanmamış.
- Action Bar: "Üstlen" butonu görünür.
- Timeline'da "Açıldı" event'i var.
- Yorum formu en altta, "İç not" varsayılan.

**Test:**
- Üstlen → IN_PROGRESS, sana atanır.
- Yorum yaz (iç not) → "Test 1" → Gönder → yorum listesinde görünür.
- "Arşivle" butonuna tıkla → AlertDialog → onayla → yorum üzeri çizili, opaque.
- Çöz → RESOLVED.

**Sorun çıkarsa:**
- "Üstlen" butonu görünmüyor → rol matrix; izleyici olarak giriş yapmış olabilirsin.
- Arşivle butonu görünmüyor → kendi yorumun değil ya da yöneticisi değilsin.
- Müşteri yanıtı seçeneği disabled → ticket CLOSED/CANCELLED.

## Final smoke checkpoint

Yukarıdaki 7 adım tamamlandıysa:
- ✅ Frontend ↔ API ↔ Postgres çalışıyor
- ✅ Caddy TLS terminasyonu doğru
- ✅ JWT auth + RLS doğru
- ✅ State machine + role matrix doğru
- ✅ BERT analiz pipeline'ı çalışıyor
- ✅ Auto-ticket bridge 5 daldan en az 1'i (create) doğrulanmış
- ✅ Comment + archive flow çalışıyor

Müşteriye gösterilebilir noktadasın.

---

## Ek — Bilinen sınırlamalar (Sprint 8 sonrası)

Bu kılavuz şu anki ürün halini anlatır. Bazı özellikler **henüz yok** ama planlı:

| Özellik | Şu anki durum | Plan |
|---|---|---|
| Yorum düzenleme (5dk pencere) | Yok — sadece archive + yeniden yaz | Sprint 8 sonrası (C6 backlog) |
| Atama event'i timeline'da | Var (Sprint 7.7.2 patch sonrası) | Hazır |
| Auto-close worker (PENDING_CUSTOMER → CLOSED) | Yok | Sprint 8.4 |
| Backup (Backblaze B2) | Yok | Sprint 8.4 |
| Sentry + Uptime Robot | Yok | Sprint 8.5 |
| CI/CD (GitHub Actions auto-deploy) | Yok | Sprint 8.3 |
| Cursor pagination | Yok (offset, max 500) | Sprint 8 sonrası (C5) |
| Webhook customer-inbound bridge | Yok | Sprint 9+ |
| Mail server (transactional) | Yok | Sprint 9+ (3rd party kullanılıyor) |

---

**Doküman sonu.** Sorularınız için: `admin@imga.ai`.
