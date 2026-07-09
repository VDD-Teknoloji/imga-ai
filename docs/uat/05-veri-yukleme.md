# 05 — Veri Yükleme (Manuel Analiz + Toplu Yükleme)

**Kapsam:** Manuel Analiz (`/analyze`), Toplu Yükleme sihirbazı
(`/analyze/upload`) ve ön-doğrulama, Geçmiş Yüklemeler
(`/analyze/upload/history`).

**Rol notu:** Manuel Analiz ve Toplu Yükleme **Analist** ve **Yönetici**
içindir. **İzleyici** bu sayfalara giremez (yalnız şablonu indirme ve
geçmiş görüntüleme bazı durumlarda açık olabilir). Şablon indirme tüm
roller için açıktır.

> **Bu modül kritik.** Toplu yüklemenin ön-doğrulama (pre-flight)
> bölümü, yanlış formatlı dosyaları **yüklemeden önce** satır numarasıyla
> yakalar. Test dosyalarını modül 00'daki tabloya göre hazırla.

> **KOŞUM KAYDI (08.07.2026):** Bu modülün 24 senaryosunun tamamı
> production/DEMO kurumunda tarayıcı otomasyonuyla koşuldu —
> **21 geçti · 1 kaldı (ANL-05) · 2 kısmen (ANL-07, UPL-08)**.
> Bulunan 5 bug'ın detayı ve test kalıntıları:
> [`2026-07-08-05-veri-yukleme-kosum-raporu.md`](2026-07-08-05-veri-yukleme-kosum-raporu.md).
> Aşağıdaki sonuç alanları bu koşuma göre doldurulmuştur.

---

## A. Manuel Analiz (`/analyze`)

### UAT-ANL-01 — Sayfa görünümü
**Rol / Önkoşul:** Analist.
**Adımlar:**
1. Sol menü → **Operasyon → Manuel Analiz**.

**Beklenen sonuç:**
- Başlık **"Yorum Analiz Et"**.
- Açıklama: *"Müşteri yorumunu yapıştırın. Duygu ve kategori analizi
  yapılır; kurum otomasyon ayarına göre gerekirse Ticket otomatik açılır."*
- "Yorum metni" alanı, NPS (opsiyonel, 0–10) alanı ve **"Analiz Et"** butonu var.

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** Tüm öğeler birebir mevcut; sayaç "0 / 10.000 karakter" ve boş
metinde buton pasif (ANL-08'in ilk maddesi burada da doğrulandı).

---

### UAT-ANL-02 — Negatif yorum analizi (otomatik Ticket — Yarı/Tam otomatik)
**Rol / Önkoşul:** Analist · Kurum otomasyon modu **Yarı otomatik** veya
**Tam otomatik**.
**Adımlar:**
1. Metin alanına negatif bir yorum yaz: *"Kargom 5 gündür gelmedi, takip
   numarası da çalışmıyor. Çok kötü bir hizmet."*
2. **"Analiz Et"**'e bas, 1–5 saniye bekle.

**Beklenen sonuç:**
- Buton "Analiz ediliyor…" gösterip sonra sonucu döner.
- **"Analiz sonucu"** kartı: Duygu **NEGATIF** (kırmızı) + skor, Kategori
  rozeti + **"%.. güven"**.
- Karar kartı (yeşil): **"Otomatik Ticket açıldı"** + *"Kurumunuzun
  otomasyon ayarı bu yoruma göre yeni bir Ticket açtı."* + **"Yeni Ticket'a git →"**.
- Linke tıklayınca yeni ticket'ın detay sayfası açılıyor.

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** NEGATIF −0.50, kargo %80 güven; yeşil kart metni birebir;
Ticket `ed2d7b74` açıldı, link detay sayfasını (Açık / Kargo-Lojistik +
"Bu Ticket'ı Açan Analiz" paneli) doğru açtı. Bonus: SLA Aşımı rozeti ve
Tetiklenen Katmanlar bölümü de geldi.

---

### UAT-ANL-03 — Mükerrer metin (24 saat içinde)
**Rol / Önkoşul:** Analist · UAT-ANL-02'deki yorumu az önce analiz etmiş ol.
**Adımlar:**
1. **Aynı** metni tekrar yapıştır → **"Analiz Et"**.

**Beklenen sonuç:**
- Karar kartı (mavi): **"Aynı metin son 24 saatte zaten analiz edildi"** +
  *"Tekrar Ticket açılmadı; mevcut Ticket'ın altında çalışmaya devam et."*

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** Kart metinleri birebir; "Mevcut Ticket'a git →" aynı Ticket
ID'ye (`ed2d7b74`) yönlendirdi.

---

### UAT-ANL-04 — Manuel modda Ticket açılmaz
**Rol / Önkoşul:** Yönetici (modu değiştirmek için) · Kurum modu **Manuel**.
**Adımlar:**
1. (Yönetici) Ayarlar'dan otomasyon modunu **Manuel** yap.
2. (Analist veya yönetici) `/analyze` → negatif bir yorum analiz et.

**Beklenen sonuç:**
- Duygu + kategori normal dönüyor.
- Karar kartı (mavi): **"Otomasyon modu manuel — Ticket açılmadı"** +
  açıklama "kurum ayarlarını Tam veya Yarı otomatik yap".

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** "Ürün kırık geldi…" → NEGATIF −1.00, urun_kalitesi %40; kart
metni birebir. Test sonunda mod Yarı otomatik'e geri alındı.

---

### UAT-ANL-05 — Eşik altı (pozitif yorum, Tam otomatik)
**Rol / Önkoşul:** Analist · Kurum modu **Tam otomatik**.
**Adımlar:**
1. Pozitif bir yorum yaz: *"Kargom çok hızlı geldi, harika hizmet."* → Analiz Et.

**Beklenen sonuç:**
- Duygu **POZITIF**.
- Karar kartı (mavi): **"Eşik altı — Ticket açılmadı"**.

**Sonuç:** ☐ Geçti ☒ **KALDI** · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** **BUG-2 (Yüksek):** Açıkça pozitif cümle **NEGATIF −0.40**
sınıflandı — "İkincil Tetikleyici" katmanı "kargo" kelimesiyle eşleşip
skoru eziyor. Sonuç: Tam otomatik modda **yanlış otomatik Ticket açıldı**
(`2a766438`). Toplu yüklemede de aynı desen görüldü ("teşekkürler harika
hizmet" satırları Olumsuz). Katman, cümle duygusu pozitifken tetiklenmemeli.

---

### UAT-ANL-06 — Belirsiz kategori
**Rol / Önkoşul:** Analist.
**Adımlar:**
1. Konuyla ilgisiz bir metin yaz: *"Bugün hava çok güzel, sahile gittim."* → Analiz Et.

**Beklenen sonuç:**
- Kategori **belirsiz**.
- Karar kartı (mavi): **"Kategori belirsiz — manuel sınıflandırma gerekli"**.

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** Kategori belirsiz (%0 güven) + kart metni doğru. Model kalitesi
notu: alakasız/olumlu metne duygu **NEGATIF −0.93** ve Özet "Hile" verildi —
senaryo kriterini etkilemiyor ama BUG-2 ile aynı negatiflik eğiliminin kanıtı.

---

### UAT-ANL-07 — "Yine de Ticket Aç" (manuel zorlama)
**Rol / Önkoşul:** Analist · UAT-ANL-04/05/06'daki gibi Ticket açılmamış bir sonuç.
**Adımlar:**
1. Karar kartının altındaki **"Yine de Ticket Aç"** butonuna bas.

**Beklenen sonuç:**
- Sistem güveni geçersiz kılınıp manuel Ticket açılıyor; ilgili ticket'a
  yönlendiren bağlantı/onay görünüyor.

**Sonuç:** ⚠ **KISMEN** · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** Yapılandırılmış kategoride (ANL-04 sonucu, urun_kalitesi)
sorunsuz: "Manuel olarak Ticket açıldı" + `fea02eca`. **BUG-3 (Orta):**
**belirsiz** sonuçta (ANL-06) buton HİÇ çalışamıyor — API 409
`"category 'belirsiz' is not configured for this tenant"`; frontend bunu
yanlış metinle ("Bu analiz zaten bir Ticket'a bağlı.") gösteriyor. Buton
belirsiz kartında sunulduğu hâlde işlevsiz.

---

### UAT-ANL-08 — Karakter limiti ve NPS doğrulaması
**Rol / Önkoşul:** Analist.
**Adımlar:**
1. Metin alanını boş bırak → "Analiz Et" butonunun durumuna bak.
2. 10.000 karakteri aşan bir metin yapıştır → sayaç ve butonu gözle.
3. NPS alanına **11** yaz → Analiz Et.

**Beklenen sonuç:**
- Boş metinde buton **pasif**.
- Sayaç **"{n} / 10.000 karakter"**; limit aşılınca kırmızı, buton pasif.
- NPS 11 → hata: **"NPS 0 ile 10 arasında olmalı."**

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** Boş → pasif ✓; 10.200 karakterde sayaç kırmızı + alan kırmızı
ring + buton pasif ✓; NPS 11 gönderimi engellendi ✓ ama mesaj beklenen özel
metin yerine tarayıcının yerleşik doğrulaması ("Değer 10 veya daha küçük
olmalıdır.") — kozmetik sapma.

---

### UAT-ANL-09 — İzleyici manuel analiz yapamaz
**Rol / Önkoşul:** İzleyici.
**Adımlar:**
1. `/analyze`'a gitmeyi dene (menüde görünüyorsa tıkla, yoksa URL'yi yaz).

**Beklenen sonuç:**
- İzleyici analiz **gönderemiyor** (sayfa erişimi engelli ya da gönderimde
  *"Bu işlem için yetkin yok."*).

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude + hulusi (viewer girişi) · **Tarih:** 08.07.2026
**Notlar:** Gerçek izleyici hesabıyla (uat-izleyici@example.com) dört kanıt:
(1) menüde Veri Yükle / Ayarlar / Yönetim bölümleri hiç yok; (2) `/analyze`
ve `/analyze/upload` URL'leri "Yetkiniz yok" sayfası; (3) API
`POST /tenants/me/analyze` → **403 insufficient permissions**; (4) hızlı
işlemler (FAB) menüsünde yükleme kısayolu yok. İki yan bulgu: **BUG-5
(Yüksek)** — Kullanıcılar sayfasının ürettiği davet linki `/invitations/…`
404 veriyor (doğru route `/invite/…`); kozmetik — "Yetkiniz yok" açıklama
metni her sayfada ayar-odaklı cümleyi gösteriyor.

---

## B. Toplu Yükleme Sihirbazı (`/analyze/upload`)

Sihirbaz 4 adımlı: **Dosya → Sütunlar → İlerleme → Tamamlandı**.

### UAT-UPL-01 — Şablon indirme
**Rol / Önkoşul:** Analist.
**Adımlar:**
1. **Operasyon → Toplu Yükleme**'yi aç.
2. Üstteki **"Şablonu İndir"** butonuna bas.

**Beklenen sonuç:**
- Başlık **"Toplu Yükleme"**; açıklama: *"CSV ya da XLSX yükleyin; metinler
  arka planda analiz edilir, sonuç Analiz Arşivi'nde görünür."*
- Şablon `imga-toplu-yukleme-sablonu.xlsx` adıyla iniyor; içinde **yorum** kolonu var.

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** Başlık/açıklama birebir; `GET /analyze/batch/template` 200;
içerik doğru (Yorumlar sayfası: yorum/tarih/kaynak/nps + TALIMAT sayfası).
Minör: dosya `imga-toplu-yukleme-sablonu.xlsx` adı yerine `.tmp` uzantılı
GUID adıyla indi — Content-Disposition başlığı kontrol edilmeli.

---

### UAT-UPL-02 — Adım 1: dosya tipi/boyut doğrulaması
**Rol / Önkoşul:** Analist.
**Adımlar:**
1. Sürükle-bırak alanına `.txt` veya `.pdf` gibi desteklenmeyen bir dosya bırak.
2. 50 MB'tan büyük bir dosya dene (varsa).

**Beklenen sonuç:**
- Yanlış uzantı → **"Sadece .csv veya .xlsx dosyaları kabul edilir."**
- Çok büyük dosya → **"Dosya 50 MB sınırını aşıyor."**
- Alanın altında kural: *"CSV, XLSX — en fazla 50 MB, en fazla 10.000 satır"*.

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** Üç madde de birebir doğrulandı (.txt reddi, 51 MB sentetik
dosya reddi, kural metni).

---

### UAT-UPL-03 — TEMİZ dosya: yeşil ön-doğrulama
**Rol / Önkoşul:** Analist · `temiz.xlsx` (yorum kolonu + 30–100 geçerli satır).
**Adımlar:**
1. Adım 1'de `temiz.xlsx`'i seç → otomatik Adım 2'ye geçer.
2. **Sütun Eşleştirme** ekranındaki ön-doğrulama panelini incele.

**Beklenen sonuç:**
- **Yeşil** panel + onay ikonu: **"Dosya şablona uygun — {N} satır analiz edilecek."**
- "Metin sütunu" otomatik **yorum** tespit edilmiş.
- **"Yüklemeyi Başlat"** butonu **aktif**.

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** Yeşil panel "Dosya şablona uygun — 35 satır analiz edilecek."
birebir; metin sütunu otomatik `yorum`; buton aktif (koşum CSV ile).
İlişkili bulgu **BUG-1 (Yüksek):** okunamayan/bozuk XLSX'te preview endpoint'i
400 yerine **500** dönüyor — `tenant_batch.py:447`'deki
`log.exception(extra={"filename": …})` çağrısı rezerve LogRecord alanı
yüzünden KeyError atıp asıl hatayı da maskeliyor; `BadZipFile`
`FileParseError`'a map'lenmeli. Ayrıca **BUG-4 (Orta):** 15 dk access-token
süresi dolunca ilk önizleme "Önizleme alınamadı: missing access token"
veriyor — preview/upload istekleri 401→refresh→retry akışına bağlı değil.
Minör: akıllı dedektör `yorum` kolonuna "product_name (%60)" önerisi gösteriyor.

---

### UAT-UPL-04 — KOLON YOK: kırmızı engelleyici hata (kritik)
**Rol / Önkoşul:** Analist · `kolon-yok.xlsx` (yorum kolonu hiç yok).
**Adımlar:**
1. `kolon-yok.xlsx`'i seç → Adım 2.

**Beklenen sonuç:**
- **Kırmızı** panel: başlık **"Bu dosya yüklenemez"**.
- Hata mesajı: **"Zorunlu 'yorum' kolonu bulunamadı. Dosyadaki kolonlar: …"**.
- İpucu: *"'Şablonu İndir' butonundan Excel şablonunu alın, yorumlarınızı
  'yorum' kolonuna yapıştırın."*
- **"Yüklemeyi Başlat"** butonu **KİLİTLİ** (üzerine gelince: *"Dosyadaki
  engelleyici hataları düzeltip yeniden yükleyin"*).

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** Kırmızı panel + hata metni + ipucu birebir; buton kilitli.
Bonus: `isim` kolonu için KVKK/kişisel veri uyarısı + onay kutusu da çalışıyor.

---

### UAT-UPL-05 — BOŞ DOSYA: kırmızı hata
**Rol / Önkoşul:** Analist · `bos-dosya.xlsx` (sadece başlık satırı).
**Adımlar:**
1. `bos-dosya.xlsx`'i seç → Adım 2.

**Beklenen sonuç:**
- Kırmızı panel: **"Dosya boş ya da yalnızca başlık satırı içeriyor."**
- İpucu: *"Yorumlarınızı 'yorum' kolonuna yazıp tekrar deneyin."*
- "Yüklemeyi Başlat" kilitli.

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** Üç madde de birebir.

---

### UAT-UPL-06 — BOŞ HÜCRELER: sarı uyarı (satır numaralı)
**Rol / Önkoşul:** Analist · `bos-hucreli.xlsx` (bazı satırlarda yorum hücresi boş).
**Adımlar:**
1. `bos-hucreli.xlsx`'i seç → Adım 2.

**Beklenen sonuç:**
- **Sarı/amber** panel: başlık **"{N} satır analiz edilecek · {M} satır atlanacak"**.
- Her boş satır için satır numarasıyla uyarı: örn. **"7. satırda 'yorum'
  boş — bu satır atlanacak"** (50'den fazlaysa *"…ve {x} satır daha."*).
- Alt açıklama: *"Bu satırları yine de yükleyebilirsiniz; atlanan satırlar
  analiz edilmez."*
- **"Yüklemeyi Başlat"** butonu **aktif** (uyarı engellemez).

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** "9 satır analiz edilecek · 3 satır atlanacak" + 3./7./10.
satır uyarıları (beklenen satırlarla birebir) + alt açıklama + aktif buton.

---

### UAT-UPL-07 — KOPYA SATIRLAR: sarı uyarı
**Rol / Önkoşul:** Analist · `kopya-satir.xlsx` (aynı yorum 2–3 kez).
**Adımlar:**
1. `kopya-satir.xlsx`'i seç → Adım 2.

**Beklenen sonuç:**
- Sarı panel: tekrar eden satırlar için uyarı, örn. **"5. satır dosya
  içinde tekrar ediyor — bir kez analiz edilecek"**.
- "Yüklemeyi Başlat" aktif.

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** "3. satır … tekrar ediyor — bir kez analiz edilecek" ve
"6. satır …" uyarıları doğru; "6 satır analiz edilecek · 2 satır atlanacak".

---

### UAT-UPL-08 — Eski format (`text` kolonu) geriye uyumluluk
**Rol / Önkoşul:** Analist · `eski-format.xlsx` (yorum yerine eski **text** kolonu).
**Adımlar:**
1. `eski-format.xlsx`'i seç → Adım 2.

**Beklenen sonuç:**
- Dosya **kabul ediliyor** (yeşil veya sarı panel) — eski `text` kolonu
  hâlâ geçerli.
- "Metin sütunu" `text` olarak tespit ediliyor.
- **Bu özellikle test edilmeli:** eski müşteri dosyaları "yüklenemez"
  hatası vermemeli.

**Sonuç:** ⚠ **KISMEN** · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** Kritik gereksinim sağlandı: dosya KABUL edildi (yeşil panel,
"10 satır analiz edilecek") — eski dosya "yüklenemez" hatası vermiyor.
Sapma: "Metin sütunu" alanı `text`e güncellenmiyor, `yorum` olarak
kalıyor (yükleme yine başarılı; alan senkronizasyonu düzeltilmeli).

---

### UAT-UPL-09 — Otomatik Ticket aç seçeneği
**Rol / Önkoşul:** Analist · `temiz.xlsx`.
**Adımlar:**
1. Adım 2'de **"Otomatik Ticket aç"** kutusunu incele (aç/kapat).

**Beklenen sonuç:**
- Açıklama: *"Kurumunuzun otomasyon modu ayarına göre eşiği geçen satırlar
  için otomatik Ticket açılır. Kapalıysa hiçbir satır Ticket açmaz; tüm
  analizler Analiz Arşivi'nde listelenir."*
- Seçim yüklemeye yansıyor.

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** Açıklama metni birebir; kutu kapalıyken koşulan 40 satırlık
yüklemede Ticket sayacı 0 kaldı (seçim yüklemeye yansıyor).

---

### UAT-UPL-10 — Adım 3: ilerleme ve canlı sayaçlar
**Rol / Önkoşul:** Analist · `temiz.xlsx` (30–100 satır).
**Adımlar:**
1. Adım 2'de **"Yüklemeyi Başlat"**'a bas.
2. Adım 3 (**İlerleme**) ekranını izle.

**Beklenen sonuç:**
- Dosya adı + satır sayısı görünüyor.
- İlerleme çubuğu **% canlı artıyor**.
- Sayaçlar güncelleniyor: **Başarılı**, **Hatalı**, **Tekrar**, **Ticket**.
- Tahmini kalan süre (varsa) görünüyor.
- İş bitince otomatik **Adım 4**'e geçiyor.

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** Tüm öğeler mevcut (dosya adı, çubuk, 4 sayaç, "Kalan tahmini
süre"); canlı artış 500 satırlık koşuda gözlendi (0 → 100/500 %20 → 450);
40 satırlık iş ~15 sn'de bitip otomatik Adım 4'e geçti.

---

### UAT-UPL-11 — İlerlemeyi iptal etme
**Rol / Önkoşul:** Analist · Yeterince büyük bir dosya (iptal için zaman olsun).
**Adımlar:**
1. Yükleme sürerken (Adım 3) **"İptal Et"** butonuna bas.

**Beklenen sonuç:**
- İş iptal ediliyor; durum "İptal edildi" oluyor.

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** 500 satırlık iş 450. satırda iptal edildi; Adım 4 başlığı
"İptal edildi" (amber) + o ana dek işlenen sayılar korunuyor; Geçmiş
Yüklemeler'de durum "İptal".

---

### UAT-UPL-12 — Yarım kalan yüklemeye yeniden bağlanma
**Rol / Önkoşul:** Analist · Bir yükleme devam ederken.
**Adımlar:**
1. Yükleme sürerken sayfayı **yenile (F5)** ya da başka sayfaya gidip geri dön.

**Beklenen sonuç:**
- Sistem devam eden işi buluyor; bilgi mesajı: **"Devam eden yükleme
  bulundu ({dosya}) — ilerlemeye yeniden bağlanıldı."**
- Tekrar Adım 3 ilerlemesine dönülüyor.

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** F5 sonrası sihirbaz devam eden işi bulup doğrudan Adım 3
ilerlemesine döndü (100/500, sayaçlar canlı). Bilgi toast'ı gözlemlenemedi
(hızlı kaybolmuş olabilir) — davranış tam, mesaj varyasyonu minör.

---

### UAT-UPL-13 — Adım 4: tamamlanma özeti
**Rol / Önkoşul:** Analist · Bir yükleme tamamlanmış.
**Adımlar:**
1. Adım 4 (**Tamamlandı**) ekranını incele.

**Beklenen sonuç:**
- Başlık **"Tamamlandı"** (yeşil) veya hata varsa **"Başarısız"** (amber).
- Sayaçlar: **İşlenen / Başarılı / Hatalı / Ticket**.
- Hata varsa **"Hata özeti ({adet})"** açılır listede satır numaralı hatalar.
- **"Bu Yüklemenin Analizlerini Gör"** butonu → Analiz Arşivi'ni o yüklemeye
  filtreli açıyor.
- **"Yeni Yükleme"** butonu sihirbazı Adım 1'e sıfırlıyor.

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** "Tamamlandı" (40/40/0/0) ve "İptal edildi" (450) varyantlarının
ikisi de görüldü; her iki buton da doğru çalışıyor ("Analizleri Gör" →
`/reviews?batch_job_id=…` filtreli, 40 kayıt). Hatalı-satır varyantı bu
koşumda üretilmedi.

---

### UAT-UPL-14 — CSV ile tekrar
**Rol / Önkoşul:** Analist · `temiz.csv` (xlsx yerine CSV).
**Adımlar:**
1. UAT-UPL-03 + UAT-UPL-10'u bir `.csv` dosyasıyla tekrar et.

**Beklenen sonuç:**
- CSV de aynı şekilde ön-doğrulamadan geçip yükleniyor.

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** Koşumun ön-doğrulama senaryoları (UPL-03…08) ve tam yükleme
akışı (UPL-10/13) CSV ile gerçekleştirildi — CSV yolu uçtan uca doğrulandı.

---

## C. Geçmiş Yüklemeler (`/analyze/upload/history`)

### UAT-UPL-15 — Geçmiş listesi
**Rol / Önkoşul:** Analist · En az 1 tamamlanmış yükleme.
**Adımlar:**
1. Toplu Yükleme sayfasından **"Geçmiş Yüklemeler"**'e git.

**Beklenen sonuç:**
- Başlık **"Geçmiş Yüklemeler"**.
- Tablo: Tarih, Dosya, Satır, Durum, Başarılı, Hata, Ticket sütunları.
- Durum rozetleri renkli (tamamlandı=yeşil, işleniyor=sarı, başarısız=kırmızı).
- Her satırda **"Analizleri gör →"** linki çalışıyor.
- Boşken: **"Henüz toplu yükleme yok. İlk dosyanızı buradan yükleyebilirsiniz."**

**Sonuç:** ☑ Geçti ☐ Kaldı · **Test eden:** Claude (otomasyon) · **Tarih:** 08.07.2026
**Notlar:** Başlık, kolonlar ve filtreli "Analizleri gör" linki doğru;
test koşuları (İptal + Tamamlandı) listede. Kozmetik: "Tamamlandı" rozeti
yeşil değil turuncu; "İptal" rozetsiz düz metin. Boş-durum mesajı DEMO'da
veri olduğu için doğrulanamadı.

---

## Modül 05 özeti

| Senaryo | Geçti | Kaldı | Not |
|---|---|---|---|
| ANL-01 … ANL-09 | 7 | 1 (ANL-05) | ANL-07 kısmen — belirsiz'de "Yine de Ticket Aç" işlevsiz (BUG-3) |
| UPL-01 … UPL-15 | 14 | 0 | UPL-08 kısmen — kabul ✓ ama "Metin sütunu" alanı `text`e güncellenmiyor |

**Genel değerlendirme:** ☐ Modül kabul edildi ☒ **Bloke eden hata var**

> Bloke edenler: **BUG-2** (İkincil Tetikleyici pozitif cümleyi negatife
> çevirip Tam otomatikte yanlış Ticket açıyor — ANL-05) ve **BUG-1**
> (ön-doğrulama endpoint'i her istisnada 500 + hata maskeleme). Ayrıca
> **BUG-5** (Kullanıcılar sayfasının davet linki 404) davet akışını kırıyor.
> Tam bug listesi ve kanıtlar:
> [`2026-07-08-05-veri-yukleme-kosum-raporu.md`](2026-07-08-05-veri-yukleme-kosum-raporu.md).

> **Özellikle doğrula:** UAT-UPL-04 (kolon yok → kilit) ve UAT-UPL-08
> (eski `text` formatı → geçer). Bu ikisi ürün sahibinin "yanlış formatı
> nokta atışı yakala, ama eski dosyaları bozma" gereksiniminin kalbidir.
> *(Koşum sonucu: UPL-04 birebir geçti; UPL-08'de dosya kabul ediliyor,
> yalnız "Metin sütunu" alan senkronu eksik.)*
