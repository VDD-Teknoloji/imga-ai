# imga UX Yeniden Planı — "Kök Neden Önce" (2026-09-01)

> Talep (ürün sahibi, 2026-09-01): "Biz müşteriye 'şu kadar pozitif, şu kadar
> negatif yorum var' demiyoruz; müşterilerinin en çok sorun yaşadığı yeri
> gösterip kanıtını sunuyoruz. Kök neden analizlerini kullanıcının gözüne
> sokmalıyız; kanıt isterse yorumlara gitsin. Veri kalitesi de bir CX işidir.
> Kullanıcı en basit işlemleri (veri yükleme, kök neden) kolayca yapabilmeli."

Bu doküman keşif dalgasının (10 ajanlık kod taraması, dosya:satır kanıtlı)
bulguları üzerine kuruludur ve Sprint 13'te yerleşen "Apple gibi, bir aptal
bile anlasın; işten anlayan detaya inebilsin" ilkesini **korur** — yön
değişikliği görsel değil, **bilgi hiyerarşisi** değişikliğidir.

---

## 1. Teşhis: bugün ne yanlış

Mevcut ana sayfa sıralaması: ExecutiveHero (duygu yüzdeleri) → NPS +
kategori sayıları → PriorityAction (tek cümle) → TopProblems (sayı + 1
alıntı) → SWOT/OKR kartları. Sorunlar:

1. **Kök neden 3 tık derinde.** Ürünün asıl vaadi (`root_cause_analyses`:
   başlık + açıklama + kanıt alıntıları + etkilenen yüzey + önerilen aksiyon
   + pay tahmini) yalnızca kategori çubuğu → alt kategori → Sparkles butonu
   yolundan açılan bir modal'da. Navlungo'daki "gümrük belgeleri müşteriye
   doğru bildirilmiyor" bulgusu sistemde ÜRETİLEBİLİYOR ama kimse görmüyor.
2. **Hiç otomatik üretilmiyor.** Kök neden %100 tık-tetiklemeli; hiçbir batch
   sonrası ön-üretim yok. İlk ziyarette boş durum + "Analiz Oluştur" butonu.
3. **Üç içgörü hattı birbirinden habersiz.** PriorityAction (SWOT önerisi),
   AiInsightStrip (brifing başlığı) ve kök neden üç ayrı üretim hattı; hiçbiri
   diğerini beslemiyor. Kullanıcıya "ne yapmalıyım"ın tek bir yüzeyi yok.
4. **TopProblems "ne"yi söylüyor, "neden"e bağlanmıyor.** Saf SQL sıralaması +
   1 alıntı; kartlar /reviews'a gidiyor, kök nedene değil.
5. **Reviews sayfası liste-veri tekrarı.** Firma kendi paylaştığı yorumların
   listesini görüyor; filtreye tepki veren hiçbir analiz yüzeyi yok.
6. **Bayat kapı:** kök neden diyaloğundaki "LLM anahtarı yok" duvarı, platform
   anahtar yedeği (2026-08-26) geldiğinden beri gereksiz yere engelliyor.

## 2. Yeni bilgi hiyerarşisi (ana sayfa)

Hedef sıralama — her blok bir SORUYU yanıtlar, sayı değil hüküm konuşur:

| # | Blok | Soru | İçerik |
|---|------|------|--------|
| 1 | **Kök neden kartları** (YENİ, sayfanın kalbi — ürün sahibi kararı 2026-09-01: en üstte) | Neden? Ne yapmalıyım? | En kötü 3 kategorinin son kök neden analizi: başlık + pay % + **yapılacak iş cümlesi** (bu hafta, var olan kanaldan başlatılabilir) + "Kanıtı gör (n yorum)" → filtreli /reviews |
| 2 | **Bugünkü hüküm** (hero) | Durum ne? | Tek cümle hüküm (mevcut ExecutiveHero, kartların altına iner) | 
| 3 | **Kanıt şeridi** | İnanayım mı? | Kök nedenin evidence_quotes'ları, tıklanınca yorum detayı |
| 4 | **Veri kalitesi koçu** (YENİ) | Analiz ne kadar güvenilir? | "Yorumlarınızın %12'si boş/anlamsız girilmiş — temsilci bazında dökümü gör; veri kalitesi arttıkça kök neden isabeti artar" + en çok sorulan sorular |
| 5 | Sayısal özet | Detay isteyene | NPS/kategori/duygu sayıları (mevcut bileşenler, AŞAĞI iner) |

Teknik dayanaklar (keşiften):
- `GET /insights/root-cause` LLM'e hiç gitmez (cache/DB) → kartları beslemek
  **bedava**; yalnız üretim (POST) paralıdır.
- Otomatik üretim: batch tamamlanınca en negatif 3 (kategori, alt-kategori)
  için arka planda POST eşdeğeri üretim (12 saat cache dedup görevi görür;
  batch başına ~3 GLM çağrısı ≈ 0,05 $). Yeni arka plan işi gerekir.
- Granülerlik: kök neden (kategori + alt-kategori) çifti ister; TopProblems
  kategori bazlı. Köprü: kategori başına en negatif alt-kategoriyi seçen
  hafif bir agregasyon (yeni küçük endpoint ya da drilldown sorgusunun
  yeniden kullanımı).
- Rol/anahtar: VIEWER üretemesin (mevcut kural), üretilmişi herkes görsün;
  anahtar duvarı kaldırıldı (platform yedeği var).

## 3. Reviews sayfası: liste + canlı analiz (bu oturumda uygulanıyor)

Sol: mevcut filtreler + kart listesi (URL-state deseni aynen). Sağ: **filtreye
tepki veren özet paneli** — yeni `GET /tenants/me/reviews/summary` (listeyle
birebir aynı filtre imzası; `include_flagged` varsayılanı listeyle aynı: dahil):
toplam, duygu dağılımı, günlük trend, en çok kategoriler, kaynaklar,
**temsilci matrisi** (toplam/bayraklı/soru/negatif — "hangi temsilci kaç boş
veri girmiş" burada), veri kalitesi kırılımı, **en çok sorulan sorular**,
ticket bağlantı sayısı. Filtre değişince panel değişir.

## 4. "Soru" işareti: kalite bayrağı DEĞİL, içerik türü

"Kargom nerede, ilgilenir misiniz?" hem sorudur hem NEGATİF şikâyettir;
kalite bayrağı yapılsaydı varsayılan olarak TÜM analitikten düşerdi (12+
yüzeydeki `quality_flag IS NULL` kuralı). Karar: `reviews.content_type`
(nullable, CHECK `IN ('question')`, genişletilebilir — experience_type
deseni). Tespit: deterministik Türkçe sezgisel (LLM q-alanı 2026-08-18'de
denenip gold4 gerilemesiyle geri alınmıştı; tekrar denenmez). Sorular
analitikte KALIR; ayrıca filtrelenir, sayılır ve "en çok sorulanlar"
panelinde toplanır. İleride `content_type`e öneri/teşekkür gibi türler
eklenebilir.

## 5. Grafik + tasarım sistemi kararları

- Marka sistemi (lacivert + sinyal turuncusu, OKLCH, Geist) **kalır**; sorun
  paletle değil hiyerarşiyle.
- Duygu renk üçlüsü (kırmızı/gri/yeşil) 4+ dosyada kopyalanmış hex —
  `--color-negative/neutral/positive` token'larına merkezileştirilecek; yeni
  paneller token kullanır (bu oturumda yeni panelde başlanır).
- recharts standart kalır; el yapımı heatmap'in koyu-mod uyumsuzluğu (düz hex
  metin/çizgi renkleri) ayrıca giderilecek.
- Grafik başına kural: her grafiğin üstünde SAYI değil TÜRKÇE HÜKÜM satırı
  ("İade sürecinde memnuniyet 3 aydır düşüyor") — mevcut 3-durum (loading/
  error/empty) konvansiyonu korunur.
- Kopya tonu: yönerge kipi ("...iletmelisiniz"), kaynağı `suggested_action`
  alanı; yeni metin üretimi gerekmiyor, mevcut alan yüzeye çıkıyor.

## 6. Uygulama durumu ve yol haritası

**Bu oturumda uygulanan (Dalga 1-3):**
- Kurum değişince bayat veri düzeltmesi (`resetQueries` + kurum-id'li remount)
- Menü/sayfa bağımsız scroll (+ route değişiminde içerik scrollTop sıfırlama)
- Reviews detayından BERT izlerinin kaldırılması; skor girişinde canlı
  "çok olumsuz…çok olumlu" etiketi (eşikler imga-core ±0.05 bandına demirli)
- Kök neden diyaloğundaki bayat LLM-anahtar duvarının kaldırılması
- `reviews.content_type='question'` + tespit + filtre + sayımlar
- Twitter meta: beğeni/retweet/yanıt/görüntülenme → `reviews.source_meta`
  (JSONB; yazar kimliği KVKK gereği bilinçli olarak ALINMIYOR)
- `GET /reviews/summary` + reviews split-view sağ paneli

**Dalga 4-5 (2026-09-01, "her şeyi tamamla" talimatıyla uygulandı):**
1. Batch-sonrası otomatik kök neden üretimi: arq görevi, gün-yuvarlanmış
   90 günlük pencere (12s cache gerçek dedup olsun diye), kurum başına
   günde bir, <50 yorumlu kurum atlanır, force_refresh asla kullanılmaz
2. `GET /insights/root-cause/overview` + ana sayfa kök neden kartları —
   ürün sahibi kararıyla duygu barının ÜSTÜNDE; kanıt alıntıları
   `/reviews?search=` linkli, pay çipi payda+n ile dürüst
3. Veri kalitesi koçu (summary ucundan beslenir; %5 altında sessiz onay)
4. Duygu token geçişi (insights/operations/compare) + heatmap koyu-mod
   + 9 ölü dashboard bileşeni silindi + detayda tweet etkileşim rozetleri
5. 5-persona uzman paneli (CX danışmanı, C-level, UX yazarı, veri
   analisti, onboarding) — ~25 S/M düzeltme uygulandı: hüküm>skor
   hiyerarşisi, temsilci matrisinde oran+n eşiği (adalet), NPS min-10
   yanıt eşiği, "Bayraklı"→"Geçersiz", model adı ekrandan kalktı,
   sıfır-veri kurum hoş-geldin akışı, viewer rol kopyaları
6. `content_type` backfill'i: 70.387 satır tarandı, 10.093 soru işaretlendi

**Verilen kararlar (2026-09-01):** üretim temposu = batch-sonrası + günlük
dedup; kanıt doğrulama = alıntıdan aramaya link. **Bilinçli ertelenenler:**
"Aksiyona çevir" (sahiplik/atama UX'i ürün kararı ister), `content_type`
tür genişlemesi (öneri/teşekkür — ürün girdisi), viral şikâyet uyarısı
(eşik + kanal kararı; veri artık toplanıyor), kök neden URL-adreslenebilirliği
(kartlar inline gösterince aciliyeti düştü), üç "ne yapmalıyım" yüzeyinin
(kök neden / SWOT / brifing) tekilleştirilmesi (kaynak-of-truth kararı).
