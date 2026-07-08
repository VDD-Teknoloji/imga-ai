# Modül 05 — Veri Yükleme UAT Koşum Raporu

**Tarih:** 2026-07-08 · **Ortam:** Production (`app.imga.ai`) — kullanıcı kararıyla; staging 8 hafta eskiydi
**Kurum:** DEMO · **Oturum:** Süper-yönetici (`admin@imga.ai`) — analist senaryoları süper-yönetici yetkisiyle koşuldu
**Test eden:** Claude (tarayıcı otomasyonu) + hulusi (giriş/ortam onayı)
**Yöntem notu:** Dosya seçimi tarayıcı otomasyonunda native diyalog açılamadığı için JS `DataTransfer`
enjeksiyonuyla yapıldı (SHA-256 doğrulamalı). Ön-doğrulama senaryoları CSV ile koşuldu; XLSX yolu
şablon indirme + preview çağrısıyla ayrıca tetiklendi.

## Sonuç özeti

| Senaryo | Sonuç | Not |
|---|---|---|
| ANL-01 Sayfa görünümü | ✅ Geçti | Başlık, açıklama, sayaç, NPS alanı, pasif buton tam |
| ANL-02 Negatif → oto Ticket | ✅ Geçti | NEGATIF −0.50, kargo %80, yeşil kart + Ticket `ed2d7b74` |
| ANL-03 Mükerrer (24s) | ✅ Geçti | Mavi kart + aynı Ticket'a "Mevcut Ticket'a git" |
| ANL-04 Manuel modda ticket yok | ✅ Geçti | Birebir beklenen kart metni |
| ANL-05 Eşik altı (pozitif) | ❌ KALDI | **BUG-2:** pozitif metin NEGATIF sınıflandı → yanlış oto-ticket `2a766438` |
| ANL-06 Belirsiz kategori | ✅ Geçti | Kart doğru; duygu kalitesi notu (alakasız metne −0.93) |
| ANL-07 Yine de Ticket Aç | ⚠️ Kısmen | **BUG-3:** belirsiz'de 409 + yanlış hata mesajı; normal kategoride çalışıyor (`fea02eca`) |
| ANL-08 Limit + NPS doğrulama | ✅ Geçti | 10.200 kırmızı sayaç + pasif buton; NPS 11 engellendi (mesaj native — kozmetik) |
| ANL-09 İzleyici engeli | ⏸ Koşulamadı | Viewer hesabı yoktu; backend 403 otomatik regresyon testiyle + RequireRole korumasıyla ayrıca doğrulanmış durumda |
| UPL-01 Şablon indirme | ✅ Geçti | Endpoint 200; içerik doğru (yorum/tarih/kaynak/nps + TALIMAT). Not: dosya `.tmp` GUID adıyla indi |
| UPL-02 Tip/boyut doğrulaması | ✅ Geçti | .txt ve 51MB reddi birebir mesajlarla |
| UPL-03 Temiz dosya (yeşil) | ✅ Geçti | "Dosya şablona uygun — 35 satır analiz edilecek." |
| UPL-04 Kolon yok (kritik) | ✅ Geçti | Kırmızı panel + birebir metin + buton kilitli + KVKK/PII uyarısı (bonus) |
| UPL-05 Boş dosya | ✅ Geçti | Birebir |
| UPL-06 Boş hücreler | ✅ Geçti | "9 analiz · 3 atlanacak", satır no'ları (3/7/10) doğru |
| UPL-07 Kopya satırlar | ✅ Geçti | 3. ve 6. satır tekrar uyarısı, buton aktif |
| UPL-08 Eski `text` formatı (kritik) | ⚠️ Kısmen | Dosya kabul ediliyor (yeşil ✓) ama "Metin sütunu" alanı `text`e güncellenmiyor |
| UPL-09 Otomatik Ticket aç seçeneği | ✅ Geçti | Açıklama birebir |
| UPL-10 İlerleme + canlı sayaçlar | ✅ Geçti | Çubuk + 4 sayaç + tahmini süre; 100/500 canlı artış görüldü |
| UPL-11 İptal | ✅ Geçti | "İptal edildi" durumu, 450'de kesildi |
| UPL-12 F5 yeniden bağlanma | ✅ Geçti | F5 sonrası Adım 3'e otomatik dönüş (bilgi toast'ı gözlenmedi — davranış tam) |
| UPL-13 Tamamlanma özeti | ✅ Geçti | Hem "Tamamlandı" (40/40) hem "İptal edildi" varyantı görüldü; iki buton çalışıyor |
| UPL-14 CSV ile tekrar | ✅ Geçti | Tüm ön-doğrulama + yükleme akışı CSV ile koşuldu |
| UPL-15 Geçmiş listesi | ✅ Geçti | Tablo + "Analizleri gör" filtreli açılıyor. Not: "Tamamlandı" rozeti yeşil değil turuncu |

**Toplam: 24 senaryo → 20 geçti · 1 kaldı · 2 kısmen · 1 koşulamadı**

## Bulunan bug'lar (öncelik sırasıyla)

### BUG-1 [Yüksek] Toplu yükleme ön-doğrulaması her istisnada 500 dönüyor + asıl hata maskeleniyor
`POST /tenants/me/analyze/batch/preview` — `tenant_batch.py:447`:
`log.exception(..., extra={"filename": safe_name})` → `filename` Python logging'in REZERVE
LogRecord alanı → `KeyError: "Attempt to overwrite 'filename' in LogRecord"`. Sonuç: preview'da
oluşan HER istisna 500'e dönüşüyor VE asıl hata loglardan siliniyor. Ayrıca tetikleyen alt-hata:
bozuk xlsx (`zipfile.BadZipFile`) `FileParseError`'a map edilmediği için 400 yerine 500 üretir —
kullanıcı "Bu dosya yüklenemez: dosya okunamıyor" yerine sessiz fallback ("Otomatik tespit
alınamadı") görüyor. **Düzeltme:** extra anahtarını yeniden adlandır (örn. `upload_filename`),
`BadZipFile`'ı FileParseError'a map et. Repo genelinde `extra={"filename"` taranmalı.

### BUG-2 [Yüksek] "İkincil Tetikleyici" katmanı pozitif cümleyi negatife çeviriyor → yanlış oto-ticket
"Kargom çok hızlı geldi, harika hizmet." → NEGATIF −0.40 (katman detayı: `İkincil Tetikleyici,
Eşleşen: kargo`). Katman "kargo" kelimesine takılıp cümle duygusunu eziyor; Tam otomatik modda
YANLIŞ ticket açıldı. Toplu yüklemede de aynı desen: "tesekkurler harika hizmet" satırları Olumsuz
işaretlendi. İlgili yer: imga-core override katmanları (ikincil tetikleyici sözlüğü). **Düzeltme
önerisi:** tetikleyici katman yalnız BERT skoru zaten negatifken güçlendirsin; pozitif skoru
tersine çevirmesin.

### BUG-3 [Orta] Belirsiz analizde "Yine de Ticket Aç" imkânsız + yanlış hata mesajı
(a) Backend: `promote_to_ticket` → `_resolve_category_id("belirsiz")` →
`CategoryNotConfiguredError` → 409 `"category 'belirsiz' is not configured for this tenant"`.
Buton belirsiz sonuç kartında sunulduğu halde hiçbir zaman çalışamıyor (belirsiz pseudo-kategori).
(b) Frontend: her 409'u sabit **"Bu analiz zaten bir Ticket'a bağlı."** metniyle gösteriyor —
API detayını yansıtmalı. Doğrulama: normal kategori (urun_kalitesi) ile promote sorunsuz (201).

### BUG-4 [Orta] Batch preview/upload istekleri access-token yenileme akışına bağlı değil
15 dk'lık access token süresi dolduktan sonraki ilk preview → 401 → kullanıcıya "Önizleme
alınamadı: missing access token". Diğer tüm çağrılar `apiRequest`'in 401→refresh→retry
sarmalayıcısından geçiyor; multipart preview/upload fetch'i de aynı akışa bağlanmalı.

### Minör / kozmetik
- UPL-08: eski `text` kolonlu dosyada "Metin sütunu" alanı `yorum` kalıyor (kabul ediliyor ama
  alan senkron değil; yükleme yine başarılı).
- NPS 0-10 doğrulaması native tarayıcı mesajı ("Değer 10 veya daha küçük olmalıdır") — UAT
  beklentisi özel metin ("NPS 0 ile 10 arasında olmalı.").
- Şablon indirme `.tmp` GUID adıyla kaldı; `imga-toplu-yukleme-sablonu.xlsx` adı gelmedi
  (Content-Disposition doğrulanmalı).
- Geçmiş Yüklemeler'de "Tamamlandı" rozeti yeşil değil turuncu.
- SmartColumnDetector `yorum` kolonuna "product_name (%60)" önerisi gösteriyor (zararsız ama
  güven vermez).
- Model duygu kalitesi: alakasız metin ("Bugün hava çok güzel...") −0.93 NEGATIF; nötr sorular
  ("Fatura bilgilerimi nasıl güncelleyebilirim") Olumsuz işaretlenebiliyor. BUG-2 ile ilişkili.

## Test verisi kalıntısı (DEMO kurumu — temizlik önerisi)

- ~540 analiz kaydı (40 tamamlanan + 450 iptal edilene kadar işlenen + manuel analizler) —
  Analiz Arşivi'nde "uat" aramasıyla bulunur.
- 3 test ticket'ı: `ed2d7b74` (ANL-02), `2a766438` (ANL-05 — yanlış oto-ticket kanıtı),
  `fea02eca` (ANL-07). İncelendikten sonra İptal edilebilir.
- Otomasyon modu teste başlarkenki değerine (Yarı otomatik) geri döndürüldü.
