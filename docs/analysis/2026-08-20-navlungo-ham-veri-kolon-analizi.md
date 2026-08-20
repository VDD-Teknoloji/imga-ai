# Navlungo ham veri kolon analizi — 2026-08-20

Kaynak: `Navlungo_Satis_Sonrasi_Talep_SLA_Raporu REVİZE (1).xlsx`
(Freshdesk tarzı destek dökümü, 21.684 satır × 63 kolon, Nisan-Temmuz
2026). "Yorum" doluluğu %76,1 — boş %23,9 (5.184 satır) telefonla
açılıp detaylandırılmamış kayıtlar (bilinen boş-satır vakasıyla birebir).

## Hemen kullanılan kolonlar (bu çalışmada bağlandı)

| Kolon | Doluluk | IMGA alanı | Durum |
|---|---|---|---|
| Oluşturulduğu zaman | %100 | review_date | ✅ 16.500 satıra geri dolduruldu (Nisan 3.497 / Mayıs 3.407 / Haziran 4.680 / Temmuz 4.916); gelecekte otomatik (değer-tabanlı tespit + Adım-2 seçimi) |
| Temsilci | %100 | entered_by | ✅ boyut eşlemesi kuruldu + geçmişe dolduruluyor; çalışan-bazlı kalite kırılımı hazır |
| Kaynak | %100 | source | ✅ geri dolduruluyor (Email/Portal/Phone/Widget/Outbound) |
| Entegratör Firma | %95,5 | channel boyutu ("Entegratör Firma") | ✅ taşıyıcı segmentasyonu (FEDEX/UPS/Widect-THY...) — "hangi taşıyıcı şikâyet üretiyor" |
| Departman | %90,6 | business_segment boyutu ("Departman") | ✅ Operasyon/Muhasebe/Satış/Depo |
| Tür | %90,6 | product_line boyutu ("Talep Tipi") | ✅ Kayıp/Hareketsizlik, Teslimat Gecikmesi, Gümrük... — taksonomiyle çapraz doğrulama kaynağı |
| Ticket Kategori | %99,1 | customer_tier boyutu ("Ticket Kategori") | ✅ Müşteri / Taşıyıcı / Kayıt Dışı |
| Talep Türü | %90,6 | quality_flag (insan etiketi) | ✅ Mükerrer→duplicate, Bilgi→informational (yalnız boş bayraklı satırlara; insan etiketi LLM'siz, bedava ve güvenilir) |
| Etiketler | %93,2 | quality_flag sinyali | ✅ "otomasyon bildirim" etiketi → informational |

## Değerli ama bu turda BİLİNÇLİ ertelenen kolonlar (yol haritası)

1. **SLA gerçekleşmeleri** — Çözüm durumu (%93,7 Within SLA/Violated),
   İlk yanıt durumu (%65,9), Çözüm süresi (saat) (%100), İlk yanıt
   süresi (%100): IMGA'nın SLA kural motoru "beklenen"i tanımlıyor;
   bu kolonlar "gerçekleşen"i taşıyor. Öneri: `review_sla_facts`
   yan-tablosu + taşıyıcı/temsilci/kategori bazında SLA ihlal oranı
   analitiği + ihlal-duygu korelasyonu. (Orta boy modül — ayrı sprint.)
2. **Anket sonuçları (CSAT)** — %3,3 (~700 satır): "Çok memnunum →
   Hiç memnun değilim" gerçek müşteri cevabı. Öneri: 1-5 CSAT alanı +
   sentiment↔CSAT uyum raporu (model kalitesinin sürekli, bedava
   ölçümü). NPS altyapısına paralel ikinci skor olarak.
3. **Etkileşim/efor** — Temsilci etkileşimleri, Müşteri etkileşimleri
   (%100): "kaç mesajda çözüldü" efor metriği; ticket zorluk skoru.
4. **Tazmin/bedel** — Tazmin Onay Durumu, Navlun/Mal Bedeli, İade
   Sebebi (%0,2-0,5): düşük doluluk ama parasal etki analizi için
   tohum (şikâyet → tazmin maliyeti bağlantısı).
5. **Teslimat durumu** — Teslimat Durumu/Detayı (%15): AfterShip
   entegrasyon izi; "Çok Kaplı / Kısmi Teslimat" gibi detaylar
   taksonomiyle örtüşüyor.
6. **Durum/Öncelik** (%100): Freshdesk yaşam döngüsü — IMGA ticket
   modülüyle çift kayıt riski; senkron entegrasyon (API) daha doğru,
   dosya-içi alan olarak taşımak değil.

## Çöp / kullanılmaz kolonlar
Boş (%0): Kaynak Bilgisi, Geri Aranma Talebi, Anket Alt Kırılım, MNG
Takip No, Müşterinin imzası, Randevu*, Hizmet konumu. Sabit: Grup
("Satış Sonrası"), Ürün ("No Product"), Takip edildiği zaman ("00:00").
Kişisel veri içerenler (TCKN/VKN %0,5, Kişi e-postaları, Telefon):
KVKK gereği İÇE ALINMAZ.

## Ürün çıkarımı
"Sentiment+SWOT ürünü" sınırını aşan somut adımlar bu dosyayla
sıralandı: (1) insan etiketli veri kalitesi (bu tur ✅), (2) segment
analitiği — taşıyıcı/departman/temsilci (bu tur ✅ veri + mevcut boyut
kırılımı UI'ı), (3) SLA gerçekleşme modülü (sıradaki en yüksek değer),
(4) CSAT köprüsü, (5) efor metrikleri. Freshdesk API senkronu uzun
vadede dosya yüklemenin yerini alabilir.
